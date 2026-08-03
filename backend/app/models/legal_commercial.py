"""Tenant-scoped legal-commercial dossier entities.

These records establish commercial traceability only. They intentionally do
not alter SRI document lifecycle or receivable balances.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.masters import TenantEntityMixin


class CommercialContract(UUIDPrimaryKeyMixin, TimestampMixin, TenantEntityMixin, Base):
    __tablename__ = "commercial_contracts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "party_id"],
            ["parties.tenant_id", "parties.id"],
            name="fk_commercial_contracts_tenant_party",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "source_lead_id"],
            ["crm_leads.tenant_id", "crm_leads.id"],
            name="fk_commercial_contracts_tenant_lead",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "parent_contract_id"],
            ["commercial_contracts.tenant_id", "commercial_contracts.id"],
            name="fk_commercial_contracts_tenant_parent",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_commercial_contracts_tenant_id"),
        UniqueConstraint(
            "tenant_id", "contract_number", name="uq_commercial_contracts_tenant_number"
        ),
        Index("ix_commercial_contracts_tenant_party", "tenant_id", "party_id"),
    )

    party_id: Mapped[uuid.UUID]
    source_lead_id: Mapped[uuid.UUID | None]
    parent_contract_id: Mapped[uuid.UUID | None]
    contract_number: Mapped[str] = mapped_column(String(80))
    title: Mapped[str] = mapped_column(String(200))
    service_type: Mapped[str] = mapped_column(String(30), default="FIXED_MONTHLY")
    report_required: Mapped[bool] = mapped_column(Boolean, default=False)
    collection_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(30), default="DRAFT")
    current_version_id: Mapped[uuid.UUID | None]


class ContractVersion(UUIDPrimaryKeyMixin, TimestampMixin, TenantEntityMixin, Base):
    __tablename__ = "commercial_contract_versions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "contract_id"],
            ["commercial_contracts.tenant_id", "commercial_contracts.id"],
            name="fk_contract_versions_tenant_contract",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "amends_version_id"],
            ["commercial_contract_versions.tenant_id", "commercial_contract_versions.id"],
            name="fk_contract_versions_tenant_amendment",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_contract_versions_tenant_id"),
        UniqueConstraint(
            "tenant_id",
            "contract_id",
            "version_number",
            name="uq_contract_versions_tenant_contract_number",
        ),
        CheckConstraint(
            "payment_terms_days >= 0", name="ck_contract_versions_payment_terms_nonnegative"
        ),
        Index("ix_contract_versions_tenant_contract", "tenant_id", "contract_id"),
    )

    contract_id: Mapped[uuid.UUID]
    version_number: Mapped[int]
    status: Mapped[str] = mapped_column(String(30), default="DRAFT")
    valid_from: Mapped[date] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    signed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    signers: Mapped[list[dict[str, str]]] = mapped_column(JSON, default=list)
    payment_terms_days: Mapped[int] = mapped_column(default=0)
    renewal_notice_days: Mapped[int | None]
    pricing_rules: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    sent_artifact_object_key: Mapped[str | None] = mapped_column(String(500))
    sent_artifact_sha256: Mapped[str | None] = mapped_column(String(64))
    sent_artifact_file_name: Mapped[str | None] = mapped_column(String(255))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    gmail_message_id: Mapped[str | None] = mapped_column(String(100))
    gmail_thread_id: Mapped[str | None] = mapped_column(String(100))
    reply_detected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reply_message_id: Mapped[str | None] = mapped_column(String(100))
    signed_artifact_object_key: Mapped[str | None] = mapped_column(String(500))
    signed_artifact_sha256: Mapped[str | None] = mapped_column(String(64))
    signed_artifact_file_name: Mapped[str | None] = mapped_column(String(255))
    signature_precheck_status: Mapped[str | None] = mapped_column(String(30))
    signature_precheck_details: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    firmaec_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    firmaec_confirmed_by: Mapped[str | None] = mapped_column(String(200))
    amends_version_id: Mapped[uuid.UUID | None]


class AwsConsumptionCut(UUIDPrimaryKeyMixin, TimestampMixin, TenantEntityMixin, Base):
    __tablename__ = "aws_consumption_cuts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "party_id"],
            ["parties.tenant_id", "parties.id"],
            name="fk_aws_cuts_tenant_party",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_aws_cuts_tenant_id"),
        UniqueConstraint(
            "tenant_id",
            "party_id",
            "period_start",
            "period_end",
            name="uq_aws_cuts_tenant_party_period",
        ),
        CheckConstraint("total_cost >= 0", name="ck_aws_cuts_total_nonnegative"),
        Index("ix_aws_cuts_tenant_party", "tenant_id", "party_id"),
    )

    party_id: Mapped[uuid.UUID]
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    source: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(30), default="IMPORTED")
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    total_cost: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    evidence_object_key: Mapped[str | None] = mapped_column(String(500))
    evidence_sha256: Mapped[str | None] = mapped_column(String(64))
    reconciliation_summary: Mapped[dict[str, Any] | None] = mapped_column(JSON)


class BillingProposal(UUIDPrimaryKeyMixin, TimestampMixin, TenantEntityMixin, Base):
    __tablename__ = "commercial_billing_proposals"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "party_id"],
            ["parties.tenant_id", "parties.id"],
            name="fk_billing_proposals_tenant_party",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "contract_version_id"],
            ["commercial_contract_versions.tenant_id", "commercial_contract_versions.id"],
            name="fk_billing_proposals_tenant_contract_version",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "aws_consumption_cut_id"],
            ["aws_consumption_cuts.tenant_id", "aws_consumption_cuts.id"],
            name="fk_billing_proposals_tenant_cut",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "sales_document_id"],
            ["sales_documents.tenant_id", "sales_documents.id"],
            name="fk_billing_proposals_tenant_sales_document",
        ),
        CheckConstraint("total_amount >= 0", name="ck_billing_proposals_total_nonnegative"),
        UniqueConstraint(
            "tenant_id",
            "sales_document_id",
            name="uq_billing_proposals_tenant_sales_document",
        ),
        Index("ix_billing_proposals_tenant_party", "tenant_id", "party_id"),
    )

    party_id: Mapped[uuid.UUID]
    contract_version_id: Mapped[uuid.UUID | None]
    aws_consumption_cut_id: Mapped[uuid.UUID | None]
    sales_document_id: Mapped[uuid.UUID | None]
    issue_date: Mapped[date] = mapped_column(Date)
    period_start: Mapped[date | None] = mapped_column(Date)
    period_end: Mapped[date | None] = mapped_column(Date)
    pricing_rule_index: Mapped[int] = mapped_column(Integer, default=0)
    billing_type: Mapped[str] = mapped_column(String(30), default="ONE_OFF")
    status: Mapped[str] = mapped_column(String(30), default="DRAFT")
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    total_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    commercial_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON)
    exception_reason: Mapped[str | None] = mapped_column(Text)
    report_required: Mapped[bool] = mapped_column(Boolean, default=False)
    collection_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    report_object_key: Mapped[str | None] = mapped_column(String(500))
    report_sha256: Mapped[str | None] = mapped_column(String(64))
    report_file_name: Mapped[str | None] = mapped_column(String(255))
    report_approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    report_approved_by: Mapped[str | None] = mapped_column(String(200))
