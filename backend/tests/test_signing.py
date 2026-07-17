"""Pruebas de firma XAdES-BES (base XML-DSig enveloped via ``signxml``).

Cubre: generacion automatica del certificado de prueba si falta, round-trip
firma/verificacion, y estabilidad del fingerprint SHA-256 del certificado
entre invocaciones (mismo .p12 debe producir siempre el mismo fingerprint,
condicion necesaria para poder auditarlo de forma reproducible en
``AuditEvent``).
"""

from __future__ import annotations

from pathlib import Path

import pytest

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
    _, certificate_pem, _ = load_signing_credentials(cert_path=isolated_cert_path)

    verified_payload = verify_signed_xml(result.signed_xml, certificate_pem=certificate_pem)
    assert b"1799999999001" in verified_payload
    assert b"0407202601179999999900110010010000000011234567817" in verified_payload


def test_sign_xml_rejects_tampered_signature(isolated_cert_path: Path) -> None:
    from signxml.exceptions import InvalidSignature

    result = sign_xml(_SAMPLE_XML, cert_path=isolated_cert_path)
    _, certificate_pem, _ = load_signing_credentials(cert_path=isolated_cert_path)

    tampered = result.signed_xml.replace(b"1799999999001", b"1799999999999")
    with pytest.raises((InvalidSignature, Exception)):
        verify_signed_xml(tampered, certificate_pem=certificate_pem)


def test_certificate_fingerprint_is_stable_across_loads(isolated_cert_path: Path) -> None:
    sign_xml(_SAMPLE_XML, cert_path=isolated_cert_path)  # generates the certificate once

    _, _, der_first = load_signing_credentials(cert_path=isolated_cert_path)
    _, _, der_second = load_signing_credentials(cert_path=isolated_cert_path)

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
        first_result.certificate_fingerprint_sha256
        != second_result.certificate_fingerprint_sha256
    )


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
