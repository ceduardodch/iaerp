"""Desglose del cobro: cuánto entró en dinero y cuánto quedó retenido.

Una retención baja el saldo igual que un cobro, pero NO es caja: es valor que
el cliente retuvo y que se recupera ante el SRI. Estas pruebas fijan esa
separación y que el desglose respete la misma regla de movimientos activos que
el saldo (``compute_installment_balance``), para que ambos números nunca se
contradigan.
"""

import uuid
from datetime import date
from decimal import Decimal

from app.core.auth import AuthContext
from app.db.session import SessionFactory
from app.models.receivables import Movement
from app.services.receivables import (
    compute_collections_breakdown,
    compute_collections_history,
)
from tests.test_billing_api import TENANT_A, auth, token_for
from tests.test_receivables_service import (
    _create_authorized_invoice_stub,
    _create_party,
    _create_receivable,
)


def _context(*, tenant_id: uuid.UUID = TENANT_A) -> AuthContext:
    return AuthContext(
        actor_id="tester@iaerp.local",
        actor_type="USER",
        tenant_id=tenant_id,
        roles=frozenset(),
        scopes=frozenset({"receivables:read"}),
        token_id="test-token",
    )


async def _seed_movements(
    *,
    suffix: str,
    entries: list[tuple[str, Decimal, date | None]],
) -> list[Movement]:
    """Crea un receivable y le aplica los movimientos indicados.

    ``entries`` es una lista de ``(movement_type, amount, effective_date)``.
    """
    async with SessionFactory() as session, session.begin():
        party = await _create_party(session, tenant_id=TENANT_A, suffix=suffix)
        invoice = await _create_authorized_invoice_stub(
            session, tenant_id=TENANT_A, party_id=party.id, total=Decimal("1000.00")
        )
        receivable, installments = await _create_receivable(
            session,
            tenant_id=TENANT_A,
            party_id=party.id,
            sales_document_id=invoice.id,
            original_amount=Decimal("1000.00"),
            installment_amounts=[Decimal("1000.00")],
            due_date=date(2026, 8, 1),
        )
        created: list[Movement] = []
        for index, (movement_type, amount, effective_date) in enumerate(entries, start=1):
            movement = Movement(
                tenant_id=TENANT_A,
                receivable_id=receivable.id,
                installment_id=installments[0].id,
                movement_type=movement_type,
                amount=amount,
                effective_date=effective_date,
                support_reference=f"{movement_type}-{suffix}-{index}",
                actor_id="tester@iaerp.local",
            )
            session.add(movement)
            created.append(movement)
        await session.flush()
        return created


async def test_cash_and_retention_are_reported_separately() -> None:
    await _seed_movements(
        suffix="col1",
        entries=[
            ("PAYMENT", Decimal("317.85"), date(2026, 7, 10)),
            ("RETENTION", Decimal("32.80"), date(2026, 7, 10)),
            ("RETENTION", Decimal("8.59"), date(2026, 7, 10)),
        ],
    )

    async with SessionFactory() as session:
        breakdown = await compute_collections_breakdown(session, _context())

    assert breakdown.cash_amount == Decimal("317.85")
    assert breakdown.cash_count == 1
    assert breakdown.retention_amount == Decimal("41.39")
    assert breakdown.retention_count == 2
    # Lo que salda la factura es la suma de ambos, no solo el dinero.
    assert breakdown.settled_amount == Decimal("359.24")


async def test_credit_notes_and_discounts_are_not_counted_as_collection() -> None:
    await _seed_movements(
        suffix="col2",
        entries=[
            ("PAYMENT", Decimal("100.00"), date(2026, 7, 10)),
            ("CREDIT_NOTE", Decimal("50.00"), date(2026, 7, 10)),
            ("DISCOUNT", Decimal("25.00"), date(2026, 7, 10)),
        ],
    )

    async with SessionFactory() as session:
        breakdown = await compute_collections_breakdown(session, _context())

    assert breakdown.credit_amount == Decimal("75.00")
    assert breakdown.credit_count == 2
    # Bajan la deuda pero no entra dinero: fuera de efectivo y de retenciones.
    assert breakdown.cash_amount == Decimal("100.00")
    assert breakdown.retention_amount == Decimal("0.00")
    assert breakdown.settled_amount == Decimal("100.00")


async def test_reversed_payment_is_excluded_from_the_breakdown() -> None:
    movements = await _seed_movements(
        suffix="col3",
        entries=[
            ("PAYMENT", Decimal("200.00"), date(2026, 7, 10)),
            ("PAYMENT", Decimal("300.00"), date(2026, 7, 11)),
        ],
    )
    reversed_movement = movements[1]

    async with SessionFactory() as session, session.begin():
        session.add(
            Movement(
                tenant_id=TENANT_A,
                receivable_id=reversed_movement.receivable_id,
                installment_id=reversed_movement.installment_id,
                movement_type="REVERSAL",
                amount=Decimal("300.00"),
                effective_date=date(2026, 7, 12),
                support_reference="Cobro duplicado",
                reversed_movement_id=reversed_movement.id,
                actor_id="tester@iaerp.local",
            )
        )

    async with SessionFactory() as session:
        breakdown = await compute_collections_breakdown(session, _context())

    # Ni el cobro revertido ni la fila REVERSAL cuentan: queda solo el de 200.
    assert breakdown.cash_amount == Decimal("200.00")
    assert breakdown.cash_count == 1


async def test_date_range_filters_by_effective_date() -> None:
    await _seed_movements(
        suffix="col4",
        entries=[
            ("PAYMENT", Decimal("111.00"), date(2026, 6, 30)),
            ("PAYMENT", Decimal("222.00"), date(2026, 7, 15)),
            ("RETENTION", Decimal("33.00"), date(2026, 7, 20)),
        ],
    )

    async with SessionFactory() as session:
        breakdown = await compute_collections_breakdown(
            session, _context(), from_date=date(2026, 7, 1), to_date=date(2026, 7, 31)
        )

    # El cobro de junio queda fuera del rango de julio.
    assert breakdown.cash_amount == Decimal("222.00")
    assert breakdown.retention_amount == Decimal("33.00")


async def test_retention_share_is_zero_without_collections() -> None:
    async with SessionFactory() as session:
        breakdown = await compute_collections_breakdown(
            session, _context(), from_date=date(2030, 1, 1), to_date=date(2030, 1, 31)
        )

    assert breakdown.settled_amount == Decimal("0.00")
    # Sin cobros no se divide por cero ni se inventa un porcentaje.
    assert breakdown.retention_share == Decimal("0.00")


async def test_retention_share_reports_the_weight_of_retentions() -> None:
    await _seed_movements(
        suffix="col5",
        entries=[
            ("PAYMENT", Decimal("750.00"), date(2026, 9, 5)),
            ("RETENTION", Decimal("250.00"), date(2026, 9, 5)),
        ],
    )

    async with SessionFactory() as session:
        breakdown = await compute_collections_breakdown(
            session, _context(), from_date=date(2026, 9, 1), to_date=date(2026, 9, 30)
        )

    assert breakdown.settled_amount == Decimal("1000.00")
    assert breakdown.retention_share == Decimal("25.00")


async def test_endpoint_returns_the_breakdown_in_camel_case(client) -> None:
    await _seed_movements(
        suffix="col6",
        entries=[
            ("PAYMENT", Decimal("400.00"), date(2026, 10, 3)),
            ("RETENTION", Decimal("100.00"), date(2026, 10, 3)),
        ],
    )
    token = await token_for(client, "a@iaerp.local", TENANT_A, ["receivables:read"])

    response = await client.get(
        "/api/v1/receivables/collections?from=2026-10-01&to=2026-10-31",
        headers=auth(token),
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["cashAmount"] == "400.00"
    assert body["retentionAmount"] == "100.00"
    assert body["settledAmount"] == "500.00"
    assert body["retentionShare"] == "20.00"


async def test_endpoint_requires_receivables_read_scope(client) -> None:
    token = await token_for(client, "a@iaerp.local", TENANT_A, ["parties:read"])
    response = await client.get("/api/v1/receivables/collections", headers=auth(token))
    assert response.status_code == 403


# --- Serie mensual: la tendencia debe cuadrar con el total ------------------


async def test_history_returns_every_month_even_without_collections() -> None:
    async with SessionFactory() as session:
        history = await compute_collections_history(
            session, _context(), months=6, as_of=date(2026, 7, 15)
        )

    # Seis meses completos, del mas viejo al mas nuevo, sin huecos: una serie
    # con meses faltantes dibuja una tendencia falsa.
    assert [(item.year, item.month) for item in history.months] == [
        (2026, 2),
        (2026, 3),
        (2026, 4),
        (2026, 5),
        (2026, 6),
        (2026, 7),
    ]
    assert all(item.settled_amount == Decimal("0.00") for item in history.months)


async def test_history_places_each_movement_in_its_effective_month() -> None:
    await _seed_movements(
        suffix="hist1",
        entries=[
            ("PAYMENT", Decimal("100.00"), date(2026, 5, 20)),
            ("PAYMENT", Decimal("250.00"), date(2026, 7, 3)),
            ("RETENTION", Decimal("50.00"), date(2026, 7, 28)),
        ],
    )

    async with SessionFactory() as session:
        history = await compute_collections_history(
            session, _context(), months=3, as_of=date(2026, 7, 15)
        )

    by_month = {(item.year, item.month): item for item in history.months}
    assert by_month[(2026, 5)].cash_amount == Decimal("100.00")
    assert by_month[(2026, 6)].settled_amount == Decimal("0.00")
    # Julio incluye el ultimo dia del mes aunque ``as_of`` sea el 15.
    assert by_month[(2026, 7)].cash_amount == Decimal("250.00")
    assert by_month[(2026, 7)].retention_amount == Decimal("50.00")
    assert by_month[(2026, 7)].settled_amount == Decimal("300.00")


async def test_history_excludes_reversed_movements_like_the_total() -> None:
    movements = await _seed_movements(
        suffix="hist2",
        entries=[
            ("PAYMENT", Decimal("400.00"), date(2026, 7, 10)),
            ("PAYMENT", Decimal("600.00"), date(2026, 7, 11)),
        ],
    )
    reversed_movement = movements[1]

    async with SessionFactory() as session, session.begin():
        session.add(
            Movement(
                tenant_id=TENANT_A,
                receivable_id=reversed_movement.receivable_id,
                installment_id=reversed_movement.installment_id,
                movement_type="REVERSAL",
                amount=Decimal("600.00"),
                effective_date=date(2026, 7, 12),
                support_reference="Cobro duplicado",
                reversed_movement_id=reversed_movement.id,
                actor_id="tester@iaerp.local",
            )
        )

    async with SessionFactory() as session:
        history = await compute_collections_history(
            session, _context(), months=1, as_of=date(2026, 7, 31)
        )
        breakdown = await compute_collections_breakdown(
            session, _context(), from_date=date(2026, 7, 1), to_date=date(2026, 7, 31)
        )

    # La serie y el total salen de la misma regla: no pueden contradecirse.
    assert history.months[0].cash_amount == Decimal("400.00")
    assert history.months[0].cash_amount == breakdown.cash_amount


async def test_history_endpoint_is_scoped_and_camel_case(client) -> None:
    await _seed_movements(
        suffix="hist3", entries=[("PAYMENT", Decimal("77.00"), date(2026, 7, 9))]
    )
    token = await token_for(client, "a@iaerp.local", TENANT_A, ["receivables:read"])

    response = await client.get(
        "/api/v1/receivables/collections/monthly?months=2&asOf=2026-07-31",
        headers=auth(token),
    )

    assert response.status_code == 200, response.text
    months = response.json()["months"]
    assert len(months) == 2
    assert months[-1]["cashAmount"] == "77.00"
    assert months[-1]["settledAmount"] == "77.00"

    denied = await client.get(
        "/api/v1/receivables/collections/monthly",
        headers=auth(await token_for(client, "a@iaerp.local", TENANT_A, ["parties:read"])),
    )
    assert denied.status_code == 403
