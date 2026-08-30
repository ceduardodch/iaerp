"""Integración opcional con Sentry/GlitchTip (app/core/observability.py).

Pendiente 9 de docs/OBSERVABILIDAD_PENDIENTES.md: gateada por
``IAERP_ERROR_DSN``. Sin DSN (default) no debe llamar a ``sentry_sdk`` ni
cambiar de comportamiento.
"""

from contextlib import contextmanager

import sentry_sdk

from app.core import observability
from app.core.config import Settings


def _settings(dsn: str | None) -> Settings:
    return Settings(IAERP_ERROR_DSN=dsn, IAERP_SECRETS_ENCRYPTION_KEY=None)


def test_init_error_tracking_is_noop_without_dsn(monkeypatch) -> None:
    calls: list[tuple] = []
    monkeypatch.setattr(sentry_sdk, "init", lambda *a, **kw: calls.append((a, kw)))
    observability._enabled = True  # simula un estado previo para probar que se apaga

    observability.init_error_tracking(_settings(None), release="iaerp-backend@0.1.0")

    assert calls == []
    assert observability._enabled is False


def test_init_error_tracking_calls_sentry_init_with_dsn(monkeypatch) -> None:
    calls: list[tuple] = []
    monkeypatch.setattr(sentry_sdk, "init", lambda *a, **kw: calls.append((a, kw)))

    settings = _settings("https://public@example.ingest.sentry.io/1")
    observability.init_error_tracking(settings, release="iaerp-backend@0.1.0")

    assert observability._enabled is True
    [(args, kwargs)] = calls
    assert args == ()
    assert kwargs["dsn"] == "https://public@example.ingest.sentry.io/1"
    assert kwargs["environment"] == settings.APP_ENV
    assert kwargs["release"] == "iaerp-backend@0.1.0"
    assert kwargs["send_default_pii"] is False


def test_capture_exception_is_noop_when_disabled(monkeypatch) -> None:
    observability._enabled = False
    captured: list[BaseException] = []
    monkeypatch.setattr(sentry_sdk, "capture_exception", lambda exc: captured.append(exc))

    observability.capture_exception(
        RuntimeError("boom"), correlation_id="corr-1", tenant_hash="abc123", actor_id="user-1"
    )

    assert captured == []


def test_capture_exception_sets_tags_and_reports_when_enabled(monkeypatch) -> None:
    observability._enabled = True
    captured: list[BaseException] = []
    tags: dict[str, str] = {}

    class _FakeScope:
        def set_tag(self, key: str, value: str) -> None:
            tags[key] = value

    @contextmanager
    def _fake_new_scope():
        yield _FakeScope()

    monkeypatch.setattr(sentry_sdk, "new_scope", _fake_new_scope)
    monkeypatch.setattr(sentry_sdk, "capture_exception", lambda exc: captured.append(exc))

    exc = RuntimeError("boom")
    observability.capture_exception(
        exc, correlation_id="corr-1", tenant_hash="abc123", actor_id="user-1"
    )

    assert captured == [exc]
    assert tags == {"correlation_id": "corr-1", "tenant": "abc123", "actor": "user-1"}


def test_capture_exception_omits_tags_that_are_none(monkeypatch) -> None:
    observability._enabled = True
    tags: dict[str, str] = {}

    class _FakeScope:
        def set_tag(self, key: str, value: str) -> None:
            tags[key] = value

    @contextmanager
    def _fake_new_scope():
        yield _FakeScope()

    monkeypatch.setattr(sentry_sdk, "new_scope", _fake_new_scope)
    monkeypatch.setattr(sentry_sdk, "capture_exception", lambda exc: None)

    observability.capture_exception(
        RuntimeError("boom"), correlation_id="corr-1", tenant_hash=None, actor_id=None
    )

    assert tags == {"correlation_id": "corr-1"}


def teardown_module() -> None:
    # No dejar el flag global en un estado que contamine otros tests del área.
    observability._enabled = False
