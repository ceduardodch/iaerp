"""Los cuatro avisos que suma F3 al catalogo.

Cada uno se prueba por lo mismo: que se programe cuando toca, que **deje de
programarse** cuando su condicion ya se cumplio, y que el correo diga la verdad
sobre lo que sabe y lo que no.
"""

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import select

from app.db.session import SessionFactory
from app.integrations.notifications.email_sender import StubEmailSender
from app.models.billing import SalesDocument
from app.models.legal_commercial import PartyBillingSchedule
from app.models.masters import EmissionPoint, Establishment, Party
from app.models.notifications import NotificationEvent, NotificationRule
from app.models.payroll import PayrollEmployee, PayrollEntry, PayrollPeriod
from app.models.tax import FiscalDocument, TaxPeriod
from app.services.notifications import delivery, planner

TENANT_A = uuid.UUID("11111111-1111-4111-8111-111111111111")


async def enable_rule(rule_type: str, *, tenant_id: uuid.UUID = TENANT_A) -> uuid.UUID:
    """Crea las reglas por defecto (si faltan) y enciende la pedida."""
    async with SessionFactory() as session, session.begin():
        await planner.ensure_default_rules(session, tenant_id=tenant_id)
    async with SessionFactory() as session, session.begin():
        rule = await session.scalar(
            select(NotificationRule).where(
                NotificationRule.tenant_id == tenant_id,
                NotificationRule.rule_type == rule_type,
            )
        )
        assert rule is not None
        rule.enabled = True
        return rule.id


async def events_of(rule_type: str) -> list[NotificationEvent]:
    async with SessionFactory() as session:
        return list(
            await session.scalars(
                select(NotificationEvent).where(
                    NotificationEvent.tenant_id == TENANT_A,
                    NotificationEvent.rule_type == rule_type,
                )
            )
        )


async def deliver_first(rule_type: str) -> StubEmailSender:
    """Entrega el primer evento del tipo y devuelve el stub para inspeccionarlo."""
    events = await events_of(rule_type)
    assert events, f"no se programo ningun aviso {rule_type}"
    sender = StubEmailSender()
    async with SessionFactory() as session, session.begin():
        event = await session.get(NotificationEvent, events[0].id)
        assert event is not None
        await delivery.deliver_event(session, event=event, sender=sender)
    return sender


# --------------------------------------------------------------------------
# CLIENTE_FACTURAR
# --------------------------------------------------------------------------


async def create_customer(name: str = "ACME S.A.", number: str = "0999999999001") -> uuid.UUID:
    async with SessionFactory() as session, session.begin():
        party = Party(
            tenant_id=TENANT_A,
            name=name,
            identification_type="RUC",
            identification_number=number,
            roles=["CUSTOMER"],
        )
        session.add(party)
        await session.flush()
        return party.id


async def create_billing_schedule(
    party_id: uuid.UUID,
    *,
    day_of_month: int = 1,
    frequency: str = "MONTHLY",
    anchor_month: int | None = None,
    amount_hint: Decimal | None = None,
) -> uuid.UUID:
    async with SessionFactory() as session, session.begin():
        schedule = PartyBillingSchedule(
            tenant_id=TENANT_A,
            party_id=party_id,
            day_of_month=day_of_month,
            frequency=frequency,
            anchor_month=anchor_month,
            amount_hint=amount_hint,
        )
        session.add(schedule)
        await session.flush()
        return schedule.id


async def create_invoice(party_id: uuid.UUID, *, issue_date: date, status: str) -> None:
    async with SessionFactory() as session, session.begin():
        establishment = Establishment(
            tenant_id=TENANT_A, code="001", name="Matriz", address="Demo"
        )
        session.add(establishment)
        await session.flush()
        emission_point = EmissionPoint(
            tenant_id=TENANT_A, establishment_id=establishment.id, code="001"
        )
        session.add(emission_point)
        await session.flush()
        session.add(
            SalesDocument(
                tenant_id=TENANT_A,
                document_type="INVOICE",
                establishment_id=establishment.id,
                emission_point_id=emission_point.id,
                sequential="000000001",
                party_id=party_id,
                issue_date=issue_date,
                status=status,
                subtotal=Decimal("100.00"),
                tax_total=Decimal("15.00"),
                total=Decimal("115.00"),
                fiscal_policy_version="2026.1",
            )
        )


async def test_billing_reminder_fires_on_the_configured_day() -> None:
    party_id = await create_customer()
    await create_billing_schedule(party_id, day_of_month=1, amount_hint=Decimal("250.00"))
    await enable_rule("CLIENTE_FACTURAR")

    assert await planner.plan_notifications_once(today=date(2026, 9, 1)) == 1
    events = await events_of("CLIENTE_FACTURAR")
    assert len(events) == 1
    assert events[0].payload["party_name"] == "ACME S.A."
    assert events[0].payload["period_label"] == "09/2026"


async def test_billing_reminder_is_silent_once_the_invoice_exists() -> None:
    party_id = await create_customer()
    await create_billing_schedule(party_id, day_of_month=1)
    await create_invoice(party_id, issue_date=date(2026, 9, 1), status="AUTHORIZED")
    await enable_rule("CLIENTE_FACTURAR")

    assert await planner.plan_notifications_once(today=date(2026, 9, 1)) == 0
    assert await events_of("CLIENTE_FACTURAR") == []


async def test_a_draft_invoice_does_not_count_as_issued() -> None:
    """Una factura en borrador no esta emitida: el recordatorio sigue haciendo falta."""
    party_id = await create_customer()
    await create_billing_schedule(party_id, day_of_month=1)
    await create_invoice(party_id, issue_date=date(2026, 9, 1), status="DRAFT")
    await enable_rule("CLIENTE_FACTURAR")

    assert await planner.plan_notifications_once(today=date(2026, 9, 1)) == 1


async def test_billing_reminder_repeats_two_days_later() -> None:
    party_id = await create_customer()
    await create_billing_schedule(party_id, day_of_month=1)
    await enable_rule("CLIENTE_FACTURAR")

    assert await planner.plan_notifications_once(today=date(2026, 9, 1)) == 1
    assert await planner.plan_notifications_once(today=date(2026, 9, 2)) == 0
    assert await planner.plan_notifications_once(today=date(2026, 9, 3)) == 1

    offsets = sorted(event.payload["offset_days"] for event in await events_of("CLIENTE_FACTURAR"))
    assert offsets == [0, 2]


async def test_day_31_still_fires_in_a_short_month() -> None:
    """Quien configura el 31 espera un aviso a fin de mes, tambien en abril."""
    party_id = await create_customer()
    await create_billing_schedule(party_id, day_of_month=31)
    await enable_rule("CLIENTE_FACTURAR")

    assert await planner.plan_notifications_once(today=date(2026, 4, 30)) == 1


async def test_quarterly_schedule_only_fires_on_its_anchor_months() -> None:
    party_id = await create_customer()
    await create_billing_schedule(
        party_id, day_of_month=5, frequency="QUARTERLY", anchor_month=1
    )
    await enable_rule("CLIENTE_FACTURAR")

    # Enero, abril, julio y octubre si; el resto no.
    assert await planner.plan_notifications_once(today=date(2026, 4, 5)) == 1
    assert await planner.plan_notifications_once(today=date(2026, 5, 5)) == 0


async def test_billing_delivery_skips_an_invoice_created_after_planning() -> None:
    party_id = await create_customer()
    await create_billing_schedule(party_id, day_of_month=1)
    await enable_rule("CLIENTE_FACTURAR")
    await planner.plan_notifications_once(today=date(2026, 9, 1))

    await create_invoice(party_id, issue_date=date(2026, 9, 4), status="SIGNED")

    sender = await deliver_first("CLIENTE_FACTURAR")
    assert sender.sent == []
    events = await events_of("CLIENTE_FACTURAR")
    assert events[0].status == "SKIPPED"
    assert events[0].error_message == "El cliente ya tiene factura del periodo"


async def test_billing_email_names_the_customer_and_the_day() -> None:
    party_id = await create_customer()
    await create_billing_schedule(party_id, day_of_month=10, amount_hint=Decimal("1250.5"))
    await enable_rule("CLIENTE_FACTURAR")
    await planner.plan_notifications_once(today=date(2026, 9, 10))

    sender = await deliver_first("CLIENTE_FACTURAR")
    body = sender.sent[0].body_text
    assert "ACME S.A." in sender.sent[0].subject
    assert "dia 10" in body
    assert "$1,250.50" in body
    assert "no emite la factura" in body


# --------------------------------------------------------------------------
# IESS_APORTE
# --------------------------------------------------------------------------


async def create_payroll(*, anio: int = 2026, mes: int = 8, entries: int = 2) -> uuid.UUID:
    async with SessionFactory() as session, session.begin():
        period = PayrollPeriod(tenant_id=TENANT_A, anio=anio, mes=mes, status="APPROVED")
        session.add(period)
        await session.flush()
        for index in range(entries):
            employee = PayrollEmployee(
                tenant_id=TENANT_A,
                identification_number=f"17123456{index:02d}",
                full_name=f"Empleado {index}",
                position="Analista",
                sueldo_mensual=Decimal("1000.00"),
                fecha_ingreso=date(2024, 1, 1),
            )
            session.add(employee)
            await session.flush()
            session.add(
                PayrollEntry(
                    tenant_id=TENANT_A,
                    period_id=period.id,
                    employee_id=employee.id,
                    dias_trabajados=30,
                    imponible=Decimal("1000.00"),
                    decimo_tercero=Decimal("0.00"),
                    decimo_cuarto=Decimal("0.00"),
                    fondos_reserva=Decimal("0.00"),
                    total_ingresos=Decimal("1000.00"),
                    aporte_iess=Decimal("94.50"),
                    total_descuentos=Decimal("94.50"),
                    liquido=Decimal("905.50"),
                    sbu_aplicado=Decimal("482.00"),
                    tasa_iess_aplicada=Decimal("0.094500"),
                    tasa_fondos_aplicada=Decimal("0.000000"),
                )
            )
        return period.id


async def test_iess_reminder_counts_back_from_the_fifteenth() -> None:
    await create_payroll(anio=2026, mes=8)
    await enable_rule("IESS_APORTE")

    # Vencimiento: 15 de septiembre de 2026 (martes, sin corrimiento).
    assert await planner.plan_notifications_once(today=date(2026, 9, 10)) == 1
    assert await planner.plan_notifications_once(today=date(2026, 9, 11)) == 0
    assert await planner.plan_notifications_once(today=date(2026, 9, 13)) == 1
    assert await planner.plan_notifications_once(today=date(2026, 9, 14)) == 1

    events = await events_of("IESS_APORTE")
    assert len(events) == 3
    assert all(event.payload["due_date"] == "2026-09-15" for event in events)


async def test_iess_reminder_needs_a_payroll_with_entries() -> None:
    await enable_rule("IESS_APORTE")
    assert await planner.plan_notifications_once(today=date(2026, 9, 10)) == 0

    await create_payroll(anio=2026, mes=8, entries=0)
    assert await planner.plan_notifications_once(today=date(2026, 9, 10)) == 0


async def test_iess_email_never_passes_the_personal_share_off_as_the_total() -> None:
    """Leer el aporte personal como el total de la planilla lleva a pagar de menos."""
    await create_payroll(anio=2026, mes=8, entries=2)
    await enable_rule("IESS_APORTE")
    await planner.plan_notifications_once(today=date(2026, 9, 10))

    sender = await deliver_first("IESS_APORTE")
    body = sender.sent[0].body_text
    assert "$189.00" in body  # 2 x 94.50
    assert "9,45%" in body
    assert "NO incluye el aporte patronal" in body
    assert "no genera ni paga la planilla" in body


async def test_a_human_acknowledgement_silences_the_remaining_iess_reminders() -> None:
    await create_payroll(anio=2026, mes=8)
    await enable_rule("IESS_APORTE")
    assert await planner.plan_notifications_once(today=date(2026, 9, 10)) == 1

    async with SessionFactory() as session, session.begin():
        event = (await session.scalars(select(NotificationEvent))).first()
        assert event is not None
        event.ack_at = event.created_at
        event.ack_by = "contadora@ejemplo.ec"

    # Los offsets que faltaban ya no se programan.
    assert await planner.plan_notifications_once(today=date(2026, 9, 13)) == 0
    assert await planner.plan_notifications_once(today=date(2026, 9, 14)) == 0


# --------------------------------------------------------------------------
# RESUMEN_MENSUAL
# --------------------------------------------------------------------------


async def create_purchase(*, issue_date: date, total: Decimal, preliminary: bool = False) -> None:
    async with SessionFactory() as session, session.begin():
        session.add(
            FiscalDocument(
                tenant_id=TENANT_A,
                direction="RECIBIDO",
                doc_type="FACTURA",
                access_key=uuid.uuid4().hex[:24] + "0" * 25,
                issue_date=issue_date,
                subtotal=total,
                tax_total=Decimal("0.00"),
                total=total,
                payment_methods=[],
                is_preliminary=preliminary,
            )
        )


async def test_monthly_summary_reports_the_closed_month_on_both_days() -> None:
    party_id = await create_customer()
    await create_invoice(party_id, issue_date=date(2026, 8, 20), status="AUTHORIZED")
    await create_purchase(issue_date=date(2026, 8, 21), total=Decimal("40.00"))
    await enable_rule("RESUMEN_MENSUAL")

    assert await planner.plan_notifications_once(today=date(2026, 9, 3)) == 1
    assert await planner.plan_notifications_once(today=date(2026, 9, 4)) == 0
    assert await planner.plan_notifications_once(today=date(2026, 9, 5)) == 1

    events = await events_of("RESUMEN_MENSUAL")
    assert len(events) == 2
    payload = events[0].payload
    assert payload["period_label"] == "08/2026"
    assert Decimal(str(payload["income_total"])) == Decimal("115.00")
    assert Decimal(str(payload["expense_total"])) == Decimal("40.00")
    assert Decimal(str(payload["result_total"])) == Decimal("75.00")


async def test_monthly_summary_warns_about_preliminary_purchases() -> None:
    await create_purchase(issue_date=date(2026, 8, 10), total=Decimal("30.00"), preliminary=True)
    await enable_rule("RESUMEN_MENSUAL")
    await planner.plan_notifications_once(today=date(2026, 9, 3))

    sender = await deliver_first("RESUMEN_MENSUAL")
    body = sender.sent[0].body_text
    assert "1 comprobante(s) de compra estan preliminares" in body
    assert "no una declaracion" in body


# --------------------------------------------------------------------------
# IVA_PREVIEW_MENSUAL
# --------------------------------------------------------------------------


async def test_iva_preview_only_runs_on_the_last_business_day() -> None:
    async with SessionFactory() as session, session.begin():
        session.add(
            TaxPeriod(
                tenant_id=TENANT_A,
                year=2026,
                month=9,
                obligation_type="IVA",
                status="EVIDENCIA_INCOMPLETA",
            )
        )
    await enable_rule("IVA_PREVIEW_MENSUAL")

    assert await planner.plan_notifications_once(today=date(2026, 9, 29)) == 0
    # 30 de septiembre de 2026 es miercoles: ultimo dia habil del mes.
    assert await planner.plan_notifications_once(today=date(2026, 9, 30)) == 1


async def test_iva_preview_says_the_figures_are_incomplete() -> None:
    """Sin evidencia completa el correo no puede mostrar una cifra que parezca final."""
    async with SessionFactory() as session, session.begin():
        session.add(
            TaxPeriod(
                tenant_id=TENANT_A,
                year=2026,
                month=9,
                obligation_type="IVA",
                status="PENDIENTE_DESCARGA",
            )
        )
    await enable_rule("IVA_PREVIEW_MENSUAL")
    await planner.plan_notifications_once(today=date(2026, 9, 30))

    events = await events_of("IVA_PREVIEW_MENSUAL")
    assert events[0].payload["is_preliminary"] is True

    sender = await deliver_first("IVA_PREVIEW_MENSUAL")
    body = sender.sent[0].body_text
    assert "INCOMPLETAS" in body
    assert "no un valor declarable" in body


async def test_iva_preview_needs_an_open_period() -> None:
    await enable_rule("IVA_PREVIEW_MENSUAL")
    assert await planner.plan_notifications_once(today=date(2026, 9, 30)) == 0
