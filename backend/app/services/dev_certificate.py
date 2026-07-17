"""Genera un certificado RSA autofirmado de PRUEBA para firmar XML XAdES-BES.

Vive en el paquete ``app`` (no en ``scripts/``) para que este disponible dentro
de la imagen del contenedor: ``signing.py`` lo invoca automaticamente en
dev/test cuando el ``.p12`` configurado no existe todavia. El script CLI
``scripts/generate_test_certificate.py`` reexporta esta funcion.

Este certificado es SOLO para dev/test: nunca reemplaza al certificado real
emitido por una entidad de certificacion acreditada que el SRI exige en
produccion (fuera de alcance de Sprint 2, ver docs/sprints/sprint-02.md "No
incluido"). El archivo generado NUNCA se versiona: ``backend/certs/`` y
``*.p12``/``*.pfx`` estan en ``.gitignore``.
"""

from __future__ import annotations

import datetime
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID


def generate_self_signed_p12(
    *,
    output_path: Path,
    password: bytes,
    common_name: str = "IAERP Dev Signing Certificate",
    valid_days: int = 365,
) -> Path:
    """Genera clave RSA-2048 + certificado autofirmado y los empaqueta en PKCS#12.

    Retorna la ruta del archivo escrito. Sobrescribe el archivo si ya existe,
    para que reejecutar en dev sea idempotente y siempre produzca un
    certificado fresco (util si la passphrase cambio).
    """

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    subject = issuer = x509.Name(
        [
            x509.NameAttribute(NameOID.COUNTRY_NAME, "EC"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "IAERP Dev"),
            x509.NameAttribute(NameOID.COMMON_NAME, common_name),
        ]
    )
    now = datetime.datetime.now(datetime.UTC)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(days=valid_days))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=True,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .sign(private_key, hashes.SHA256())
    )

    pkcs12_bytes = pkcs12.serialize_key_and_certificates(
        name=b"iaerp-dev-signing",
        key=private_key,
        cert=certificate,
        cas=None,
        encryption_algorithm=serialization.BestAvailableEncryption(password),
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(pkcs12_bytes)
    # Restrict permissions best-effort; on some filesystems (e.g. certain CI
    # runners) chmod is a no-op, which is acceptable since this is dev/test-only.
    output_path.chmod(0o600)
    return output_path


__all__ = ["generate_self_signed_p12"]
