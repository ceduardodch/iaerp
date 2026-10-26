"""Formato ATS oficial con identificaciones exclusivamente sintéticas."""

from decimal import Decimal

import pytest

from app.services.tax.ats import AtsInput, AtsSale, build_ats_xml
from app.services.tax.ats_identification import (
    ats_identification_type,
    normalize_ats_identification,
)
from app.services.tax.ats_validation import validate_ats_xml


@pytest.mark.parametrize(
    ("raw", "normalized", "kind"),
    [
        ("12-3456789", "123456789", "06"),
        (" AB 123-456 ", "AB123456", "06"),
        ("ZX1234567890", "ZX1234567890", "06"),
        ("ABC", "ABC", "06"),
        ("1712345678", "1712345678", "05"),
        ("1790000000001", "1790000000001", "04"),
        ("9999999999999", "9999999999999", "07"),
        ("ABC@123", "ABC@123", None),
        ("12345678901234", "12345678901234", None),
        ("AB", "AB", None),
        ("１２３４５６７８９０", "１２３４５６７８９０", None),
    ],
)
def test_identification_preserves_letters_and_removes_only_formatting(raw, normalized, kind):
    assert normalize_ats_identification(raw) == normalized
    assert ats_identification_type(raw, sale=True) == kind


def sample_with_identification(value: str) -> bytes:
    return build_ats_xml(AtsInput(
        identification="1790000000001", legal_name="EMPRESA DEMO", year=2026, month=7,
        sales=[AtsSale(customer_identification=value, customer_identification_type="06",
                       customer_type="01", customer_name="PERSONA DEMO",
                       base_zero_rate=Decimal("100"), payment_methods=["20"])],
    ))


def test_official_xsd_rejects_punctuation_without_echoing_customer_data():
    with pytest.raises(ValueError) as error:
        validate_ats_xml(sample_with_identification("12-3456789"))
    assert "idCliente" in str(error.value)
    assert "12-3456789" not in str(error.value)
    validate_ats_xml(sample_with_identification("123456789"))


def test_official_xsd_rejects_dtd():
    with pytest.raises(ValueError, match="DTD"):
        validate_ats_xml(b'<!DOCTYPE iva [<!ENTITY x "test">]><iva/>')


def test_consumer_final_omits_conditional_related_party_and_foreign_fields():
    from xml.etree.ElementTree import fromstring

    xml = build_ats_xml(AtsInput(
        identification="1790000000001", legal_name="EMPRESA DEMO", year=2026, month=7,
        sales=[AtsSale(customer_identification="9999999999999",
                       customer_identification_type="07", base_zero_rate=Decimal("100"),
                       payment_methods=["20"])],
    ))
    validate_ats_xml(xml)
    sale = fromstring(xml).find(".//detalleVentas")
    assert sale is not None
    assert sale.find("parteRelVtas") is None
    assert sale.find("tipoCliente") is None
    assert sale.find("denoCli") is None
