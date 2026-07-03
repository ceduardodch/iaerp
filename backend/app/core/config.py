from functools import lru_cache
from typing import Literal

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=True,
        extra="ignore",
    )

    APP_ENV: Literal["development", "test", "release", "production"] = "development"
    PROJECT_NAME: str = "IAERP"
    API_PREFIX: str = "/api/v1"
    DATABASE_URL: str = "sqlite+aiosqlite:///./iaerp.db"

    AUTH_MODE: Literal["dev", "oidc"] = "dev"
    DEV_JWT_SECRET: str = "development-only-secret-change-before-shared-use"
    OIDC_ISSUER_URL: str = "http://localhost:8080/realms/iaerp"
    OIDC_JWKS_URL: str | None = None
    OIDC_API_AUDIENCE: str = "iaerp-api"
    OIDC_MCP_AUDIENCE: str = "http://localhost:8000/mcp"
    MCP_SERVER_URL: str = "http://localhost:8000/mcp"
    OIDC_ADMIN_URL: str | None = None
    OIDC_ADMIN_REALM: str = "iaerp"
    OIDC_ADMIN_CLIENT_ID: str | None = None
    OIDC_ADMIN_CLIENT_SECRET: SecretStr | None = None

    CORS_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173"
    REDIS_URL: str = "redis://localhost:6379/0"
    MCP_ENABLED: bool = True
    OUTBOX_BATCH_SIZE: int = 50
    OUTBOX_LEASE_SECONDS: int = 60
    OUTBOX_MAX_ATTEMPTS: int = 8
    DISPATCHER_HEARTBEAT_KEY: str = "iaerp:dispatcher:heartbeat"
    DISPATCHER_HEARTBEAT_TTL_SECONDS: int = 15

    @model_validator(mode="after")
    def validate_production_security(self) -> "Settings":
        if self.APP_ENV in {"release", "production"}:
            if self.AUTH_MODE == "dev":
                raise ValueError("AUTH_MODE=dev is forbidden outside development/test")
            if self.DATABASE_URL.startswith("sqlite"):
                raise ValueError("SQLite is forbidden outside development/test")
        if self.AUTH_MODE == "dev" and len(self.DEV_JWT_SECRET) < 32:
            raise ValueError("DEV_JWT_SECRET must have at least 32 characters")
        return self

    def cors_origins(self) -> list[str]:
        return [item.strip() for item in self.CORS_ORIGINS.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
