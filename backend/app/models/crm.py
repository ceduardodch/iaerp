import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.masters import Party, Product, TenantEntityMixin
from app.models.platform import User


class LeadStatus(StrEnum):
    """Estados del pipeline de ventas."""

    NEW = "NEW"
    CONTACTED = "CONTACTED"
    QUALIFIED = "QUALIFIED"
    PROPOSAL = "PROPOSAL"
    NEGOTIATION = "NEGOTIATION"
    WON = "WON"
    LOST = "LOST"


class Lead(UUIDPrimaryKeyMixin, TimestampMixin, TenantEntityMixin, Base):
    """Prospecto principal del CRM."""

    __tablename__ = "crm_leads"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "party_id"],
            ["parties.tenant_id", "parties.id"],
            name="fk_crm_leads_tenant_party",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "product_id"],
            ["products.tenant_id", "products.id"],
            name="fk_crm_leads_tenant_product",
        ),
        CheckConstraint("hotness IN ('COLD', 'WARM', 'HOT')", name="hotness_valid"),
        CheckConstraint("score >= 0", name="score_non_negative"),
        CheckConstraint("score <= 100", name="score_max_100"),
        CheckConstraint(
            "status IN ('NEW', 'CONTACTED', 'QUALIFIED', 'PROPOSAL', 'NEGOTIATION', 'WON', 'LOST')",
            name="status_valid",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_crm_leads_tenant_id"),
        Index("ix_crm_leads_tenant_status", "tenant_id", "status"),
        Index("ix_crm_leads_tenant_owner", "tenant_id", "owner_user_id"),
    )

    party_id: Mapped[uuid.UUID]
    title: Mapped[str] = mapped_column(String(200))
    product_id: Mapped[uuid.UUID | None]
    status: Mapped[LeadStatus] = mapped_column(String(20), default=LeadStatus.NEW)
    source: Mapped[str | None] = mapped_column(String(50))
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    score: Mapped[int] = mapped_column(default=0)
    hotness: Mapped[Literal["COLD", "WARM", "HOT"]] = mapped_column(String(10), default="COLD")
    estimated_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    expected_close_date: Mapped[date | None]

    # Relaciones
    party: Mapped[Party] = relationship(lazy="joined")
    product: Mapped["Product | None"] = relationship(lazy="joined", overlaps="party")
    owner: Mapped[User | None] = relationship(lazy="joined")
    activities: Mapped[list["LeadActivity"]] = relationship(
        back_populates="lead", cascade="all, delete-orphan"
    )


class LeadActivity(UUIDPrimaryKeyMixin, TimestampMixin, TenantEntityMixin, Base):
    """Actividades y seguimientos realizados sobre un lead."""

    __tablename__ = "crm_activities"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "lead_id"],
            ["crm_leads.tenant_id", "crm_leads.id"],
            name="fk_crm_activities_tenant_lead",
        ),
        CheckConstraint(
            "activity_type IN ('CALL', 'EMAIL', 'WHATSAPP', 'MEETING', 'NOTE', 'TASK')",
            name="activity_type_valid",
        ),
        CheckConstraint(
            "outcome IN ('POSITIVE', 'NEUTRAL', 'NEGATIVE', 'PENDING')",
            name="outcome_valid",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_crm_activities_tenant_id"),
        Index("ix_crm_activities_tenant_lead", "tenant_id", "lead_id"),
        Index("ix_crm_activities_tenant_date", "tenant_id", "created_at"),
    )

    lead_id: Mapped[uuid.UUID]
    activity_type: Mapped[Literal["CALL", "EMAIL", "WHATSAPP", "MEETING", "NOTE", "TASK"]] = (
        mapped_column(String(20))
    )
    subject: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    outcome: Mapped[Literal["POSITIVE", "NEUTRAL", "NEGATIVE", "PENDING"]] = mapped_column(
        String(20)
    )
    reminder_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reminder_completed: Mapped[bool] = mapped_column(default=False)

    # Integración Gmail
    source_email_id: Mapped[str | None] = mapped_column(String(100))
    source_email_thread_id: Mapped[str | None] = mapped_column(String(100))

    actor_id: Mapped[str] = mapped_column(String(200))

    # Relaciones
    lead: Mapped["Lead"] = relationship(back_populates="activities")


class GmailIntegration(UUIDPrimaryKeyMixin, TimestampMixin, TenantEntityMixin, Base):
    """Configuración de integración Gmail por tenant y usuario."""

    __tablename__ = "crm_gmail_integrations"
    __table_args__ = (UniqueConstraint("tenant_id", "user_id", name="uq_crm_gmail_tenant_user"),)

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    email: Mapped[str | None] = mapped_column(String(320))
    access_token: Mapped[str | None] = mapped_column(Text)
    refresh_token: Mapped[str | None] = mapped_column(Text)
    access_token_encrypted: Mapped[str | None] = mapped_column(Text)
    refresh_token_encrypted: Mapped[str | None] = mapped_column(Text)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scopes_granted: Mapped[list[str]] = mapped_column(JSON)
    sync_enabled: Mapped[bool] = mapped_column(default=False)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sync_labels: Mapped[list[str] | None] = mapped_column(JSON)
    active: Mapped[bool] = mapped_column(default=True)


class WhatsAppIntegration(UUIDPrimaryKeyMixin, TimestampMixin, TenantEntityMixin, Base):
    __tablename__ = "crm_whatsapp_integrations"
    __table_args__ = (UniqueConstraint("tenant_id", name="uq_crm_whatsapp_tenant"),)

    business_account_id: Mapped[str] = mapped_column(String(100))
    phone_number_id: Mapped[str] = mapped_column(String(100))
    display_phone_number: Mapped[str | None] = mapped_column(String(40))
    access_token_encrypted: Mapped[str] = mapped_column(Text)
    app_secret_encrypted: Mapped[str] = mapped_column(Text)
    verify_token_encrypted: Mapped[str] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(default=True)
