"""Pruebas de validacion de ``Settings`` para el simulador SRI.

``SRI_SIMULATOR_ENABLED`` sigue el mismo patron que ``AUTH_MODE=dev``: nunca
puede quedar habilitado fuera de development/test (ver
``docs/sprints/sprint-02.md``, decision 7, y ``app/core/config.py``).
"""

import pytest

from app.core.config import Settings


def test_sri_simulator_enabled_is_forbidden_in_release() -> None:
    with pytest.raises(ValueError, match="SRI_SIMULATOR_ENABLED"):
        Settings(
            APP_ENV="release",
            AUTH_MODE="oidc",
            DATABASE_URL="postgresql+asyncpg://user:pass@localhost/db",  # pragma: allowlist secret
            SRI_SIMULATOR_ENABLED=True,
            DEV_JWT_SECRET="x" * 40,
        )


def test_sri_simulator_enabled_is_forbidden_in_production() -> None:
    with pytest.raises(ValueError, match="SRI_SIMULATOR_ENABLED"):
        Settings(
            APP_ENV="production",
            AUTH_MODE="oidc",
            DATABASE_URL="postgresql+asyncpg://user:pass@localhost/db",  # pragma: allowlist secret
            SRI_SIMULATOR_ENABLED=True,
            DEV_JWT_SECRET="x" * 40,
        )


def test_sri_simulator_disabled_is_allowed_in_release() -> None:
    settings = Settings(
        APP_ENV="release",
        AUTH_MODE="oidc",
        DATABASE_URL="postgresql+asyncpg://user:pass@localhost/db",  # pragma: allowlist secret
        SRI_SIMULATOR_ENABLED=False,
        DEV_JWT_SECRET="x" * 40,
    )
    assert settings.SRI_SIMULATOR_ENABLED is False


def test_sri_simulator_enabled_by_default_in_development() -> None:
    settings = Settings(APP_ENV="development", DEV_JWT_SECRET="x" * 40)
    assert settings.SRI_SIMULATOR_ENABLED is True


def test_staging_allows_oidc_with_sri_simulator() -> None:
    """staging es online-seguro: OIDC + simulador para probar facturacion."""
    settings = Settings(
        APP_ENV="staging",
        AUTH_MODE="oidc",
        DATABASE_URL="postgresql+asyncpg://user:pass@localhost/db",  # pragma: allowlist secret
        SRI_SIMULATOR_ENABLED=True,
    )
    assert settings.APP_ENV == "staging"
    assert settings.SRI_SIMULATOR_ENABLED is True


def test_staging_forbids_dev_auth() -> None:
    """staging es accesible online: nunca `/dev/token` abierto (AUTH_MODE=dev)."""
    with pytest.raises(ValueError, match="AUTH_MODE=dev"):
        Settings(
            APP_ENV="staging",
            AUTH_MODE="dev",
            DATABASE_URL="postgresql+asyncpg://user:pass@localhost/db",  # pragma: allowlist secret
            DEV_JWT_SECRET="x" * 40,
        )


def test_staging_forbids_sqlite() -> None:
    with pytest.raises(ValueError, match="SQLite"):
        Settings(
            APP_ENV="staging",
            AUTH_MODE="oidc",
            DATABASE_URL="sqlite+aiosqlite:///./iaerp.db",  # pragma: allowlist secret
        )
