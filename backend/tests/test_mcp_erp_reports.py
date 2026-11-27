"""El catálogo de informes y su transporte MCP respetan permisos y empresa."""

from decimal import Decimal

from sqlalchemy import event, select

from app.db.session import SessionFactory, engine
from app.models.masters import Product, TaxCategory
from app.schemas.erp_reports import ReportName
from tests.conftest import TENANT_A, TENANT_B
from tests.test_billing_api import token_for
from tests.test_mcp_receivables import mcp_lifespan, mcp_session

REPORT_TOOL = "erp.read_report"


async def test_reports_require_a_dedicated_scope_for_discovery_and_calls(client):
    token = await token_for(client, "a@iaerp.local", TENANT_A, ["tax:read", "products:read"])
    async with mcp_lifespan(), mcp_session(token) as session:
        names = {tool.name for tool in (await session.list_tools()).tools}
        assert "tax.get_period_summary" in names
        assert REPORT_TOOL not in names
        denied = await session.call_tool(REPORT_TOOL, {"report": "products"})
        assert denied.isError
        assert "missing scope reports:read" in denied.content[0].text


async def test_read_report_has_a_closed_catalog_and_is_tenant_scoped(client):
    async with SessionFactory.begin() as db:
        for tenant_id, name in ((TENANT_A, "Servicio A"), (TENANT_B, "Servicio B")):
            category_id = await db.scalar(
                select(TaxCategory.id).where(TaxCategory.tenant_id == tenant_id)
            )
            db.add(
                Product(
                    tenant_id=tenant_id,
                    name=name,
                    code="SVC",
                    unit_price=Decimal("12.34"),
                    tax_category_id=category_id,
                )
            )
    token_a = await token_for(client, "a@iaerp.local", TENANT_A, ["reports:read"])
    token_b = await token_for(client, "b@iaerp.local", TENANT_B, ["reports:read"])
    business_writes = []

    def observe_writes(connection, cursor, statement, parameters, context, executemany):
        sql = statement.lstrip().lower()
        if sql.startswith(("insert ", "update ", "delete ", "merge ", "call ")):
            if not sql.startswith(
                (
                    "insert into automation_rate_windows ",
                    "update automation_rate_windows ",
                )
            ):
                business_writes.append(sql.split()[0])

    event.listen(engine.sync_engine, "before_cursor_execute", observe_writes)
    try:
        async with mcp_lifespan():
            async with mcp_session(token_a) as session:
                catalog = (await session.list_tools()).tools
                assert {tool.name for tool in catalog} == {REPORT_TOOL}
                tool = catalog[0]
                assert tool.annotations.readOnlyHint is True
                assert tool.annotations.openWorldHint is False
                assert tool.inputSchema["additionalProperties"] is False
                assert tool.outputSchema["additionalProperties"] is False
                for data in (
                    {"report": "products", "tenantId": str(TENANT_B)},
                    {"report": "sql"},
                    {"report": "catalog", "offset": -1},
                    {"report": "products", "limit": 101},
                    {"report": "sales", "startDate": "2026-07-15", "endDate": "2026-06-30"},
                ):
                    assert (await session.call_tool(REPORT_TOOL, data)).isError
                inventory = await session.call_tool(REPORT_TOOL, {"report": "catalog"})
                assert not inventory.isError
                inventory_columns = inventory.structuredContent["columns"]
                descriptors = [
                    dict(zip(inventory_columns, row, strict=True))
                    for row in inventory.structuredContent["rows"]
                ]
                by_name = {row["report"]: row for row in descriptors}
                assert {name.value for name in ReportName} <= by_name.keys()
                assert "unitPrice" in by_name["products"]["columns"]
                assert "startDate" not in by_name["products"]["filters"]
                assert "startDate" in by_name["sales"]["filters"]
                assert all(row["description"] and row["columns"] for row in descriptors)
                result_a = await session.call_tool(REPORT_TOOL, {"report": "products", "limit": 1})
                assert not result_a.isError
                assert any("Servicio A" in row for row in result_a.structuredContent["rows"])
                assert all("Servicio B" not in row for row in result_a.structuredContent["rows"])
                next_page = await session.call_tool(
                    REPORT_TOOL, {"report": "products", "limit": 1, "offset": 1}
                )
                assert not next_page.isError
                assert next_page.structuredContent["rows"] == []
            async with mcp_session(token_b) as session:
                result_b = await session.call_tool(REPORT_TOOL, {"report": "products"})
                assert not result_b.isError
                assert any("Servicio B" in row for row in result_b.structuredContent["rows"])
                assert all("Servicio A" not in row for row in result_b.structuredContent["rows"])
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", observe_writes)
    assert business_writes == []
