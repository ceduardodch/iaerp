"""Configuración del módulo de avisos desde la API (F4 del plan de avisos).

Cubre lo que `tests/test_notifications_foundation.py` y
`tests/test_notifications_catalog.py` no tocan: encender/apagar una regla
desde HTTP, editar y borrar plantillas, previsualizarlas, leer la bitácora
con filtros, dar acuse y reenviar. El planificador y el catálogo ya están
probados aparte; aquí solo se verifica que la nueva API los honre.
"""

import uuid
from datetime import UTC, date, datetime

from sqlalchemy import select

from app.db.session import SessionFactory
from app.models.notifications import NotificationDelivery, NotificationEvent, NotificationRule
from app.models.tax import TaxPeriod
from app.services.notifications import catalog, planner

TENANT_A = uuid.UUID("11111111-1111-4111-8111-111111111111")
TENANT_B = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")

DUE_DATE = date(2026, 9, 28)
# La regla de IVA_DECLARACION trae offsets "-7,-3,-1"; este es el primer aviso.
FIRST_REMINDER_DAY = date(2026, 9, 21)

_VALID_RULE_UPDATE = {
    "enabled": False,
    "scheduleKind": "OFFSET_TO_DUE",
    "offsetsDays": "-7,-3,-1",
    "sendHour": 8,
    "channels": "EMAIL",
    "audienceKind": "TENANT_USERS",
    "audienceRoles": [],
    "audienceEmails": [],
    "requireAck": True,
}


async def token_for(client, tenant_id: uuid.UUID, scopes: list[str]) -> str:
    email = "a@iaerp.local" if tenant_id == TENANT_A else "b@iaerp.local"
    response = await client.post(
        "/api/v1/dev/token",
        json={"email": email, "tenantId": str(tenant_id), "scopes": scopes},
    )
    assert response.status_code == 200, response.text
    return str(response.json()["accessToken"])


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def parse_dt(value: str) -> datetime:
    """Compara timestamps por valor, no por texto.

    SQLite (usado en pruebas locales sin ``TEST_DATABASE_URL``) devuelve un
    datetime naive para columnas ``DateTime(timezone=True)`` al releerlas de
    una sesión nueva, aunque se haya guardado uno con tzinfo UTC. Mismo
    comportamiento ya documentado en ``core/auth.py::resolve_auth_context``.
    """
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


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


async def seed_events(
    count: int,
    *,
    rule_type: str = "IVA_DECLARACION",
    status: str = "PENDING",
    tenant_id: uuid.UUID = TENANT_A,
) -> None:
    async with SessionFactory() as session, session.begin():
        for _ in range(count):
            session.add(
                NotificationEvent(
                    tenant_id=tenant_id,
                    rule_type=rule_type,
                    dedupe_key=f"seed:{rule_type}:{status}:{uuid.uuid4()}",
                    scheduled_at=datetime.now(UTC),
                    status=status,
                    payload={"period_label": "08/2026"},
                )
            )


async def seed_event_with_delivery(
    *,
    tenant_id: uuid.UUID = TENANT_A,
    status: str = "SENT",
) -> uuid.UUID:
    async with SessionFactory() as session, session.begin():
        event = NotificationEvent(
            tenant_id=tenant_id,
            rule_type="IVA_DECLARACION",
            dedupe_key=f"seed-detail:{uuid.uuid4()}",
            scheduled_at=datetime.now(UTC),
            status=status,
            payload={"period_label": "08/2026"},
        )
        session.add(event)
        await session.flush()
        session.add(
            NotificationDelivery(
                tenant_id=tenant_id,
                event_id=event.id,
                recipient="contadora@ejemplo.ec",
                provider="STUB",
                status="STUBBED",
            )
        )
        return event.id


# --------------------------------------------------------------------------
# Reglas
# --------------------------------------------------------------------------


async def test_listing_rules_creates_the_five_defaults_disabled_and_does_not_duplicate(
    client,
) -> None:
    token = await token_for(client, TENANT_A, ["notifications:read"])

    first = await client.get("/api/v1/notifications/rules", headers=auth(token))
    assert first.status_code == 200, first.text
    rules = first.json()
    assert len(rules) == 5
    assert {rule["ruleType"] for rule in rules} == set(catalog.IMPLEMENTED_RULE_TYPES)
    assert all(rule["enabled"] is False for rule in rules)

    second = await client.get("/api/v1/notifications/rules", headers=auth(token))
    assert second.status_code == 200, second.text
    assert len(second.json()) == 5


async def test_updating_a_rule_changes_its_fields_and_the_planner_honors_it(client) -> None:
    await create_period()
    token = await token_for(client, TENANT_A, ["notifications:read", "notifications:write"])

    listed = await client.get("/api/v1/notifications/rules", headers=auth(token))
    rule_id = next(r["id"] for r in listed.json() if r["ruleType"] == "IVA_DECLARACION")

    response = await client.put(
        f"/api/v1/notifications/rules/{rule_id}",
        headers={**auth(token), "Idempotency-Key": "rule-update-key-0000000001"},
        json={
            **_VALID_RULE_UPDATE,
            "enabled": True,
            "offsetsDays": "-7",
            "sendHour": 9,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["enabled"] is True
    assert body["offsetsDays"] == "-7"
    assert body["sendHour"] == 9
    assert body["requireAck"] is True

    # La regla quedó encendida de verdad: el planificador programa el aviso.
    assert await planner.plan_notifications_once(today=FIRST_REMINDER_DAY) == 1


async def test_updating_a_rule_from_another_tenant_or_missing_is_404(client) -> None:
    async with SessionFactory() as session, session.begin():
        await planner.ensure_default_rules(session, tenant_id=TENANT_B)
    async with SessionFactory() as session:
        other_rule_id = await session.scalar(
            select(NotificationRule.id).where(
                NotificationRule.tenant_id == TENANT_B,
                NotificationRule.rule_type == "IVA_DECLARACION",
            )
        )
    assert other_rule_id is not None

    token = await token_for(client, TENANT_A, ["notifications:write"])

    other_tenant_response = await client.put(
        f"/api/v1/notifications/rules/{other_rule_id}",
        headers={**auth(token), "Idempotency-Key": "rule-update-key-0000000002"},
        json=_VALID_RULE_UPDATE,
    )
    assert other_tenant_response.status_code == 404, other_tenant_response.text

    missing_response = await client.put(
        f"/api/v1/notifications/rules/{uuid.uuid4()}",
        headers={**auth(token), "Idempotency-Key": "rule-update-key-0000000003"},
        json=_VALID_RULE_UPDATE,
    )
    assert missing_response.status_code == 404, missing_response.text


# --------------------------------------------------------------------------
# Plantillas
# --------------------------------------------------------------------------


async def test_template_falls_back_to_the_catalog_default_until_customized(client) -> None:
    token = await token_for(client, TENANT_A, ["notifications:read", "notifications:write"])

    default_response = await client.get(
        "/api/v1/notifications/templates/IVA_DECLARACION", headers=auth(token)
    )
    assert default_response.status_code == 200, default_response.text
    default_body = default_response.json()
    assert default_body["isCustom"] is False
    assert default_body["subject"] == catalog.IVA_DECLARACION.subject

    put_response = await client.put(
        "/api/v1/notifications/templates/IVA_DECLARACION",
        headers={**auth(token), "Idempotency-Key": "template-update-key-000001"},
        json={"subject": "Ojo: IVA {{periodo}}", "body": "Vence {{fecha_limite}}."},
    )
    assert put_response.status_code == 200, put_response.text
    put_body = put_response.json()
    assert put_body["isCustom"] is True
    assert put_body["subject"] == "Ojo: IVA {{periodo}}"

    custom_response = await client.get(
        "/api/v1/notifications/templates/IVA_DECLARACION", headers=auth(token)
    )
    assert custom_response.json()["isCustom"] is True
    assert custom_response.json()["subject"] == "Ojo: IVA {{periodo}}"

    delete_response = await client.delete(
        "/api/v1/notifications/templates/IVA_DECLARACION", headers=auth(token)
    )
    assert delete_response.status_code == 200, delete_response.text
    assert delete_response.json()["isCustom"] is False

    after_delete = await client.get(
        "/api/v1/notifications/templates/IVA_DECLARACION", headers=auth(token)
    )
    assert after_delete.json()["isCustom"] is False
    assert after_delete.json()["subject"] == catalog.IVA_DECLARACION.subject


async def test_preview_renders_the_sample_payload_markers(client) -> None:
    token = await token_for(client, TENANT_A, ["notifications:write"])

    response = await client.post(
        "/api/v1/notifications/templates/IVA_DECLARACION/preview",
        headers=auth(token),
        json={
            "subject": catalog.IVA_DECLARACION.subject,
            "body": catalog.IVA_DECLARACION.body,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert "{{" not in body["subject"]
    assert "{{" not in body["bodyText"]
    assert "08/2026" in body["subject"]
    assert "28/09/2026" in body["bodyText"]


async def test_preview_for_an_unknown_rule_type_is_404(client) -> None:
    token = await token_for(client, TENANT_A, ["notifications:write"])
    response = await client.post(
        "/api/v1/notifications/templates/NOT_A_REAL_TYPE/preview",
        headers=auth(token),
        json={"subject": "x", "body": "y"},
    )
    assert response.status_code == 404, response.text


# --------------------------------------------------------------------------
# Bitácora de eventos
# --------------------------------------------------------------------------


async def test_events_filter_by_status_and_rule_type_and_the_limit_is_capped(client) -> None:
    await seed_events(3, rule_type="IVA_DECLARACION", status="PENDING")
    await seed_events(2, rule_type="IVA_DECLARACION", status="SENT")
    await seed_events(4, rule_type="CLIENTE_FACTURAR", status="PENDING")

    token = await token_for(client, TENANT_A, ["notifications:read"])

    by_status = await client.get(
        "/api/v1/notifications/events", headers=auth(token), params={"status": "SENT"}
    )
    assert by_status.status_code == 200, by_status.text
    assert len(by_status.json()) == 2
    assert all(item["status"] == "SENT" for item in by_status.json())

    by_rule_type = await client.get(
        "/api/v1/notifications/events",
        headers=auth(token),
        params={"ruleType": "CLIENTE_FACTURAR"},
    )
    assert by_rule_type.status_code == 200, by_rule_type.text
    assert len(by_rule_type.json()) == 4
    assert all(item["ruleType"] == "CLIENTE_FACTURAR" for item in by_rule_type.json())

    await seed_events(250, rule_type="RESUMEN_MENSUAL", status="PENDING")
    capped = await client.get(
        "/api/v1/notifications/events",
        headers=auth(token),
        params={"limit": 500},
    )
    assert capped.status_code == 200, capped.text
    assert len(capped.json()) == 200


async def test_event_detail_includes_its_deliveries(client) -> None:
    event_id = await seed_event_with_delivery()
    token = await token_for(client, TENANT_A, ["notifications:read"])

    response = await client.get(f"/api/v1/notifications/events/{event_id}", headers=auth(token))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["payload"] == {"period_label": "08/2026"}
    assert len(body["deliveries"]) == 1
    assert body["deliveries"][0]["recipient"] == "contadora@ejemplo.ec"
    assert body["deliveries"][0]["status"] == "STUBBED"


async def test_ack_sets_the_timestamp_once_and_a_second_call_does_not_overwrite_it(
    client,
) -> None:
    event_id = await seed_event_with_delivery()
    token = await token_for(client, TENANT_A, ["notifications:write"])

    first = await client.post(
        f"/api/v1/notifications/events/{event_id}/ack",
        headers={**auth(token), "Idempotency-Key": "ack-key-0000000000000001"},
    )
    assert first.status_code == 200, first.text
    first_ack_at = first.json()["ackAt"]
    assert first_ack_at is not None
    assert first.json()["ackBy"] is not None

    second = await client.post(
        f"/api/v1/notifications/events/{event_id}/ack",
        headers={**auth(token), "Idempotency-Key": "ack-key-0000000000000002"},
    )
    assert second.status_code == 200, second.text
    assert parse_dt(second.json()["ackAt"]) == parse_dt(first_ack_at)


async def test_resend_retries_delivery_for_a_failed_event(client) -> None:
    await create_period()
    # Primera corrida: no hay reglas encendidas todavía, pero de paso crea las
    # 5 filas por defecto (apagadas) para el tenant -- igual que en
    # ``test_notifications_foundation.py::_planned_event``.
    await planner.plan_notifications_once(today=FIRST_REMINDER_DAY)
    async with SessionFactory() as session, session.begin():
        rule = await session.scalar(
            select(NotificationRule).where(
                NotificationRule.tenant_id == TENANT_A,
                NotificationRule.rule_type == "IVA_DECLARACION",
            )
        )
        assert rule is not None
        rule.enabled = True
    assert await planner.plan_notifications_once(today=FIRST_REMINDER_DAY) == 1

    async with SessionFactory() as session, session.begin():
        event = (await session.scalars(select(NotificationEvent))).first()
        assert event is not None
        event.status = "FAILED"
        event.error_message = "Ningun envio prospero"
        event_id = event.id

    token = await token_for(client, TENANT_A, ["notifications:write"])
    response = await client.post(
        f"/api/v1/notifications/events/{event_id}/resend",
        headers={**auth(token), "Idempotency-Key": "resend-key-0000000000001"},
    )
    assert response.status_code == 200, response.text
    # Sin BREVO_API_KEY en pruebas, el remitente activo es el stub: nunca "SENT".
    assert response.json()["status"] == "STUBBED"

    async with SessionFactory() as session:
        deliveries = list(
            await session.scalars(
                select(NotificationDelivery).where(NotificationDelivery.event_id == event_id)
            )
        )
    assert len(deliveries) == 1
    assert deliveries[0].recipient == "a@iaerp.local"
    assert deliveries[0].status == "STUBBED"


# --------------------------------------------------------------------------
# Aislamiento de tenant y scopes
# --------------------------------------------------------------------------


async def test_tenant_isolation_across_rules_templates_and_events(client) -> None:
    token_a = await token_for(client, TENANT_A, ["notifications:read", "notifications:write"])
    token_b = await token_for(client, TENANT_B, ["notifications:read", "notifications:write"])

    # Plantillas: B personaliza IVA_DECLARACION; A sigue viendo el default.
    put_b = await client.put(
        "/api/v1/notifications/templates/IVA_DECLARACION",
        headers={**auth(token_b), "Idempotency-Key": "isolation-template-key-0001"},
        json={"subject": "Solo para B", "body": "Cuerpo de B"},
    )
    assert put_b.status_code == 200, put_b.text

    a_view = await client.get(
        "/api/v1/notifications/templates/IVA_DECLARACION", headers=auth(token_a)
    )
    assert a_view.json()["isCustom"] is False
    assert a_view.json()["subject"] == catalog.IVA_DECLARACION.subject

    # Reglas: A no puede tocar una regla de B.
    async with SessionFactory() as session, session.begin():
        await planner.ensure_default_rules(session, tenant_id=TENANT_B)
    async with SessionFactory() as session:
        b_rule_id = await session.scalar(
            select(NotificationRule.id).where(
                NotificationRule.tenant_id == TENANT_B,
                NotificationRule.rule_type == "IVA_DECLARACION",
            )
        )
    rule_put = await client.put(
        f"/api/v1/notifications/rules/{b_rule_id}",
        headers={**auth(token_a), "Idempotency-Key": "isolation-rule-key-0000001"},
        json=_VALID_RULE_UPDATE,
    )
    assert rule_put.status_code == 404, rule_put.text

    # Eventos: A no puede leer, dar acuse ni reenviar un evento de B.
    b_event_id = await seed_event_with_delivery(tenant_id=TENANT_B)

    detail = await client.get(f"/api/v1/notifications/events/{b_event_id}", headers=auth(token_a))
    assert detail.status_code == 404, detail.text

    ack = await client.post(
        f"/api/v1/notifications/events/{b_event_id}/ack",
        headers={**auth(token_a), "Idempotency-Key": "isolation-ack-key-0000001"},
    )
    assert ack.status_code == 404, ack.text

    resend = await client.post(
        f"/api/v1/notifications/events/{b_event_id}/resend",
        headers={**auth(token_a), "Idempotency-Key": "isolation-resend-key-0000001"},
    )
    assert resend.status_code == 404, resend.text


async def test_missing_scope_is_rejected_on_a_get_and_a_post(client) -> None:
    token = await token_for(client, TENANT_A, ["invoices:read"])

    get_response = await client.get("/api/v1/notifications/rules", headers=auth(token))
    assert get_response.status_code == 403, get_response.text

    post_response = await client.post(
        f"/api/v1/notifications/events/{uuid.uuid4()}/ack",
        headers={**auth(token), "Idempotency-Key": "scope-check-key-0000000001"},
    )
    assert post_response.status_code == 403, post_response.text
