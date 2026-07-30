"""Firma XAdES-BES del XML de comprobantes SRI.

Esta funcion es pura respecto de I/O de red (no transmite nada) y auditable:
retorna el XML firmado y el fingerprint SHA-256 del certificado usado, para
que el llamador (fase 4, flujo ``issue_document``) lo escriba en
``AuditEvent`` junto con la transicion de estado a ``SIGNED``. No decide
cuando firmar ni persiste nada: solo firma.

El SRI requiere XAdES-BES: XML-DSig enveloped mas ``SignedProperties`` con
``SigningTime`` y ``SigningCertificate``. ``signxml`` conserva aqui la
verificacion local; la construccion de la firma usa ``xades``/``xmlsig``, el
mismo perfil que ya valida el SRI en Sky Franquicia.
"""

from __future__ import annotations

import hashlib
from base64 import b64encode
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import xmlsig
from cryptography.hazmat.primitives.serialization import pkcs12
from lxml import etree
from signxml.algorithms import DigestAlgorithm, SignatureMethod
from signxml.verifier import SignatureConfiguration, XMLVerifier
from xades import XAdESContext, template

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
) -> tuple[bytes, bytes, bytes, list[bytes]]:
    """Carga la clave privada, certificado y bytes DER del certificado desde el .p12.

    Retorna ``(private_key_pem, certificate_pem, certificate_der,
    certificate_chain_pem)``. La cadena conserva los certificados intermedios
    que vienen dentro del PKCS#12, pues el SRI necesita poder construir una
    cadena de confianza desde el certificado firmante.

    Genera el certificado de prueba automaticamente en dev/test si el archivo
    no existe todavia (ver ``_ensure_dev_certificate_exists``).
    """

    resolved_path = cert_path or _resolve_cert_path()
    resolved_password = password if password is not None else _resolve_cert_password()

    if p12_bytes is None:
        _ensure_dev_certificate_exists(resolved_path)

    from cryptography.hazmat.primitives import serialization

    certificate_bytes = p12_bytes if p12_bytes is not None else resolved_path.read_bytes()
    private_key, certificate, additional_certs = pkcs12.load_key_and_certificates(
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
    certificate_chain_pem = [
        additional_certificate.public_bytes(serialization.Encoding.PEM)
        for additional_certificate in additional_certs or []
    ]
    return private_key_pem, certificate_pem, certificate_der, certificate_chain_pem


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

    private_key_pem, certificate_pem, certificate_der, certificate_chain_pem = (
        load_signing_credentials(cert_path=cert_path, password=password, p12_bytes=p12_bytes)
    )

    from cryptography import x509
    from cryptography.hazmat.primitives.serialization import Encoding, load_pem_private_key

    parser = etree.XMLParser(remove_blank_text=True, resolve_entities=False)
    signed_root = etree.fromstring(xml_bytes, parser=parser)
    private_key = load_pem_private_key(private_key_pem, password=None)
    certificate = x509.load_pem_x509_certificate(certificate_pem)

    signature = xmlsig.template.create(
        xmlsig.constants.TransformInclC14N,
        # El perfil que SRI acepta para comprobantes offline usa RSA/SHA-1.
        # Se mantiene por compatibilidad fiscal, limitado a esta firma XAdES.
        xmlsig.constants.TransformRsaSha1,
        name="Signature",
    )
    signed_root.append(signature)
    reference = xmlsig.template.add_reference(
        signature,
        xmlsig.constants.TransformSha1,
        uri="#comprobante",
    )
    xmlsig.template.add_transform(reference, xmlsig.constants.TransformEnveloped)
    xmlsig.template.add_transform(reference, xmlsig.constants.TransformInclC14N)

    key_info = xmlsig.template.ensure_key_info(signature)
    x509_data = xmlsig.template.add_x509_data(key_info)
    xmlsig.template.x509_data_add_certificate(x509_data)

    qualifying_properties = template.create_qualifying_properties(signature)
    signed_properties = template.create_signed_properties(
        qualifying_properties,
        name="SignedProperties",
        datetime=datetime.now(UTC).replace(tzinfo=None),
    )
    signed_properties_reference = xmlsig.template.add_reference(
        signature,
        xmlsig.constants.TransformSha1,
        uri=f"#{signed_properties.get('Id')}",
        uri_type="http://uri.etsi.org/01903#SignedProperties",
    )
    xmlsig.template.add_transform(
        signed_properties_reference,
        xmlsig.constants.TransformInclC14N,
    )

    context = XAdESContext()
    context.x509 = certificate
    context.public_key = certificate.public_key()
    context.private_key = private_key
    context.sign(signature)

    # KeyInfo no forma parte de SignedInfo; se anexan los intermedios luego de
    # firmar para que el SRI pueda construir la cadena del certificado firmante.
    x509_certificate_tag = "{http://www.w3.org/2000/09/xmldsig#}X509Certificate"
    for chain_certificate_pem in certificate_chain_pem:
        chain_certificate = x509.load_pem_x509_certificate(chain_certificate_pem)
        etree.SubElement(x509_data, x509_certificate_tag).text = b64encode(
            chain_certificate.public_bytes(encoding=Encoding.DER)
        ).decode("ascii")

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
        expect_config=SignatureConfiguration(
            expect_references=2,
            signature_methods=frozenset({SignatureMethod.RSA_SHA1}),
            digest_algorithms=frozenset({DigestAlgorithm.SHA1}),
        ),
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
