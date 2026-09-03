"""Configuración del módulo de avisos desde fuera de SQL (F4 del plan de avisos).

Separado de ``delivery.py`` y ``planner.py`` a propósito: aquellos deciden
*cuándo* avisar y *qué decir*; este módulo deja que una persona **cambie**
esas decisiones sin tocar código -- encender/apagar reglas, editar
plantillas, revisar la bitácora, dar acuse o reenviar.

Ninguna función de aquí hace ``session.commit()`` ni abre ``session.begin()``:
eso lo maneja el endpoint (``execute_idempotent`` para las escrituras
auditadas, un ``session.commit()`` directo para las lecturas que de paso
crean las reglas por defecto).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthContext
from app.integrations.notifications.email_sender import EmailSender
from app.models.notifications import (
    NotificationDelivery,
    NotificationEvent,
    NotificationRule,
    NotificationTemplate,
)
from app.models.platform import Tenant
from app.schemas.notifications import (
    NotificationRuleUpdate,
    NotificationTemplatePreviewRequest,
    NotificationTemplateUpdate,
)
from app.services.notifications import catalog, channels, delivery, planner

# Tope duro de ``GET /notifications/events``: el endpoint nunca confía en el
# límite que pida el query param, aunque la validación de FastAPI ya acote su
# rango razonable. Ver el docstring de ``list_events``.
DEFAULT_EVENTS_LIMIT = 50
MAX_EVENTS_LIMIT = 200

# Payloads de ejemplo para la vista previa de plantillas: uno por tipo de
# aviso implementado, con las claves exactas que lee cada
# ``_*_values`` de ``delivery.py``. No son datos al azar: son legibles y
# representativos de lo que un aviso real trae en su ``payload``.
_SAMPLE_PAYLOADS: dict[str, dict[str, object]] = {
    "IVA_DECLARACION": {
        "period_label": "08/2026",
        "due_date": "2026-09-28",
        "days_remaining": 7,
        "period_status": "EVIDENCIA_INCOMPLETA",
        "open_tasks": ["Completar evidencia tributaria 08/2026"],
        "holidays_checked": False,
    },
    "CLIENTE_FACTURAR": {
        "party_name": "ACME S.A.",
        "period_label": "09/2026",
        "billing_day": 10,
        "amount_hint": "1250.50",
        "notes": "Revisar consumo AWS del mes",
    },
    "IESS_APORTE": {
        "period_label": "08/2026",
        "due_date": "2026-09-15",
        "days_remaining": 5,
        "employee_count": 2,
        "aporte_personal": "189.00",
        "holidays_checked": False,
    },
    "RESUMEN_MENSUAL": {
        "period_label": "08/2026",
        "income_total": "115.00",
        "income_count": 1,
        "expense_total": "40.00",
        "expense_count": 1,
        "result_total": "75.00",
        "preliminary_purchase_count": 1,
    },
    "IVA_PREVIEW_MENSUAL": {
        "period_label": "09/2026",
        "iva_generado": "15.00",
        "credito_tributario": "6.00",
        "saldo_a_pagar": "9.00",
        "document_count": 4,
        "is_preliminary": False,
        "preliminary_reasons": [],
    },
}


async def list_rules(session: AsyncSession, context: AuthContext) -> list[NotificationRule]:
    """Reglas del tenant, creando primero las que falten del catálogo.

    Así la pantalla siempre muestra los tipos implementados aunque el
    scheduler nunca haya corrido para este tenant (por ejemplo, un tenant
    recién creado). ``ensure_default_rules`` es idempotente: no duplica.
    """
    await planner.ensure_default_rules(session, tenant_id=context.tenant_id)
    return list(
        await session.scalars(
            select(NotificationRule)
            .where(NotificationRule.tenant_id == context.tenant_id)
            .order_by(NotificationRule.rule_type)
        )
    )


async def update_rule(
    session: AsyncSession,
    context: AuthContext,
    rule_id: uuid.UUID,
    data: NotificationRuleUpdate,
) -> NotificationRule:
    """Reemplazo completo de la parametrización de una regla.

    ``rule_type`` no se toca: no viene en ``NotificationRuleUpdate``, así que
    no hay forma de que un PUT reasigne una regla a otro tipo de aviso.
    """
    rule = await session.scalar(
        select(NotificationRule)
        .where(
            NotificationRule.tenant_id == context.tenant_id,
            NotificationRule.id == rule_id,
        )
        .with_for_update()
    )
    if rule is None:
        raise HTTPException(status_code=404, detail="Notification rule not found")
    rule.enabled = data.enabled
    rule.schedule_kind = data.schedule_kind
    rule.days_of_month = data.days_of_month
    rule.offsets_days = data.offsets_days
    rule.send_hour = data.send_hour
    rule.channels = data.channels
    rule.audience_kind = data.audience_kind
    rule.audience_roles = list(data.audience_roles)
    rule.audience_emails = [str(email) for email in data.audience_emails]
    rule.require_ack = data.require_ack
    await session.flush()
    # ``updated_at`` is server-managed (``onupdate=func.now()``); a flush expires
    # it, and reading the expired attribute from a sync context (like Pydantic's
    # ``model_validate``) would try an implicit synchronous load and fail with
    # ``MissingGreenlet``. Same fix as ``put_collection_policy`` in api/router.py.
    await session.refresh(rule)
    return rule


async def get_template(
    session: AsyncSession,
    context: AuthContext,
    rule_type: str,
) -> tuple[NotificationTemplate, bool]:
    """Plantilla del tenant, o el default del catálogo si no personalizó nada.

    El objeto "virtual" que se arma para el default nunca se agrega a la
    sesión: es solo un contenedor de lectura, no debe poder persistirse por
    accidente.
    """
    if rule_type not in catalog.DEFINITIONS:
        raise HTTPException(status_code=404, detail="Unknown notification rule type")
    existing = await session.scalar(
        select(NotificationTemplate).where(
            NotificationTemplate.tenant_id == context.tenant_id,
            NotificationTemplate.rule_type == rule_type,
        )
    )
    if existing is not None:
        return existing, True
    definition = catalog.definition_for(rule_type)
    virtual = NotificationTemplate(
        tenant_id=context.tenant_id,
        rule_type=rule_type,
        subject=definition.subject,
        body=definition.body,
    )
    return virtual, False


async def put_template(
    session: AsyncSession,
    context: AuthContext,
    rule_type: str,
    data: NotificationTemplateUpdate,
) -> NotificationTemplate:
    if rule_type not in catalog.DEFINITIONS:
        raise HTTPException(status_code=404, detail="Unknown notification rule type")
    template = await session.scalar(
        select(NotificationTemplate)
        .where(
            NotificationTemplate.tenant_id == context.tenant_id,
            NotificationTemplate.rule_type == rule_type,
        )
        .with_for_update()
    )
    if template is None:
        template = NotificationTemplate(tenant_id=context.tenant_id, rule_type=rule_type)
        session.add(template)
    template.subject = data.subject
    template.body = data.body
    await session.flush()
    return template


async def delete_template(session: AsyncSession, context: AuthContext, rule_type: str) -> None:
    """Vuelve al default del catálogo. No falla si no había fila propia."""
    template = await session.scalar(
        select(NotificationTemplate).where(
            NotificationTemplate.tenant_id == context.tenant_id,
            NotificationTemplate.rule_type == rule_type,
        )
    )
    if template is not None:
        await session.delete(template)
        await session.flush()


async def preview_template(
    session: AsyncSession,
    context: AuthContext,
    rule_type: str,
    data: NotificationTemplatePreviewRequest,
) -> tuple[str, str, str]:
    """Renderiza ``data`` con un payload de ejemplo. No persiste nada."""
    if rule_type not in catalog.DEFINITIONS:
        raise HTTPException(status_code=404, detail="Unknown notification rule type")
    tenant = await session.get(Tenant, context.tenant_id)
    company_name = tenant.name if tenant is not None else ""
    payload = _SAMPLE_PAYLOADS.get(rule_type, {})
    values = delivery.placeholder_values(
        rule_type=rule_type, company_name=company_name, payload=payload
    )
    return delivery.render(subject_template=data.subject, body_template=data.body, values=values)


async def list_events(
    session: AsyncSession,
    context: AuthContext,
    *,
    status: str | None,
    rule_type: str | None,
    limit: int,
) -> list[NotificationEvent]:
    """Bitácora del tenant, más reciente primero.

    ``limit`` ya debe venir acotado por el caller (ver ``MAX_EVENTS_LIMIT``):
    esta función no vuelve a acotarlo para no esconder un límite mayor pasado
    por error en una llamada interna.
    """
    statement = select(NotificationEvent).where(NotificationEvent.tenant_id == context.tenant_id)
    if status is not None:
        statement = statement.where(NotificationEvent.status == status)
    if rule_type is not None:
        statement = statement.where(NotificationEvent.rule_type == rule_type)
    statement = statement.order_by(NotificationEvent.scheduled_at.desc()).limit(limit)
    return list(await session.scalars(statement))


async def get_event_detail(
    session: AsyncSession,
    context: AuthContext,
    event_id: uuid.UUID,
) -> tuple[NotificationEvent, list[NotificationDelivery]]:
    event = await session.scalar(
        select(NotificationEvent).where(
            NotificationEvent.tenant_id == context.tenant_id,
            NotificationEvent.id == event_id,
        )
    )
    if event is None:
        raise HTTPException(status_code=404, detail="Notification event not found")
    deliveries = list(
        await session.scalars(
            select(NotificationDelivery).where(
                NotificationDelivery.tenant_id == context.tenant_id,
                NotificationDelivery.event_id == event_id,
            )
        )
    )
    return event, deliveries


async def ack_event(
    session: AsyncSession,
    context: AuthContext,
    event_id: uuid.UUID,
) -> NotificationEvent:
    """Registra el acuse humano. Dar acuse dos veces es un no-op, no un error."""
    event = await session.scalar(
        select(NotificationEvent)
        .where(
            NotificationEvent.tenant_id == context.tenant_id,
            NotificationEvent.id == event_id,
        )
        .with_for_update()
    )
    if event is None:
        raise HTTPException(status_code=404, detail="Notification event not found")
    if event.ack_at is None:
        event.ack_at = datetime.now(UTC)
        event.ack_by = context.actor_id
        await session.flush()
    return event


async def resend_event(
    session: AsyncSession,
    context: AuthContext,
    event_id: uuid.UUID,
    sender: EmailSender | None = None,
) -> NotificationEvent:
    """Reintenta la entrega a pedido humano, fuera del outbox del scheduler.

    Reutiliza ``delivery.deliver_event``: revisa de nuevo si el aviso sigue
    vigente (``_should_skip``) y actualiza cada ``NotificationDelivery``,
    igual que un despacho normal.
    """
    event = await session.scalar(
        select(NotificationEvent)
        .where(
            NotificationEvent.tenant_id == context.tenant_id,
            NotificationEvent.id == event_id,
        )
        .with_for_update()
    )
    if event is None:
        raise HTTPException(status_code=404, detail="Notification event not found")
    await delivery.deliver_event(
        session, event=event, sender=sender or channels.build_email_sender()
    )
    return event


__all__ = [
    "DEFAULT_EVENTS_LIMIT",
    "MAX_EVENTS_LIMIT",
    "ack_event",
    "delete_template",
    "get_event_detail",
    "get_template",
    "list_events",
    "list_rules",
    "preview_template",
    "put_template",
    "resend_event",
    "update_rule",
]
