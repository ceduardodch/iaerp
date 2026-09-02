"""Fundacion del modulo de avisos internos (F1 del plan de avisos).

La prueba que sostiene todo el modulo es la primera: el planificador corre en
bucle cada minuto, asi que si no deduplica manda el mismo aviso 1.440 veces al
dia. El resto cubre las condiciones de "no avisar": periodo ya declarado, regla
apagada, sin destinatarios, y el aislamiento entre tenants.
"""

import uuid
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import select

from app.db.session import SessionFactory
from app.integrations.notifications.email_sender import StubEmailSender
from app.models.notifications import (
    NotificationDelivery,
    NotificationEvent,
    NotificationRule,
    NotificationTemplate,
)
from app.models.platform import OutboxEvent
from app.models.tax import TaxPeriod, TaxTask
from app.services.notifications import delivery, planner
from app.workers import notifications as notifications_worker
from app.workers.notifications import (
    dispatch_due_notifications_once,
    handle_notification_due,
)
from app.workers.outbox import OutboxMessage

TENANT_A = uuid.UUID("11111111-1111-4111-8111-111111111111")
TENANT_B = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")

DUE_DATE = date(2026, 9, 28)
# La regla trae offsets "-7,-3,-1"; este es el dia del primer aviso.
FIRST_REMINDER_DAY = date(2026, 9, 21)


async def create_period(
    *,
    tenant_id: uuid.UUID = TENANT_A,
    year: int = 2026,
    month: int = 8,
    status: str = "EVIDENCIA_INCOMPLETA",
    due_date: date | None = DUE_DATE,
) -> uuid.UUID:
    async with SessionFactory() as session, session.begin():
        period = TaxPeriod(
            tenant_id=tenant_id,
            year=year,
            month=month,
            obligation_type="IVA",
            status=status,
            due_date=due_date,
        )
        session.add(period)
        await session.flush()
        return period.id


async def enable_rule(
    *,
    tenant_id: uuid.UUID = TENANT_A,
    rule_type: str = "IVA_DECLARACION",
) -> uuid.UUID:
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


async def list_events(tenant_id: uuid.UUID = TENANT_A) -> list[NotificationEvent]:
    async with SessionFactory() as session:
        return list(
            await session.scalars(
                select(NotificationEvent).where(NotificationEvent.tenant_id == tenant_id)
            )
        )


async def test_planner_run_twice_the_same_day_creates_one_event() -> None:
    """Criterio de salida de F1: el bucle no puede duplicar un aviso."""
    await create_period()
    await planner.plan_notifications_once(today=FIRST_REMINDER_DAY)
    await enable_rule()

    assert await planner.plan_notifications_once(today=FIRST_REMINDER_DAY) == 1
    assert await planner.plan_notifications_once(today=FIRST_REMINDER_DAY) == 0
    assert await planner.plan_notifications_once(today=FIRST_REMINDER_DAY) == 0

    events = await list_events()
    assert len(events) == 1
    assert events[0].rule_type == "IVA_DECLARACION"
    assert events[0].payload["offset_days"] == -7


async def test_default_rules_are_created_disabled_and_send_nothing() -> None:
    """Un modulo que empieza mandando correos solo se gana un filtro de spam."""
    await create_period()

    assert await planner.plan_notifications_once(today=FIRST_REMINDER_DAY) == 0

    async with SessionFactory() as session:
        rules = list(
            await session.scalars(
                select(NotificationRule).where(NotificationRule.tenant_id == TENANT_A)
            )
        )
    assert rules
    assert all(rule.enabled is False for rule in rules)
    assert await list_events() == []


async def test_default_rules_are_not_duplicated() -> None:
    async with SessionFactory() as session, session.begin():
        first = await planner.ensure_default_rules(session, tenant_id=TENANT_A)
    async with SessionFactory() as session, session.begin():
        second = await planner.ensure_default_rules(session, tenant_id=TENANT_A)
    assert first >= 1
    assert second == 0


async def test_only_the_offset_matching_today_is_planned() -> None:
    await create_period()
    await planner.plan_notifications_once(today=FIRST_REMINDER_DAY)
    await enable_rule()

    # Un dia sin offset configurado no programa nada...
    assert await planner.plan_notifications_once(today=date(2026, 9, 22)) == 0
    # ...y cada offset configurado programa su propio aviso.
    assert await planner.plan_notifications_once(today=date(2026, 9, 25)) == 1
    assert await planner.plan_notifications_once(today=date(2026, 9, 27)) == 1

    offsets = sorted(event.payload["offset_days"] for event in await list_events())
    assert offsets == [-3, -1]


async def test_declared_period_is_never_announced() -> None:
    await create_period(status="DECLARADO")
    await planner.plan_notifications_once(today=FIRST_REMINDER_DAY)
    await enable_rule()

    assert await planner.plan_notifications_once(today=FIRST_REMINDER_DAY) == 0
    assert await list_events() == []


async def test_period_without_deadline_is_not_announced() -> None:
    """Sin fecha limite no hay nada que anunciar; inventarla seria peor."""
    await create_period(due_date=None)
    await planner.plan_notifications_once(today=FIRST_REMINDER_DAY)
    await enable_rule()

    assert await planner.plan_notifications_once(today=FIRST_REMINDER_DAY) == 0


async def test_each_tenant_only_sees_its_own_periods() -> None:
    await create_period(tenant_id=TENANT_A)
    await planner.plan_notifications_once(today=FIRST_REMINDER_DAY)
    await enable_rule(tenant_id=TENANT_A)
    await enable_rule(tenant_id=TENANT_B)

    assert await planner.plan_notifications_once(today=FIRST_REMINDER_DAY) == 1
    assert len(await list_events(TENANT_A)) == 1
    assert await list_events(TENANT_B) == []


async def _planned_event() -> NotificationEvent:
    await create_period()
    await planner.plan_notifications_once(today=FIRST_REMINDER_DAY)
    await enable_rule()
    await planner.plan_notifications_once(today=FIRST_REMINDER_DAY)
    events = await list_events()
    assert len(events) == 1
    return events[0]


async def test_delivery_reaches_tenant_members_and_records_one_row_each() -> None:
    planned = await _planned_event()
    sender = StubEmailSender()

    async with SessionFactory() as session, session.begin():
        event = await session.get(NotificationEvent, planned.id)
        assert event is not None
        status = await delivery.deliver_event(session, event=event, sender=sender)

    assert status == "STUBBED"
    assert [message.recipient for message in sender.sent] == ["a@iaerp.local"]

    async with SessionFactory() as session:
        deliveries = list(
            await session.scalars(
                select(NotificationDelivery).where(
                    NotificationDelivery.event_id == planned.id
                )
            )
        )
    assert len(deliveries) == 1
    assert deliveries[0].recipient == "a@iaerp.local"
    assert deliveries[0].status == "STUBBED"
    assert deliveries[0].provider == "STUB"


async def test_stub_delivery_is_never_reported_as_sent() -> None:
    """Una bitacora de pruebas no puede ser indistinguible de la de produccion."""
    planned = await _planned_event()

    async with SessionFactory() as session, session.begin():
        event = await session.get(NotificationEvent, planned.id)
        assert event is not None
        status = await delivery.deliver_event(
            session, event=event, sender=StubEmailSender()
        )

    assert status == "STUBBED"
    assert status != "SENT"


async def test_delivery_skips_a_period_declared_after_planning() -> None:
    """Avisar de algo ya hecho es lo que ensena a la gente a ignorar los avisos."""
    planned = await _planned_event()
    period_id = uuid.UUID(str(planned.payload["period_id"]))

    async with SessionFactory() as session, session.begin():
        period = await session.get(TaxPeriod, period_id)
        assert period is not None
        period.status = "DECLARADO"

    sender = StubEmailSender()
    async with SessionFactory() as session, session.begin():
        event = await session.get(NotificationEvent, planned.id)
        assert event is not None
        status = await delivery.deliver_event(session, event=event, sender=sender)

    assert status == "SKIPPED"
    assert sender.sent == []


async def test_delivery_without_recipients_is_skipped_with_a_reason() -> None:
    planned = await _planned_event()

    async with SessionFactory() as session, session.begin():
        rule = await session.get(NotificationRule, planned.rule_id)
        assert rule is not None
        rule.audience_kind = "EXPLICIT_EMAILS"
        rule.audience_emails = []

    async with SessionFactory() as session, session.begin():
        event = await session.get(NotificationEvent, planned.id)
        assert event is not None
        status = await delivery.deliver_event(
            session, event=event, sender=StubEmailSender()
        )
        assert status == "SKIPPED"
        assert event.error_message == "La regla no tiene destinatarios"


async def test_delivery_uses_explicit_emails_when_configured() -> None:
    planned = await _planned_event()

    async with SessionFactory() as session, session.begin():
        rule = await session.get(NotificationRule, planned.rule_id)
        assert rule is not None
        rule.audience_kind = "EXPLICIT_EMAILS"
        rule.audience_emails = ["contador@ejemplo.ec", "gerencia@ejemplo.ec"]

    sender = StubEmailSender()
    async with SessionFactory() as session, session.begin():
        event = await session.get(NotificationEvent, planned.id)
        assert event is not None
        await delivery.deliver_event(session, event=event, sender=sender)

    assert [message.recipient for message in sender.sent] == [
        "contador@ejemplo.ec",
        "gerencia@ejemplo.ec",
    ]


async def test_email_warns_that_holidays_are_not_verified() -> None:
    """Regla de contenido: una fecha sin verificar se anuncia como tal."""
    planned = await _planned_event()
    assert planned.payload["holidays_checked"] is False

    sender = StubEmailSender()
    async with SessionFactory() as session, session.begin():
        event = await session.get(NotificationEvent, planned.id)
        assert event is not None
        await delivery.deliver_event(session, event=event, sender=sender)

    body = sender.sent[0].body_text
    assert "feriado" in body
    assert "28/09/2026" in body
    assert "faltan 7 dias" in body
    assert "no declara ni paga" in body


async def test_open_tax_tasks_are_listed_in_the_message() -> None:
    period_id = await create_period()
    async with SessionFactory() as session, session.begin():
        session.add(
            TaxTask(
                tenant_id=TENANT_A,
                tax_period_id=period_id,
                task_type="COMPLETAR_EVIDENCIA",
                title="Completar evidencia tributaria 08/2026",
                status="PENDIENTE",
                requires_approval=True,
            )
        )
    await planner.plan_notifications_once(today=FIRST_REMINDER_DAY)
    await enable_rule()
    await planner.plan_notifications_once(today=FIRST_REMINDER_DAY)

    events = await list_events()
    sender = StubEmailSender()
    async with SessionFactory() as session, session.begin():
        event = await session.get(NotificationEvent, events[0].id)
        assert event is not None
        await delivery.deliver_event(session, event=event, sender=sender)

    assert "Completar evidencia tributaria 08/2026" in sender.sent[0].body_text


async def test_tenant_template_overrides_the_catalog_default() -> None:
    planned = await _planned_event()
    async with SessionFactory() as session, session.begin():
        session.add(
            NotificationTemplate(
                tenant_id=TENANT_A,
                rule_type="IVA_DECLARACION",
                subject="Ojo: IVA {{periodo}}",
                body="Vence {{fecha_limite}} en {{empresa}}.",
            )
        )

    sender = StubEmailSender()
    async with SessionFactory() as session, session.begin():
        event = await session.get(NotificationEvent, planned.id)
        assert event is not None
        await delivery.deliver_event(session, event=event, sender=sender)

    assert sender.sent[0].subject == "Ojo: IVA 08/2026"
    assert sender.sent[0].body_text == "Vence 28/09/2026 en Tenant A."


async def test_dispatch_claims_only_due_events_and_emits_one_outbox_event() -> None:
    planned = await _planned_event()

    async with SessionFactory() as session, session.begin():
        event = await session.get(NotificationEvent, planned.id)
        assert event is not None
        event.scheduled_at = datetime(2099, 1, 1, tzinfo=UTC)

    assert await dispatch_due_notifications_once() == 0

    async with SessionFactory() as session, session.begin():
        event = await session.get(NotificationEvent, planned.id)
        assert event is not None
        event.scheduled_at = datetime(2020, 1, 1, tzinfo=UTC)

    assert await dispatch_due_notifications_once() == 1
    # Ya reclamado: la segunda vuelta del bucle no lo vuelve a encolar.
    assert await dispatch_due_notifications_once() == 0

    async with SessionFactory() as session:
        outbox = list(
            await session.scalars(
                select(OutboxEvent).where(OutboxEvent.event_type == "notification.due")
            )
        )
        event = await session.get(NotificationEvent, planned.id)
    assert len(outbox) == 1
    assert event is not None
    assert event.status == "PROCESSING"
    assert event.attempts == 1


def _message_for(event_id: uuid.UUID) -> OutboxMessage:
    return OutboxMessage(
        event_id=uuid.uuid4(),
        tenant_id=TENANT_A,
        event_type="notification.due",
        aggregate_type="notification_event",
        aggregate_id=str(event_id),
        payload={},
        correlation_id="test",
        attempts=1,
    )


@pytest.fixture
def captured_sender(monkeypatch: pytest.MonkeyPatch) -> StubEmailSender:
    """Sustituye el proveedor que arma el handler para poder mirar que envio."""
    sender = StubEmailSender()
    monkeypatch.setattr(notifications_worker, "get_email_sender", lambda: sender)
    return sender


async def test_handler_delivers_a_pending_event(captured_sender: StubEmailSender) -> None:
    planned = await _planned_event()

    async with SessionFactory() as session, session.begin():
        await handle_notification_due(session, _message_for(planned.id))

    assert [message.recipient for message in captured_sender.sent] == ["a@iaerp.local"]
    async with SessionFactory() as session:
        event = await session.get(NotificationEvent, planned.id)
    assert event is not None
    assert event.status == "STUBBED"


@pytest.mark.parametrize("resolved_status", ["SENT", "STUBBED", "SKIPPED", "CANCELLED"])
async def test_handler_never_resends_a_resolved_event(
    resolved_status: str,
    captured_sender: StubEmailSender,
) -> None:
    """La entrega es lo unico que no se puede deshacer; el outbox reintenta."""
    planned = await _planned_event()
    async with SessionFactory() as session, session.begin():
        event = await session.get(NotificationEvent, planned.id)
        assert event is not None
        event.status = resolved_status

    async with SessionFactory() as session, session.begin():
        await handle_notification_due(session, _message_for(planned.id))

    assert captured_sender.sent == []
