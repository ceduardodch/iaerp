"""Contrato MCP del flujo diario de reportes recibidos del SRI."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.db.session import SessionFactory
from app.models.payables import Payable
from app.models.tax import FiscalDocument, TaxPeriod
from app.services import storage
from app.services.tax import evidence as evidence_service
from tests.conftest import TENANT_B
from tests.test_billing_api import TENANT_A, token_for
from tests.test_mcp_receivables import (
    _enable_automation_writes,
    mcp_lifespan,
    mcp_session,
)
from tests.test_tax_received_reports import (
    REPORT_MONTH,
    REPORT_YEAR,
    _report,
    _upload,
)


@pytest.fixture
def stored_objects(monkeypatch) -> dict[str, bytes]:
    objects: dict[str, bytes] = {}

    async def upload(*, object_key: str, data: bytes, **_kwargs) -> None:
        objects[object_key] = data

    async def download(*, object_key: str) -> bytes:
        return objects[object_key]

    monkeypatch.setattr(evidence_service.storage, "upload_private_object", upload)
    monkeypatch.setattr(storage, "download_artifact", download)
    return objects


async def test_mcp_tax_catalog_is_filtered_by_scope(client) -> None:
    without_tax = await token_for(client, "a@iaerp.local", TENANT_A, ["context:read"])
    with_tax = await token_for(client, "a@iaerp.local", TENANT_A, ["tax:write"])

    async with mcp_lifespan():
        async with mcp_session(without_tax) as session:
            tools = await session.list_tools()
            assert "tax.process_received_reports" not in {tool.name for tool in tools.tools}

        async with mcp_session(with_tax) as session:
            tools = await session.list_tools()
            assert "tax.process_received_reports" in {tool.name for tool in tools.tools}


async def test_mcp_tax_process_requires_kill_switch_and_reuses_rest_case(
    client,
    stored_objects,
) -> None:
    token = await token_for(
        client,
        "a@iaerp.local",
        TENANT_A,
        ["tax:write", "automation:write"],
    )
    evidence_id = await _upload(client, token, "facturas.txt", _report())
    arguments = {
        "evidenceIds": [evidence_id],
        "reportYear": REPORT_YEAR,
        "reportMonth": REPORT_MONTH,
        "idempotencyKey": "mcp-tax-reports-20260830",
    }

    async with mcp_lifespan():
        async with mcp_session(token) as session:
            blocked = await session.call_tool("tax.process_received_reports", arguments)
            assert blocked.isError is True
            assert "Automation writes are disabled" in blocked.content[0].text

        await _enable_automation_writes(client, token, "mcp-tax-enable-0001")

        async with mcp_session(token) as session:
            processed = await session.call_tool("tax.process_received_reports", arguments)
            replay = await session.call_tool("tax.process_received_reports", arguments)

    assert processed.isError is False
    assert replay.isError is False
    assert replay.structuredContent == processed.structuredContent
    body = processed.structuredContent
    assert body["reportYear"] == REPORT_YEAR
    assert body["reportMonth"] == REPORT_MONTH
    assert body["evidenceCount"] == 1
    assert body["listedRows"] == 1
    assert body["recoveryJob"]["status"] == "QUEUED"


async def test_mcp_tax_rejects_report_from_another_month(client, stored_objects) -> None:
    token = await token_for(
        client,
        "a@iaerp.local",
        TENANT_A,
        ["tax:write", "automation:write"],
    )
    evidence_id = await _upload(client, token, "facturas.txt", _report())
    await _enable_automation_writes(client, token, "mcp-tax-enable-date")

    async with mcp_lifespan(), mcp_session(token) as session:
        result = await session.call_tool(
            "tax.process_received_reports",
            {
                "evidenceIds": [evidence_id],
                "reportYear": 2026,
                "reportMonth": 7,
                "idempotencyKey": "mcp-tax-wrong-date-0001",
            },
        )

    assert result.isError is True
    assert "Every report row must match reportYear and reportMonth" in result.content[0].text


async def test_mcp_tax_contract_is_closed_and_rejects_tenant_override(client) -> None:
    token = await token_for(client, "a@iaerp.local", TENANT_A, ["tax:write"])

    async with mcp_lifespan(), mcp_session(token) as session:
        tools = await session.list_tools()
        tool = next(item for item in tools.tools if item.name == "tax.process_received_reports")
        result = await session.call_tool(
            tool.name,
            {
                "evidenceIds": ["00000000-0000-0000-0000-000000000001"],
                "reportYear": REPORT_YEAR,
                "reportMonth": REPORT_MONTH,
                "idempotencyKey": "mcp-tax-extra-field-0001",
                "tenantId": str(TENANT_A),
            },
        )

    assert tool.inputSchema["additionalProperties"] is False
    assert tool.outputSchema["additionalProperties"] is False
    recovery_schema = tool.outputSchema["$defs"]["TaxXmlRecoveryJobRead"]
    item_schema = tool.outputSchema["$defs"]["TaxXmlRecoveryItemRead"]
    assert recovery_schema["additionalProperties"] is False
    assert item_schema["additionalProperties"] is False
    assert "documentId" in item_schema["properties"]
    assert "fiscal_document_id" not in item_schema["properties"]
    assert result.isError is True
    assert "Extra inputs are not permitted" in result.content[0].text


async def test_mcp_tax_read_scope_excludes_writes_and_other_tenants(client) -> None:
    arguments = {"year": 2026, "startMonth": 1, "endMonth": 2}
    name = "tax.get_period_summary"
    async with SessionFactory.begin() as db:
        period = TaxPeriod(
            tenant_id=TENANT_A, year=2026, month=1, obligation_type="IVA", status="LISTO_REVISAR",
        )
        db.add(period)
        await db.flush()
        invoice = FiscalDocument(
            tenant_id=TENANT_A, tax_period_id=period.id, direction="RECIBIDO",
            doc_type="FACTURA", issue_date=date(2026, 1, 8), subtotal=Decimal("91.25"),
        )
        db.add(invoice)
        await db.flush()
        db.add(Payable(
            tenant_id=TENANT_A, fiscal_document_id=invoice.id, description="Compra sintética",
            issue_date=invoice.issue_date, due_date=invoice.issue_date, total=Decimal("104.94"),
            tax_classification="DEDUCTIBLE_CONFIRMED",
        ))
    token_a = await token_for(client, "a@iaerp.local", TENANT_A, ["tax:read"])
    token_b = await token_for(client, "b@iaerp.local", TENANT_B, ["tax:read"])
    async with mcp_lifespan():
        async with mcp_session(token_a) as session:
            catalog = (await session.list_tools()).tools
            assert {tool.name for tool in catalog} == {name}
            tool = catalog[0]
            assert tool.annotations.readOnlyHint is True
            assert tool.annotations.openWorldHint is False
            assert tool.inputSchema["additionalProperties"] is False
            assert tool.outputSchema["additionalProperties"] is False
            assert tool.outputSchema["$defs"]["TaxSummaryMonth"]["additionalProperties"] is False
            report_a = await session.call_tool(name, arguments)
            assert not report_a.isError
            assert report_a.structuredContent["months"][0]["ivaPeriodStatus"] == "LISTO_REVISAR"
            assert report_a.structuredContent["months"][0]["filedAmounts"] is None
            expected = {
                "deductiblePurchasesBase": "91.25",
                "nonDeductiblePurchasesBase": "0.00",
                "pendingReviewPurchasesBase": "0.00",
            }
            assert report_a.structuredContent["classifiedPurchasesTotals"] == expected
            assert report_a.structuredContent["months"][0]["classifiedPurchases"] == expected
            for update in (
                {"tenantId": str(TENANT_B)}, {"startMonth": 2, "endMonth": 1},
                {"endMonth": 13}, {"startMonth": 0}, {"year": 1999},
            ):
                assert (await session.call_tool(name, arguments | update)).isError

        async with mcp_session(token_b) as session:
            report_b = await session.call_tool(name, arguments)
            assert not report_b.isError
            assert report_b.structuredContent["classifiedPurchasesTotals"] is None
            assert [month["month"] for month in report_b.structuredContent["months"]] == [1, 2]
            assert all(
                month["ivaPeriodStatus"] is None and month["filedAmounts"] is None
                for month in report_b.structuredContent["months"]
            )

    async with SessionFactory() as db:
        assert await db.scalar(select(func.count()).select_from(TaxPeriod)) == 1


async def test_mcp_tax_summary_rejects_write_only_and_non_fiscal_tokens(client) -> None:
    name = "tax.get_period_summary"
    async with mcp_lifespan():
        for scopes in (["context:read", "invoices:read"], ["tax:write"]):
            token = await token_for(client, "a@iaerp.local", TENANT_A, scopes)
            async with mcp_session(token) as session:
                assert name not in {tool.name for tool in (await session.list_tools()).tools}
                result = await session.call_tool(
                    name, {"year": 2026, "startMonth": 1, "endMonth": 1}
                )
                assert result.isError
                assert "missing scope tax:read" in result.content[0].text
