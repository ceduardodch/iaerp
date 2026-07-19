import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.masters import Party, TenantEntityMixin
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
        UniqueConstraint("tenant_id", "id", name="uq_leads_tenant_id"),
        Index("ix_leads_tenant_status", "tenant_id", "status"),
        Index("ix_leads_tenant_owner", "tenant_id", "owner_user_id"),
    )

    party_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("parties.id"))
    status: Mapped[LeadStatus] = mapped_column(String(20), default=LeadStatus.NEW)
    source: Mapped[str | None] = mapped_column(String(50))
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    score: Mapped[int] = mapped_column(default=0)
    hotness: Mapped[Literal["COLD", "WARM", "HOT"]] = mapped_column(String(10), default="COLD")
    estimated_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    expected_close_date: Mapped[date | None]

    # Relaciones
    party: Mapped[Party] = relationship(lazy="joined")
    owner: Mapped[User] = relationship(lazy="joined")
    activities: Mapped[list["LeadActivity"]] = relationship(
        back_populates="lead", cascade="all, delete-orphan"
    )


class LeadActivity(UUIDPrimaryKeyMixin, TimestampMixin, TenantEntityMixin, Base):
    """Actividades y seguimientos realizados sobre un lead."""
    __tablename__ = "crm_activities"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_activities_tenant_id"),
        Index("ix_activities_tenant_lead", "tenant_id", "lead_id"),
        Index("ix_activities_tenant_date", "tenant_id", "created_at"),
    )

    lead_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("crm_leads.id"))
    activity_type: Mapped[Literal["CALL", "EMAIL", "MEETING", "NOTE", "TASK"]] = mapped_column(
        String(20)
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
    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id", name="uq_gmail_tenant_user"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    access_token: Mapped[str] = mapped_column(Text)
    refresh_token: Mapped[str] = mapped_column(Text)
    token_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    scopes_granted: Mapped[list[str]] = mapped_column(JSON)
    sync_enabled: Mapped[bool] = mapped_column(default=False)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sync_labels: Mapped[list[str] | None] = mapped_column(JSON)
    active: Mapped[bool] = mapped_column(default=True)
