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

    # `staging` es un entorno online seguro para PRUEBAS: exige OIDC y Postgres
    # como release/production (nunca `/dev/token` abierto ni SQLite), pero SI
    # permite el simulador SRI para poder facturar sin un certificado real ante
    # el SRI. `release`/`production` prohiben el simulador.
    APP_ENV: Literal["development", "test", "staging", "release", "production"] = "development"
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

    # Firma XAdES-BES (ver app/services/signing.py). El certificado de
    # PRUEBA nunca se versiona (backend/certs/ en .gitignore); en dev/test se
    # genera automaticamente si falta, ejecutando
    # scripts/generate_test_certificate.py.
    IAERP_SIGNING_CERT_PATH: str | None = None
    IAERP_SIGNING_CERT_PASSWORD: SecretStr | None = None

    # Simulador SRI (ver app/integrations/sri/simulator.py). Solo se monta el
    # router `/sri-sim` si esta habilitado; NUNCA puede habilitarse fuera de
    # development/test (docs/sprints/sprint-02.md, decision 7).
    SRI_SIMULATOR_ENABLED: bool = True

    # Almacenamiento privado de artefactos (XML firmado, RIDE PDF) en MinIO,
    # ver ADR 0005 y app/services/storage.py. Defaults del compose local.
    MINIO_ENDPOINT: str = "localhost:9000"
    # Endpoint alcanzable por el consumidor final de las URL prefirmadas (el
    # navegador). En Compose el backend habla con MinIO por la red interna
    # (`minio:9000`), pero ese host no resuelve desde el host/navegador; en ese
    # caso se fija a `localhost:9000`. Si es None, se reutiliza MINIO_ENDPOINT
    # (despliegue con un unico host publico).
    MINIO_PUBLIC_ENDPOINT: str | None = None
    MINIO_ACCESS_KEY: str = "iaerp-local"
    MINIO_SECRET_KEY: SecretStr = SecretStr("iaerp-local-password")
    MINIO_SECURE: bool = False
    MINIO_REGION: str = "us-east-1"
    MINIO_DOCUMENTS_BUCKET: str = "iaerp-documents"

    @model_validator(mode="after")
    def validate_production_security(self) -> "Settings":
        # Entornos endurecidos: nunca auth dev ni SQLite. `staging` se incluye
        # porque es online (accesible fuera de la maquina del desarrollador) y
        # no debe exponer `/dev/token` ni correr sobre SQLite.
        hardened_envs = {"staging", "release", "production"}
        # El simulador SRI solo se prohibe en produccion/preprod real; en
        # `staging` se permite para poder probar el ciclo de facturacion sin un
        # certificado real ante el SRI.
        simulator_forbidden_envs = {"release", "production"}
        if self.APP_ENV in hardened_envs:
            if self.AUTH_MODE == "dev":
                raise ValueError("AUTH_MODE=dev is forbidden outside development/test")
            if self.DATABASE_URL.startswith("sqlite"):
                raise ValueError("SQLite is forbidden outside development/test")
        if self.APP_ENV in simulator_forbidden_envs and self.SRI_SIMULATOR_ENABLED:
            raise ValueError("SRI_SIMULATOR_ENABLED is forbidden in release/production")
        if self.AUTH_MODE == "dev" and len(self.DEV_JWT_SECRET) < 32:
            raise ValueError("DEV_JWT_SECRET must have at least 32 characters")
        return self

    def cors_origins(self) -> list[str]:
        return [item.strip() for item in self.CORS_ORIGINS.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
