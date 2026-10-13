"""Zero-value fiscal receipts must not create a supplier debt or abort a batch."""

from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.db.session import SessionFactory
from app.models.payables import Payable, PayableInstallment
from app.models.platform import AutomationSettings
from app.models.tax import FiscalDocument
from tests.test_tax_foundation import TENANT_A, TENANT_B, auth, token_for
from tests.test_tax_received_reports import (
    REPORT_MONTH,
    REPORT_YEAR,
    _merge_reports,
    _report,
    _upload,
    stored_objects,  # noqa: F401 - share the private storage fixture
)


@pytest.mark.parametrize("route", ["monthly", "bulk"])
@pytest.mark.usefixtures("stored_objects")
@pytest.mark.parametrize(
    ("label", "document_code"),
    [("Factura", "01"), ("Liquidación de compra", "03"), ("Nota de débito", "05")],
)
async def test_zero_receipt_preserved_without_debt_and_batch_is_idempotent(
    client, route, label, document_code
) -> None:
    token = await token_for(client, "a@iaerp.local", TENANT_A, ["tax:read", "tax:write"])
    async with SessionFactory.begin() as session:
        settings = await session.get(AutomationSettings, TENANT_A)
        assert settings is not None
        settings.writes_enabled = True

    zero = _report(label=label, document_code=document_code).replace(
        b"10.00\t1.50\t11.50", b"0.00\t0.00\t0.00"
    )
    content = _merge_reports(zero, _report(sequential=2))
    if route == "monthly":
        evidence_id = await _upload(client, token, "zero-receipts.txt", content)

    for attempt in range(2):
        headers = auth(token, f"zero-{route}-{document_code}-{attempt:04d}")
        if route == "monthly":
            response = await client.post(
                "/api/v1/tax/received-reports/process",
                headers=headers,
                json={
                    "evidenceIds": [evidence_id],
                    "reportYear": REPORT_YEAR,
                    "reportMonth": REPORT_MONTH,
                },
            )
            assert response.status_code == 201, response.text
            assert response.json()["listedRows"] == 2
        else:
            response = await client.post(
                "/api/v1/tax/evidence/bulk",
                headers=headers,
                files={"files": ("zero-receipts.txt", content, "text/plain")},
                data={"apply": "true"},
            )
            assert response.status_code == 200, response.text
            assert response.json()["errors"] == 0

    async with SessionFactory() as session:
        documents = list(await session.scalars(select(FiscalDocument)))
        assert len(documents) == 2
        zero_document = next(item for item in documents if item.total == Decimal("0.00"))
        assert zero_document.tenant_id == TENANT_A
        assert zero_document.is_preliminary
        assert zero_document.evidence_id is not None
        payables = list(await session.scalars(select(Payable)))
        assert len(payables) == 1
        assert payables[0].total == Decimal("11.50")
        assert payables[0].fiscal_document_id != zero_document.id
        assert await session.scalar(select(func.count()).select_from(PayableInstallment)) == 1
        assert await session.scalar(
            select(func.count()).select_from(FiscalDocument).where(
                FiscalDocument.tenant_id == TENANT_B
            )
        ) == 0
