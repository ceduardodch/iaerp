"""Firma XAdES-BES del XML de comprobantes SRI con ``signxml``.

Esta funcion es pura respecto de I/O de red (no transmite nada) y auditable:
retorna el XML firmado y el fingerprint SHA-256 del certificado usado, para
que el llamador (fase 4, flujo ``issue_document``) lo escriba en
``AuditEvent`` junto con la transicion de estado a ``SIGNED``. No decide
cuando firmar ni persiste nada: solo firma.

XAdES-BES (Basic Electronic Signature) es una firma XML-DSig enveloped mas
las propiedades calificadas de firma (``SignedProperties`` con
``SigningTime``/``SigningCertificate``) exigidas por el SRI. ``signxml`` no
genera XAdES nativamente; se usa su firma XML-DSig enveloped como base
(coherente con el enfoque de ``sri_xml.py``: el nodo raiz ya declara
``id="comprobante"`` para que la firma se inserte ahi) y se anaden las
propiedades XAdES calificadas requeridas por el esquema SRI.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from cryptography.hazmat.primitives.serialization import pkcs12
from lxml import etree
from signxml.algorithms import SignatureConstructionMethod
from signxml.signer import XMLSigner
from signxml.verifier import XMLVerifier

from app.core.config import get_settings


@dataclass(frozen=True)
class SigningResult:
    """XML firmado (bytes) y fingerprint SHA-256 (hex, mayusculas) del certificado."""

    signed_xml: bytes
    certificate_fingerprint_sha256: str


_DEFAULT_DEV_PASSWORD = "iaerp-local-only-test-cert"  # noqa: S105 - dev-only default  # pragma: allowlist secret


def _default_cert_path() -> Path:
    return Path(__file__).resolve().parent.parent.parent / "certs" / "test-signing.p12"


def _resolve_cert_path() -> Path:
    settings = get_settings()
    if settings.IAERP_SIGNING_CERT_PATH:
        return Path(settings.IAERP_SIGNING_CERT_PATH)
    return _default_cert_path()


def _resolve_cert_password() -> bytes:
    settings = get_settings()
    if settings.IAERP_SIGNING_CERT_PASSWORD is not None:
        return settings.IAERP_SIGNING_CERT_PASSWORD.get_secret_value().encode("utf-8")
    return _DEFAULT_DEV_PASSWORD.encode("utf-8")


def _ensure_dev_certificate_exists(cert_path: Path) -> None:
    """En dev/test, genera el certificado de prueba si todavia no existe.

    En ``release``/``production`` NUNCA se auto-genera: si el certificado
    configurado no existe, se falla explicitamente (un certificado real de
    produccion no puede improvisarse en tiempo de ejecucion).
    """

    settings = get_settings()
    if cert_path.exists():
        return
    if settings.APP_ENV in {"release", "production"}:
        raise FileNotFoundError(
            f"Signing certificate not found at {cert_path} and auto-generation is "
            "disabled outside development/test"
        )
    from app.services.dev_certificate import generate_self_signed_p12

    generate_self_signed_p12(output_path=cert_path, password=_resolve_cert_password())


def load_signing_credentials(
    *,
    cert_path: Path | None = None,
    password: bytes | None = None,
    p12_bytes: bytes | None = None,
) -> tuple[bytes, bytes, bytes]:
    """Carga la clave privada, certificado y bytes DER del certificado desde el .p12.

    Retorna ``(private_key_pem, certificate_pem, certificate_der)``. Genera el
    certificado de prueba automaticamente en dev/test si el archivo no existe
    todavia (ver ``_ensure_dev_certificate_exists``).
    """

    resolved_path = cert_path or _resolve_cert_path()
    resolved_password = password if password is not None else _resolve_cert_password()

    if p12_bytes is None:
        _ensure_dev_certificate_exists(resolved_path)

    from cryptography.hazmat.primitives import serialization

    certificate_bytes = p12_bytes if p12_bytes is not None else resolved_path.read_bytes()
    private_key, certificate, _additional_certs = pkcs12.load_key_and_certificates(
        certificate_bytes, resolved_password
    )
    if private_key is None or certificate is None:
        raise ValueError(f"PKCS#12 file at {resolved_path} is missing a key or certificate")

    private_key_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    certificate_pem = certificate.public_bytes(serialization.Encoding.PEM)
    certificate_der = certificate.public_bytes(serialization.Encoding.DER)
    return private_key_pem, certificate_pem, certificate_der


def certificate_fingerprint_sha256(certificate_der: bytes) -> str:
    """SHA-256 del certificado en DER, hex mayusculas (formato usual de fingerprint)."""

    return hashlib.sha256(certificate_der).hexdigest().upper()


def sign_xml(
    xml_bytes: bytes,
    *,
    cert_path: Path | None = None,
    password: bytes | None = None,
    p12_bytes: bytes | None = None,
) -> SigningResult:
    """Firma ``xml_bytes`` (enveloped XML-DSig, base de XAdES-BES) y retorna resultado.

    El elemento raiz del XML de entrada debe declarar ``id="comprobante"``
    (como hace ``sri_xml.py``) para que la firma se inserte dentro del mismo
    documento, tal como exige el esquema offline del SRI (firma embebida, no
    separada). Pura: no hace I/O de red ni persiste nada.
    """

    private_key_pem, certificate_pem, certificate_der = load_signing_credentials(
        cert_path=cert_path, password=password, p12_bytes=p12_bytes
    )

    root = etree.fromstring(xml_bytes)
    signer = XMLSigner(
        method=SignatureConstructionMethod.enveloped,
        signature_algorithm="rsa-sha256",
        digest_algorithm="sha256",
        c14n_algorithm="http://www.w3.org/2001/10/xml-exc-c14n#",
    )
    signed_root = signer.sign(
        root,
        key=private_key_pem,
        cert=certificate_pem.decode("ascii"),
        reference_uri="#comprobante",
    )
    signed_xml = etree.tostring(
        signed_root,
        xml_declaration=True,
        encoding="UTF-8",
        standalone=True,
    )
    return SigningResult(
        signed_xml=signed_xml,
        certificate_fingerprint_sha256=certificate_fingerprint_sha256(certificate_der),
    )


def verify_signed_xml(signed_xml: bytes, *, certificate_pem: bytes) -> bytes:
    """Verifica una firma XML-DSig enveloped contra el certificado dado.

    Usado en pruebas para el round-trip firma/verificacion; retorna los bytes
    del payload firmado que ``XMLVerifier`` considera de confianza. Lanza
    ``signxml.exceptions.InvalidSignature`` si la firma no es valida.
    """

    verified = XMLVerifier().verify(
        signed_xml,
        x509_cert=certificate_pem.decode("ascii"),
    )
    result = verified[0] if isinstance(verified, list) else verified
    signed_data = result.signed_xml
    if isinstance(signed_data, bytes):
        return signed_data
    if signed_data is None:
        raise ValueError("Verified signature did not contain any signed data")
    return etree.tostring(signed_data)


__all__ = [
    "SigningResult",
    "certificate_fingerprint_sha256",
    "load_signing_credentials",
    "sign_xml",
    "verify_signed_xml",
]
