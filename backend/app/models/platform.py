import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Tenant(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "tenants"

    ruc: Mapped[str] = mapped_column(String(13), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    organization_id: Mapped[str | None] = mapped_column(String(100), unique=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class TenantFiscalSettings(TimestampMixin, Base):
    __tablename__ = "tenant_fiscal_settings"
    __table_args__ = (
        CheckConstraint(
            "sri_environment IN ('1', '2')",
            name="sri_environment_valid",
        ),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        primary_key=True,
    )
    sri_environment: Mapped[str] = mapped_column(String(1), default="1")
    certificate_object_key: Mapped[str | None] = mapped_column(String(500))
    certificate_password_encrypted: Mapped[str | None] = mapped_column(Text)
    certificate_fingerprint_sha256: Mapped[str | None] = mapped_column(String(64))
    certificate_subject: Mapped[str | None] = mapped_column(String(500))
    certificate_valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    certificate_valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    certificate_uploaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"

    external_subject: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(200))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Membership(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "memberships"
    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id", name="uq_memberships_tenant_user"),
        Index("ix_memberships_user_active", "user_id", "active"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    roles: Mapped[list[str]] = mapped_column(JSON, default=list)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class ServiceAccount(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "service_accounts"
    __table_args__ = (
        UniqueConstraint("tenant_id", "client_id", name="uq_service_accounts_tenant_client"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    client_id: Mapped[str] = mapped_column(String(200), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    scopes: Mapped[list[str]] = mapped_column(JSON, default=list)
    secret_hash: Mapped[str] = mapped_column(String(200))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AutomationSettings(TimestampMixin, Base):
    __tablename__ = "automation_settings"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id"),
        primary_key=True,
    )
    writes_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    daily_amount_limit: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        default=Decimal("0.00"),
    )


class IdempotencyRecord(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "idempotency_records"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "actor_id",
            "operation",
            "idempotency_key",
            name="uq_idempotency_scope",
        ),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    actor_id: Mapped[str] = mapped_column(String(200))
    operation: Mapped[str] = mapped_column(String(120))
    idempotency_key: Mapped[str] = mapped_column(String(128))
    request_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(30), default="PROCESSING")
    response_status: Mapped[int | None]
    response_body: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AuditEvent(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        UniqueConstraint("tenant_id", "sequence", name="uq_audit_tenant_sequence"),
        Index("ix_audit_tenant_created", "tenant_id", "created_at"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    sequence: Mapped[int]
    actor_id: Mapped[str] = mapped_column(String(200))
    actor_type: Mapped[str] = mapped_column(String(30))
    action: Mapped[str] = mapped_column(String(120))
    entity_type: Mapped[str] = mapped_column(String(80))
    entity_id: Mapped[str | None] = mapped_column(String(100))
    correlation_id: Mapped[str] = mapped_column(String(100), index=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(128))
    decision: Mapped[str] = mapped_column(String(30))
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    previous_hash: Mapped[str | None] = mapped_column(String(64))
    event_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )


class OutboxEvent(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "outbox_events"
    __table_args__ = (Index("ix_outbox_pending", "published_at", "available_at"),)

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(120))
    aggregate_type: Mapped[str] = mapped_column(String(80))
    aggregate_id: Mapped[str] = mapped_column(String(100))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    correlation_id: Mapped[str] = mapped_column(String(100), index=True)
    attempts: Mapped[int] = mapped_column(default=0)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dead_lettered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )


class InboxEvent(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "inbox_events"
    __table_args__ = (
        UniqueConstraint(
            "consumer_name",
            "event_id",
            name="uq_inbox_consumer_event",
        ),
        Index("ix_inbox_tenant_created", "tenant_id", "created_at"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    consumer_name: Mapped[str] = mapped_column(String(120))
    event_id: Mapped[uuid.UUID]
    status: Mapped[str] = mapped_column(String(30), default="PROCESSING")
    attempts: Mapped[int] = mapped_column(default=1)
    last_error: Mapped[str | None] = mapped_column(Text)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )


class DeadLetter(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "dead_letters"
    __table_args__ = (
        UniqueConstraint(
            "source_type",
            "source_id",
            name="uq_dead_letter_source",
        ),
        Index("ix_dead_letter_tenant_created", "tenant_id", "created_at"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    source_type: Mapped[str] = mapped_column(String(40))
    source_id: Mapped[uuid.UUID]
    event_type: Mapped[str] = mapped_column(String(120))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    error: Mapped[str] = mapped_column(Text)
    attempts: Mapped[int]
    status: Mapped[str] = mapped_column(String(30), default="OPEN")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OperationRecord(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "operations"

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    actor_id: Mapped[str] = mapped_column(String(200))
    operation_type: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(30))
    correlation_id: Mapped[str] = mapped_column(String(100), index=True)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    error: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
