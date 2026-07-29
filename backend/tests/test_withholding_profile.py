from datetime import date
from decimal import Decimal

import pytest

from app.schemas.masters import PartyCreate
from app.schemas.receivables import RetentionInput


def test_party_accepts_expected_withholding_profile() -> None:
    party = PartyCreate(
        name="Cliente de retención",
        identification_type="RUC",
        identification_number="1791233417001",
        roles=["CUSTOMER"],
        expected_iva_withholding_rate=Decimal("100.00"),
        expected_income_withholding_rate=Decimal("3.00"),
        withholding_profile_valid_from=date(2026, 4, 1),
    )
    assert party.expected_iva_withholding_rate == Decimal("100.00")
    assert party.expected_income_withholding_rate == Decimal("3.00")


def test_retention_requires_document_reference() -> None:
    with pytest.raises(ValueError):
        RetentionInput(kind="RETENTION_IVA", amount=Decimal("10.00"), reason="Retención")
