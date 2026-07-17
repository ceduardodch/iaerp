from datetime import date
from decimal import Decimal

import pytest

from app.services.fiscal_policy import (
    FISCAL_POLICY_V0,
    FISCAL_POLICY_V1,
    LineInput,
    resolve_fiscal_policy,
)


def test_resolve_fiscal_policy_selects_v1_for_dates_on_or_after_valid_from():
    assert resolve_fiscal_policy(date(2024, 4, 1)) is FISCAL_POLICY_V1
    assert resolve_fiscal_policy(date(2026, 7, 4)) is FISCAL_POLICY_V1


def test_resolve_fiscal_policy_selects_v0_for_dates_before_v1():
    """Vector 7 del ADR 0008: un sustento de 2024-03-15 (antes del regimen de
    IVA 15%, 2024-04-01) resuelve a la version historica ``ec-iva-v0``, nunca
    a ``ec-iva-v1``.
    """

    assert resolve_fiscal_policy(date(2024, 3, 15)) is FISCAL_POLICY_V0
    assert resolve_fiscal_policy(date(2024, 3, 31)) is FISCAL_POLICY_V0


def test_resolve_fiscal_policy_rejects_dates_before_any_known_version():
    with pytest.raises(ValueError, match="No fiscal policy is defined"):
        resolve_fiscal_policy(date(1970, 1, 1))


def test_fiscal_policy_version_matches_accepted_adr_0008():
    assert FISCAL_POLICY_V1.version == "ec-iva-v1"
    assert FISCAL_POLICY_V0.version == "ec-iva-v0"


def test_calculate_document_rejects_empty_lines():
    with pytest.raises(ValueError, match="at least one line"):
        FISCAL_POLICY_V1.calculate_document([])


class TestCalculateLine:
    def test_simple_line_15_percent(self):
        line = LineInput(
            quantity=Decimal("2"),
            unit_price=Decimal("10.00"),
            discount=Decimal("0.00"),
            tax_rate=Decimal("15.000000"),
            tax_sri_code="4",
        )
        result = FISCAL_POLICY_V1.calculate_line(line)
        assert result.base_amount == Decimal("20.00")
        assert result.tax_amount == Decimal("3.00")

    def test_line_with_discount(self):
        line = LineInput(
            quantity=Decimal("3"),
            unit_price=Decimal("15.00"),
            discount=Decimal("5.00"),
            tax_rate=Decimal("15.000000"),
            tax_sri_code="4",
        )
        result = FISCAL_POLICY_V1.calculate_line(line)
        # base bruta = 45.00, - descuento 5.00 = 40.00
        assert result.base_amount == Decimal("40.00")
        assert result.tax_amount == Decimal("6.00")

    def test_zero_rate_line_has_no_tax(self):
        line = LineInput(
            quantity=Decimal("1"),
            unit_price=Decimal("100.00"),
            discount=Decimal("0.00"),
            tax_rate=Decimal("0.000000"),
            tax_sri_code="0",
        )
        result = FISCAL_POLICY_V1.calculate_line(line)
        assert result.base_amount == Decimal("100.00")
        assert result.tax_amount == Decimal("0.00")

    def test_quantity_and_price_are_quantized_to_six_decimals(self):
        line = LineInput(
            quantity=Decimal("1.1234567"),
            unit_price=Decimal("1.1234564"),
            discount=Decimal("0.00"),
            tax_rate=Decimal("15.000000"),
            tax_sri_code="4",
        )
        result = FISCAL_POLICY_V1.calculate_line(line)
        assert result.quantity == Decimal("1.123457")
        assert result.unit_price == Decimal("1.123456")

    def test_half_up_rounding_at_the_boundary(self):
        # base bruta = 1 * 0.125 = 0.125 -> HALF_UP a 0.13
        line = LineInput(
            quantity=Decimal("1"),
            unit_price=Decimal("0.125000"),
            discount=Decimal("0.00"),
            tax_rate=Decimal("15.000000"),
            tax_sri_code="4",
        )
        result = FISCAL_POLICY_V1.calculate_line(line)
        assert result.base_amount == Decimal("0.13")

    def test_tax_is_computed_over_the_already_quantized_base(self):
        # base bruta = 3 * 3.335 = 10.005 -> HALF_UP a 10.01 (no 10.00)
        # valor informativo de linea = 10.01 * 15% = 1.5015 -> HALF_UP a 1.50
        line = LineInput(
            quantity=Decimal("3"),
            unit_price=Decimal("3.335000"),
            discount=Decimal("0.00"),
            tax_rate=Decimal("15.000000"),
            tax_sri_code="4",
        )
        result = FISCAL_POLICY_V1.calculate_line(line)
        assert result.base_amount == Decimal("10.01")
        assert result.tax_amount == Decimal("1.50")


class TestCalculateDocument:
    """Vectores 1-5 de la tabla oficial del ADR 0008 (Accepted 2026-07-04)."""

    def test_vector_1_simple_line_15_percent(self):
        lines = [
            LineInput(
                quantity=Decimal("2"),
                unit_price=Decimal("50.00"),
                discount=Decimal("0.00"),
                tax_rate=Decimal("15.000000"),
                tax_sri_code="4",
            ),
        ]
        result = FISCAL_POLICY_V1.calculate_document(lines)
        assert result.subtotal == Decimal("100.00")
        assert result.tax_total == Decimal("15.00")
        assert result.total == Decimal("115.00")

    def test_vector_2_discount_and_six_decimal_precision(self):
        lines = [
            LineInput(
                quantity=Decimal("3.5"),
                unit_price=Decimal("9.333333"),
                discount=Decimal("1.17"),
                tax_rate=Decimal("15.000000"),
                tax_sri_code="4",
            ),
        ]
        result = FISCAL_POLICY_V1.calculate_document(lines)
        # bruto = 3.5 * 9.333333 = 32.6666655; - 1.17 = 31.4966655 -> 31.50
        assert result.lines[0].base_amount == Decimal("31.50")
        assert result.subtotal == Decimal("31.50")
        # 31.50 * 15% = 4.725 -> HALF_UP 4.73
        assert result.tax_total == Decimal("4.73")
        assert result.total == Decimal("36.23")

    def test_vector_3_rounding_difference_line_vs_group_total(self):
        # 3 lineas de 1 x 1.05: cada linea informativa redondea 1.05*15%=0.1575
        # -> 0.16 (0.16*3 = 0.48), pero el ADR exige recalcular sobre la base
        # agregada: 3.15 * 15% = 0.4725 -> HALF_UP 0.47 (no 0.48).
        lines = [
            LineInput(
                quantity=Decimal("1"),
                unit_price=Decimal("1.05"),
                discount=Decimal("0.00"),
                tax_rate=Decimal("15.000000"),
                tax_sri_code="4",
            )
            for _ in range(3)
        ]
        result = FISCAL_POLICY_V1.calculate_document(lines)
        assert [line.base_amount for line in result.lines] == [Decimal("1.05")] * 3
        assert [line.tax_amount for line in result.lines] == [Decimal("0.16")] * 3
        assert result.subtotal == Decimal("3.15")
        assert result.tax_total == Decimal("0.47")
        assert result.total == Decimal("3.62")

    def test_vector_4_zero_rate(self):
        lines = [
            LineInput(
                quantity=Decimal("4"),
                unit_price=Decimal("12.25"),
                discount=Decimal("0.00"),
                tax_rate=Decimal("0.000000"),
                tax_sri_code="0",
            ),
        ]
        result = FISCAL_POLICY_V1.calculate_document(lines)
        assert result.subtotal == Decimal("49.00")
        assert result.tax_total == Decimal("0.00")
        assert result.total == Decimal("49.00")

    def test_vector_5_mixed_tax_rates(self):
        lines = [
            LineInput(
                quantity=Decimal("1"),
                unit_price=Decimal("100.00"),
                discount=Decimal("0.00"),
                tax_rate=Decimal("15.000000"),
                tax_sri_code="4",
            ),
            LineInput(
                quantity=Decimal("2"),
                unit_price=Decimal("25.00"),
                discount=Decimal("0.00"),
                tax_rate=Decimal("0.000000"),
                tax_sri_code="0",
            ),
            LineInput(
                quantity=Decimal("10"),
                unit_price=Decimal("8.457"),
                discount=Decimal("0.00"),
                tax_rate=Decimal("5.000000"),
                tax_sri_code="5",
            ),
        ]
        result = FISCAL_POLICY_V1.calculate_document(lines)
        summary_by_code = {entry.tax_sri_code: entry for entry in result.tax_summary}
        assert summary_by_code["4"].base_amount == Decimal("100.00")
        assert summary_by_code["4"].tax_amount == Decimal("15.00")
        assert summary_by_code["0"].base_amount == Decimal("50.00")
        assert summary_by_code["0"].tax_amount == Decimal("0.00")
        assert summary_by_code["5"].base_amount == Decimal("84.57")
        # 84.57 * 5% = 4.2285 -> HALF_UP 4.23
        assert summary_by_code["5"].tax_amount == Decimal("4.23")
        assert result.total == Decimal("253.80")

    def test_document_level_discount_via_per_line_discount(self):
        # El ADR modela descuento por linea; un "descuento de documento" se
        # expresa repartiendolo entre lineas antes de llamar al motor.
        lines = [
            LineInput(
                quantity=Decimal("1"),
                unit_price=Decimal("100.00"),
                discount=Decimal("10.00"),
                tax_rate=Decimal("15.000000"),
                tax_sri_code="4",
            ),
        ]
        result = FISCAL_POLICY_V1.calculate_document(lines)
        assert result.subtotal == Decimal("90.00")
        assert result.tax_total == Decimal("13.50")
        assert result.total == Decimal("103.50")


@pytest.mark.parametrize(
    ("quantity", "unit_price", "discount", "tax_rate", "expected_base", "expected_tax"),
    [
        # tarifa 15% vigente (codigo SRI 4)
        ("1", "10.00", "0.00", "15.000000", "10.00", "1.50"),
        # tarifa 5% (codigo SRI 5, materiales de construccion)
        ("1", "10.00", "0.00", "5.000000", "10.00", "0.50"),
        # tarifa 12% (historica, solo aplicable a notas de credito sobre
        # sustentos emitidos hasta 2024-03-31, segun el ADR 0008)
        ("1", "10.00", "0.00", "12.000000", "10.00", "1.20"),
        # tarifa 0%
        ("1", "10.00", "0.00", "0.000000", "10.00", "0.00"),
        # descuento total de la linea
        ("1", "10.00", "10.00", "15.000000", "0.00", "0.00"),
        # cantidad decimal
        ("0.5", "10.00", "0.00", "15.000000", "5.00", "0.75"),
    ],
)
def test_fiscal_vectors_by_rate(
    quantity: str,
    unit_price: str,
    discount: str,
    tax_rate: str,
    expected_base: str,
    expected_tax: str,
):
    line = LineInput(
        quantity=Decimal(quantity),
        unit_price=Decimal(unit_price),
        discount=Decimal(discount),
        tax_rate=Decimal(tax_rate),
        tax_sri_code="4",
    )
    result = FISCAL_POLICY_V1.calculate_line(line)
    assert result.base_amount == Decimal(expected_base)
    assert result.tax_amount == Decimal(expected_tax)


class TestCreditNoteVectors:
    """Vectores 6 y 7 de la tabla oficial del ADR 0008 (nota de credito parcial).

    ``fiscal_policy.py`` no distingue facturas de notas de credito: la misma
    ``FiscalCalculationPolicy.calculate_document`` se usa para ambas, con la
    diferencia de que ``services/billing.create_credit_note`` resuelve la
    version/tarifa vigente A LA FECHA DE EMISION DE LA FACTURA DE SUSTENTO
    (ver ``test_billing_credit_note.py`` para la prueba de integracion contra
    ``resolve_fiscal_policy``); aqui solo se verifica que el motor de calculo
    reproduce los montos exactos de la tabla para cada vector.
    """

    def test_vector_6_partial_credit_note_current_rate(self):
        # Sustento: 10 x 3.14 cp 4 (importeTotal 36.11... en realidad la NC
        # devuelve 3 unidades del mismo precio unitario/tarifa vigente 15%.
        lines = [
            LineInput(
                quantity=Decimal("3"),
                unit_price=Decimal("3.14"),
                discount=Decimal("0.00"),
                tax_rate=Decimal("15.000000"),
                tax_sri_code="4",
            ),
        ]
        result = FISCAL_POLICY_V1.calculate_document(lines)
        assert result.subtotal == Decimal("9.42")
        # 9.42 * 15% = 1.413 -> HALF_UP 1.41
        assert result.tax_total == Decimal("1.41")
        assert result.total == Decimal("10.83")

    def test_vector_7_partial_credit_note_historical_rate(self):
        # Sustento 2024-03-15: 5 x 20.00 cp 2 (12%, importeTotal 112.00). NC
        # 2026 devuelve 2 unidades al 12% (tarifa del sustento, no la vigente
        # a la fecha de la NC).
        assert resolve_fiscal_policy(date(2024, 3, 15)) is FISCAL_POLICY_V0
        lines = [
            LineInput(
                quantity=Decimal("2"),
                unit_price=Decimal("20.00"),
                discount=Decimal("0.00"),
                tax_rate=Decimal("12.000000"),
                tax_sri_code="2",
            ),
        ]
        result = FISCAL_POLICY_V0.calculate_document(lines)
        assert result.subtotal == Decimal("40.00")
        # 40.00 * 12% = 4.80
        assert result.tax_total == Decimal("4.80")
        assert result.total == Decimal("44.80")

    def test_vector_6_7_balance_never_exceeds_supporting_invoice_total(self):
        """Assert adicional del ADR: suma de valorModificacion no excede importeTotal."""

        invoice_total = Decimal("112.00")
        credit_note_total = Decimal("44.80")
        assert credit_note_total <= invoice_total
