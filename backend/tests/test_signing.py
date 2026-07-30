"""Pruebas de firma XAdES-BES (base XML-DSig enveloped via ``signxml``).

Cubre: generacion automatica del certificado de prueba si falta, round-trip
firma/verificacion, y estabilidad del fingerprint SHA-256 del certificado
entre invocaciones (mismo .p12 debe producir siempre el mismo fingerprint,
condicion necesaria para poder auditarlo de forma reproducible en
``AuditEvent``).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID
from lxml import etree

from app.services.signing import (
    certificate_fingerprint_sha256,
    load_signing_credentials,
    sign_xml,
    verify_signed_xml,
)

_SAMPLE_XML = (
    b'<factura id="comprobante" version="1.1.0">'
    b"<infoTributaria><ruc>1799999999001</ruc><claveAcceso>"
    b"0407202601179999999900110010010000000011234567817"
    b"</claveAcceso></infoTributaria>"
    b"</factura>"
)


def _p12_with_trust_chain(password: bytes) -> bytes:
    """Crea un PKCS#12 sintético con emisor y certificado firmante."""

    now = datetime.now(UTC)
    root_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    root_subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Test Root CA")])
    root_certificate = (
        x509.CertificateBuilder()
        .subject_name(root_subject)
        .issuer_name(root_subject)
        .public_key(root_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=365))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(root_key, hashes.SHA256())
    )
    signer_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    signer_subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Test Signer")])
    signer_certificate = (
        x509.CertificateBuilder()
        .subject_name(signer_subject)
        .issuer_name(root_subject)
        .public_key(signer_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=365))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(root_key, hashes.SHA256())
    )
    return pkcs12.serialize_key_and_certificates(
        name=b"test-signer",
        key=signer_key,
        cert=signer_certificate,
        cas=[root_certificate],
        encryption_algorithm=serialization.BestAvailableEncryption(password),
    )


@pytest.fixture
def isolated_cert_path(tmp_path: Path) -> Path:
    return tmp_path / "test-signing.p12"


def test_sign_xml_auto_generates_missing_dev_certificate(isolated_cert_path: Path) -> None:
    assert not isolated_cert_path.exists()
    result = sign_xml(_SAMPLE_XML, cert_path=isolated_cert_path)
    assert isolated_cert_path.exists()
    assert len(result.certificate_fingerprint_sha256) == 64
    assert b"Signature" in result.signed_xml


def test_sign_and_verify_round_trip(isolated_cert_path: Path) -> None:
    result = sign_xml(_SAMPLE_XML, cert_path=isolated_cert_path)
    _, certificate_pem, _, _ = load_signing_credentials(cert_path=isolated_cert_path)

    verified_payload = verify_signed_xml(result.signed_xml, certificate_pem=certificate_pem)
    assert b"1799999999001" in verified_payload
    assert b"0407202601179999999900110010010000000011234567817" in verified_payload


def test_sign_xml_rejects_tampered_signature(isolated_cert_path: Path) -> None:
    from signxml.exceptions import InvalidSignature

    result = sign_xml(_SAMPLE_XML, cert_path=isolated_cert_path)
    _, certificate_pem, _, _ = load_signing_credentials(cert_path=isolated_cert_path)

    tampered = result.signed_xml.replace(b"1799999999001", b"1799999999999")
    with pytest.raises((InvalidSignature, Exception)):
        verify_signed_xml(tampered, certificate_pem=certificate_pem)


def test_certificate_fingerprint_is_stable_across_loads(isolated_cert_path: Path) -> None:
    sign_xml(_SAMPLE_XML, cert_path=isolated_cert_path)  # generates the certificate once

    _, _, der_first, _ = load_signing_credentials(cert_path=isolated_cert_path)
    _, _, der_second, _ = load_signing_credentials(cert_path=isolated_cert_path)

    fingerprint_first = certificate_fingerprint_sha256(der_first)
    fingerprint_second = certificate_fingerprint_sha256(der_second)
    assert fingerprint_first == fingerprint_second
    assert len(fingerprint_first) == 64
    assert fingerprint_first == fingerprint_first.upper()


def test_certificate_fingerprint_differs_between_distinct_certificates(tmp_path: Path) -> None:
    first_path = tmp_path / "first.p12"
    second_path = tmp_path / "second.p12"

    first_result = sign_xml(_SAMPLE_XML, cert_path=first_path)
    second_result = sign_xml(_SAMPLE_XML, cert_path=second_path)

    assert (
        first_result.certificate_fingerprint_sha256 != second_result.certificate_fingerprint_sha256
    )


def test_sign_xml_includes_pkcs12_certificate_chain() -> None:
    password = b"test-chain-password"
    result = sign_xml(_SAMPLE_XML, p12_bytes=_p12_with_trust_chain(password), password=password)

    root = etree.fromstring(result.signed_xml)
    certificates = root.xpath(
        "//*[local-name()='KeyInfo']//*[local-name()='X509Certificate']/text()"
    )
    assert len(certificates) == 2


def test_load_signing_credentials_rejects_wrong_password(isolated_cert_path: Path) -> None:
    sign_xml(_SAMPLE_XML, cert_path=isolated_cert_path)
    with pytest.raises(ValueError):
        load_signing_credentials(cert_path=isolated_cert_path, password=b"definitely-wrong")


def test_generate_test_certificate_script_is_idempotent(tmp_path: Path) -> None:
    from scripts.generate_test_certificate import generate_self_signed_p12

    output_path = tmp_path / "cert.p12"
    first = generate_self_signed_p12(output_path=output_path, password=b"pw")
    assert first.exists()
    # Re-running overwrites cleanly (idempotent script execution).
    second = generate_self_signed_p12(output_path=output_path, password=b"pw")
    assert second == first
    assert second.exists()
