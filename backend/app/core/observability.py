"""Integración opcional con Sentry/GlitchTip (pendiente 9 de
docs/OBSERVABILIDAD_PENDIENTES.md).

Gateada por ``IAERP_ERROR_DSN``: vacío (default) = desactivado y ambas
funciones son no-op, sin tocar la red ni cambiar el comportamiento de la
aplicación.
"""

import sentry_sdk

from app.core.config import Settings

_enabled = False


def init_error_tracking(settings: Settings, *, release: str) -> None:
    global _enabled
    if not settings.IAERP_ERROR_DSN:
        _enabled = False
        return
    sentry_sdk.init(
        dsn=settings.IAERP_ERROR_DSN,
        environment=settings.APP_ENV,
        release=release,
        send_default_pii=False,
    )
    _enabled = True


def capture_exception(
    exc: BaseException,
    *,
    correlation_id: str,
    tenant_hash: str | None,
    actor_id: str | None,
) -> None:
    """No-op si Sentry no fue inicializado (``IAERP_ERROR_DSN`` vacío)."""
    if not _enabled:
        return
    with sentry_sdk.new_scope() as scope:
        scope.set_tag("correlation_id", correlation_id)
        if tenant_hash is not None:
            scope.set_tag("tenant", tenant_hash)
        if actor_id is not None:
            scope.set_tag("actor", actor_id)
        sentry_sdk.capture_exception(exc)
