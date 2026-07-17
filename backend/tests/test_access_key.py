"""Pruebas de la clave de acceso SRI (49 digitos, modulo 11).

Los tres vectores base se calcularon a mano (script auxiliar, no versionado)
replicando el algoritmo oficial de la Ficha Tecnica de Comprobantes
Electronicos (Anexo 1: pesos ciclicos 2..7 de derecha a izquierda, con las
excepciones textuales resto 0 -> DV 0 y resto 1 -> DV 1). Se documentan aqui
los 48 digitos base y el digito verificador esperado para que cualquier
refactor del algoritmo se valide contra un resultado conocido, no solo contra
la propia implementacion.
"""

from datetime import date

import pytest

from app.services.access_key import (
    AccessKeyInput,
    build_access_key,
    compute_verifier_digit,
    generate_numeric_code,
    verify_access_key,
)

# Vector 1 (caso general): fecha 04/07/2026, factura (01), RUC 1799999999001,
# ambiente pruebas (1), serie 001-001, secuencial 000000001, codigo numerico
# 12345678, tipo de emision normal (1).
_VECTOR_1_BASE = "040720260117999999990011001001000000001123456781"[:48]
_VECTOR_1_EXPECTED_DV = 7
_VECTOR_1_FULL = _VECTOR_1_BASE + str(_VECTOR_1_EXPECTED_DV)

# Vector 2: mismos datos que el vector 1 salvo codigoNumerico=00000003, elegido
# porque produce suma ponderada % 11 == 0 (caso especial resto 0 -> DV 0).
_VECTOR_2_BASE = "040720260117999999990011001001000000001000000031"[:48]
_VECTOR_2_EXPECTED_DV = 0

# Vector 3: mismos datos que el vector 1 salvo codigoNumerico=00000007, elegido
# porque produce suma ponderada % 11 == 1 (caso especial resto 1 -> DV 1).
_VECTOR_3_BASE = "040720260117999999990011001001000000001000000071"[:48]
_VECTOR_3_EXPECTED_DV = 1


def test_verifier_digit_matches_hand_calculated_vector_1() -> None:
    assert compute_verifier_digit(_VECTOR_1_BASE) == _VECTOR_1_EXPECTED_DV


def test_verifier_digit_handles_remainder_zero_edge_case() -> None:
    """Cuando ``11 - resto`` da 11, la ficha tecnica exige DV=0, no 11."""

    assert compute_verifier_digit(_VECTOR_2_BASE) == _VECTOR_2_EXPECTED_DV


def test_verifier_digit_handles_remainder_one_edge_case() -> None:
    """Cuando ``11 - resto`` da 10, la ficha tecnica exige DV=1, no 10."""

    assert compute_verifier_digit(_VECTOR_3_BASE) == _VECTOR_3_EXPECTED_DV


def test_verifier_digit_rejects_wrong_length() -> None:
    with pytest.raises(ValueError, match="48 numeric digits"):
        compute_verifier_digit("123")


def test_verifier_digit_rejects_non_numeric() -> None:
    with pytest.raises(ValueError, match="48 numeric digits"):
        compute_verifier_digit("a" * 48)


def test_build_access_key_matches_hand_calculated_vector_1() -> None:
    access_key = build_access_key(
        AccessKeyInput(
            issue_date=date(2026, 7, 4),
            document_code="01",
            ruc="1799999999001",
            environment="1",
            establishment_code="001",
            emission_point_code="001",
            sequential="000000001",
            numeric_code="12345678",
        )
    )
    assert access_key == _VECTOR_1_FULL
    assert len(access_key) == 49


def test_build_access_key_is_49_digits_and_all_numeric() -> None:
    access_key = build_access_key(
        AccessKeyInput(
            issue_date=date(2026, 1, 1),
            document_code="04",
            ruc="1790000001001",
            environment="2",
            establishment_code="002",
            emission_point_code="003",
            sequential="000000042",
            numeric_code="00000000",
        )
    )
    assert len(access_key) == 49
    assert access_key.isdigit()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("document_code", "99"),
        ("environment", "9"),
        ("ruc", "123"),
        ("establishment_code", "1"),
        ("emission_point_code", "abc"),
        ("sequential", "1"),
        ("numeric_code", "1"),
        ("emission_type", "2"),
    ],
)
def test_build_access_key_rejects_invalid_fields(field: str, value: str) -> None:
    base_kwargs = dict(
        issue_date=date(2026, 7, 4),
        document_code="01",
        ruc="1799999999001",
        environment="1",
        establishment_code="001",
        emission_point_code="001",
        sequential="000000001",
        numeric_code="12345678",
    )
    base_kwargs[field] = value
    with pytest.raises(ValueError):
        build_access_key(AccessKeyInput(**base_kwargs))  # type: ignore[arg-type]


def test_verify_access_key_accepts_valid_key() -> None:
    assert verify_access_key(_VECTOR_1_FULL) is True


def test_verify_access_key_rejects_tampered_verifier() -> None:
    tampered = _VECTOR_1_BASE + "9"
    assert verify_access_key(tampered) is False


def test_verify_access_key_rejects_wrong_length() -> None:
    assert verify_access_key("123") is False


def test_verify_access_key_rejects_non_numeric() -> None:
    assert verify_access_key("a" * 49) is False


def test_generate_numeric_code_is_8_digits() -> None:
    for _ in range(20):
        code = generate_numeric_code()
        assert len(code) == 8
        assert code.isdigit()
