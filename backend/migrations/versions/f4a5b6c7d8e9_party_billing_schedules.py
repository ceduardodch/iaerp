"""party billing schedules: que dia hay que facturarle a cada cliente

Revision ID: f4a5b6c7d8e9
Revises: e3f4a5b6c7d8
Create Date: 2026-09-02 19:00:00.000000

F3 del modulo de avisos. Es el dato que faltaba para ``CLIENTE_FACTURAR``:
``CommercialContract.service_type`` ya decia ``FIXED_MONTHLY`` pero no que dia
del mes, asi que "a este se le factura el 1 y a aquel el 10" no existia en
ninguna tabla.

Tabla nueva, sin backfill: no hay forma de deducir el dia de facturacion de un
cliente a partir de sus facturas pasadas sin adivinar. Lo carga una persona.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f4a5b6c7d8e9"  # pragma: allowlist secret -- Alembic revision ID
down_revision: str | None = "e3f4a5b6c7d8"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "party_billing_schedules",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("party_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("contract_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("day_of_month", sa.Integer(), nullable=False),
        sa.Column("frequency", sa.String(length=20), nullable=False),
        sa.Column("anchor_month", sa.Integer(), nullable=True),
        sa.Column("amount_hint", sa.Numeric(18, 2), nullable=True),
        sa.Column("notes", sa.String(length=500), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "day_of_month BETWEEN 1 AND 31",
            name="ck_party_billing_schedules_day_of_month_valid",
        ),
        sa.CheckConstraint(
            "frequency IN ('MONTHLY', 'BIMONTHLY', 'QUARTERLY', 'ANNUAL')",
            name="ck_party_billing_schedules_frequency_valid",
        ),
        sa.CheckConstraint(
            "frequency = 'MONTHLY' OR anchor_month IS NOT NULL",
            name="ck_party_billing_schedules_anchor_month_required",
        ),
        sa.CheckConstraint(
            "anchor_month IS NULL OR anchor_month BETWEEN 1 AND 12",
            name="ck_party_billing_schedules_anchor_month_valid",
        ),
        sa.CheckConstraint(
            "amount_hint IS NULL OR amount_hint >= 0",
            name="ck_party_billing_schedules_amount_hint_non_negative",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_party_billing_schedules_tenant_id_tenants",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "party_id"],
            ["parties.tenant_id", "parties.id"],
            name="fk_party_billing_schedules_tenant_party",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "contract_id"],
            ["commercial_contracts.tenant_id", "commercial_contracts.id"],
            name="fk_party_billing_schedules_tenant_contract",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_party_billing_schedules"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_party_billing_schedules_tenant_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "party_id",
            "day_of_month",
            "frequency",
            name="uq_party_billing_schedules_party_day_frequency",
        ),
    )
    op.create_index(
        "ix_party_billing_schedules_tenant_id", "party_billing_schedules", ["tenant_id"]
    )
    op.create_index(
        "ix_party_billing_schedules_tenant_active",
        "party_billing_schedules",
        ["tenant_id", "active"],
    )


def downgrade() -> None:
    op.drop_table("party_billing_schedules")
