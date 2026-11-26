from datetime import date
from decimal import Decimal
from uuid import UUID

from app.db.session import SessionFactory
from app.models.masters import EmissionPoint, Establishment, TaxCategory
from tests.test_billing_api import TENANT_A, TENANT_B, token_for
from tests.test_mcp_invoices import (
    _enable_automation_writes,
    _setup_masters_and_invoice_scoped_token,
    mcp_lifespan,
    mcp_session,
)


async def test_invoice_options_resolve_product_tax_and_point_for_new_draft(client):
    masters, token = await _setup_masters_and_invoice_scoped_token(
        client,
        tenant_id=TENANT_A,
        email="a@iaerp.local",
        key_prefix="options-draft",
        extra_scopes=["invoices:write", "parties:read", "products:read", "automation:write"],
    )
    _, other_token = await _setup_masters_and_invoice_scoped_token(
        client,
        tenant_id=TENANT_B,
        email="b@iaerp.local",
        key_prefix="options-other",
        extra_scopes=["invoices:write"],
    )
    await _enable_automation_writes(client, token, "options-enable-0001")
    issue_date = "2026-07-04"
    async with mcp_lifespan():
        async with mcp_session(token) as session:
            catalog = await session.call_tool("invoices.draft_options", {"issueDate": issue_date})
            assert not catalog.isError
            options = catalog.structuredContent
            assert len(options["emissionPoints"]) == len(options["taxCategories"]) == 1
            point = options["emissionPoints"][0]
            assert point == {
                "id": masters["emission_point_id"],
                "code": "001",
                "establishmentId": masters["establishment_id"],
                "establishmentCode": "001",
                "establishmentName": "Matriz",
            }
            product_result = await session.call_tool("products.search", {"query": "consultoria"})
            product = product_result.structuredContent["result"][0]
            tax = options["taxCategories"][0]
            assert tax["id"] == product["taxCategoryId"]
            customer_result = await session.call_tool(
                "parties.search", {"query": "Cliente Facturable", "role": "CUSTOMER"}
            )
            customer = customer_result.structuredContent["result"][0]
            draft = await session.call_tool(
                "invoices.create_draft",
                {
                    "idempotencyKey": "options-create-0001",
                    "invoice": {
                        "establishmentId": point["establishmentId"],
                        "emissionPointId": point["id"],
                        "customerId": customer["id"],
                        "issueDate": issue_date,
                        "lines": [
                            {
                                "productId": product["id"],
                                "description": product["name"],
                                "unitPrice": product["unitPrice"],
                                "quantity": "2",
                                "taxCode": tax["sriCode"],
                            }
                        ],
                    },
                },
            )
            assert not draft.isError, draft.content
            assert Decimal(draft.structuredContent["total"]) == Decimal("115.00")
        async with mcp_session(other_token) as session:
            other = await session.call_tool("invoices.draft_options", {"issueDate": issue_date})
            assert not other.isError
            assert len(other.structuredContent["emissionPoints"]) == 1
            assert len(other.structuredContent["taxCategories"]) == 1
            assert other.structuredContent["emissionPoints"][0]["id"] != point["id"]
            assert other.structuredContent["taxCategories"][0]["id"] != tax["id"]


async def test_invoice_options_hide_inactive_points_and_inapplicable_rates(client):
    masters, token = await _setup_masters_and_invoice_scoped_token(
        client,
        tenant_id=TENANT_A,
        email="a@iaerp.local",
        key_prefix="options-dates",
        extra_scopes=["invoices:write"],
    )
    async with SessionFactory() as db, db.begin():
        establishment = await db.get(Establishment, UUID(masters["establishment_id"]))
        establishment.active = False
        other = Establishment(tenant_id=TENANT_A, code="008", name="Agencia", address="Calle 7")
        db.add(other)
        await db.flush()
        db.add(
            EmissionPoint(tenant_id=TENANT_A, establishment_id=other.id, code="003", active=False)
        )
        db.add_all(
            [
                TaxCategory(
                    tenant_id=TENANT_A,
                    sri_code=masters["tax_code"],
                    name="Vigencia posterior",
                    rate=Decimal("6"),
                    valid_from=date(2026, 8, 1),
                ),
                TaxCategory(
                    tenant_id=TENANT_A,
                    sri_code="X",
                    name="Vigencia de un día",
                    rate=Decimal("0"),
                    valid_from=date(2026, 7, 4),
                    valid_to=date(2026, 7, 4),
                ),
            ]
        )
    async with mcp_lifespan(), mcp_session(token) as session:
        for issue_date, expected in [
            ("2026-07-03", []),
            ("2026-07-04", ["X"]),
            ("2026-07-05", []),
            ("2026-08-01", [masters["tax_code"]]),
        ]:
            result = await session.call_tool("invoices.draft_options", {"issueDate": issue_date})
            assert not result.isError
            assert result.structuredContent["emissionPoints"] == []
            assert [tax["sriCode"] for tax in result.structuredContent["taxCategories"]] == expected


async def test_invoice_options_require_invoice_writer_scope(client):
    token = await token_for(client, "a@iaerp.local", TENANT_A, ["context:read"])
    async with mcp_lifespan(), mcp_session(token) as session:
        assert "invoices.draft_options" not in {
            tool.name for tool in (await session.list_tools()).tools
        }
        result = await session.call_tool("invoices.draft_options", {"issueDate": "2026-07-04"})
        assert result.isError
