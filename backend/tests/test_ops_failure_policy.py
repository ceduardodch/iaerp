"""Politica de reintento automatico de fallos operativos.

``classify_failure()`` es la unica puerta entre un ``DeadLetter`` y un
reintento sin intervencion humana (pendiente 4). La lista blanca es explicita
y de default-deny: un ``event_type`` nuevo NUNCA debe entrar aqui sin que su
handler demuestre reconciliacion idempotente (ver
``docs/OBSERVABILIDAD_PENDIENTES.md``, regla 7). Este archivo es intocable
para debilitar la lista: si una prueba falla, el error esta en el codigo
nuevo, no en la prueba.
"""

from app.services.ops_failures import classify_failure
from app.services.social_campaigns import (
    CAMPAIGN_ACTIVATION_EVENT,
    CAMPAIGN_PAUSE_EVENT,
    CAMPAIGN_POLICY_EVENT,
    CAMPAIGN_PREPARATION_EVENT,
)
from app.services.tax.xml_recovery import RECOVERY_REQUESTED_EVENT
from app.workers.collections import COLLECTION_REMINDER_DUE_EVENT
from app.workers.sri_transmission import CREDIT_NOTE_AUTHORIZED_EVENT, INVOICE_AUTHORIZED_EVENT


def test_invoice_signed_is_auto_retry() -> None:
    """``handle_invoice_signed`` nunca retransmite una clave ya aceptada por el
    SRI: antes de reenviar, reconcilia contra ``SRITransmission`` existente
    (RECEIVED/PENDING_AUTHORIZATION/AUTHORIZED). Es el unico caso con
    reconciliacion idempotente demostrada, por eso es el unico AUTO_RETRY.
    """
    assert classify_failure("invoice.signed") == "AUTO_RETRY"


def test_events_without_demonstrated_reconciliation_need_human() -> None:
    """Ningun otro event_type del sistema tiene reconciliacion demostrada:
    reintentarlos solos podria duplicar cartera, notas de credito, campañas
    publicadas o recordatorios de cobranza ya enviados.
    """
    events_needing_human = [
        INVOICE_AUTHORIZED_EVENT,
        CREDIT_NOTE_AUTHORIZED_EVENT,
        COLLECTION_REMINDER_DUE_EVENT,
        CAMPAIGN_ACTIVATION_EVENT,
        CAMPAIGN_PAUSE_EVENT,
        CAMPAIGN_POLICY_EVENT,
        CAMPAIGN_PREPARATION_EVENT,
        RECOVERY_REQUESTED_EVENT,
        "tax.evidence.sri_recovered",
    ]
    for event_type in events_needing_human:
        assert classify_failure(event_type) == "NEEDS_HUMAN", event_type


def test_unknown_event_type_defaults_to_needs_human() -> None:
    """Default-deny: un event_type nunca visto no puede colarse como AUTO_RETRY."""
    assert classify_failure("some.brand.new.event") == "NEEDS_HUMAN"
    assert classify_failure("") == "NEEDS_HUMAN"
