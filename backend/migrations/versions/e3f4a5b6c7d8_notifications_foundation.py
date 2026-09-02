"""notifications foundation: rules, templates, events and deliveries

Revision ID: e3f4a5b6c7d8
Revises: d2e3f4a5b6c7
Create Date: 2026-09-02 18:00:00.000000

F1 del modulo de avisos internos (``docs/NOTIFICATIONS_MODULE_PLAN.md``). Crea
el esquema completo aunque solo IVA_DECLARACION este implementado todavia: es
mas barato que agregar columnas despues sobre tablas con filas.

La restriccion que sostiene el modulo es
``uq_notification_events_tenant_dedupe_key``: sin ella, el planificador -- que
corre en bucle -- programaria el mismo aviso una vez por vuelta.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e3f4a5b6c7d8"  # pragma: allowlist secret -- Alembic revision ID
down_revision: str | None = "d2e3f4a5b6c7"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


RULE_TYPES_SQL = (
    "'CLIENTE_FACTURAR', 'IVA_DECLARACION', 'IVA_PREVIEW_MENSUAL', "
    "'RESUMEN_MENSUAL', 'IESS_APORTE', 'NOMINA_ROL', 'CARTERA_VENCIDA', "
    "'CXP_PROXIMO_PAGO', 'RENOVACION_CONTRATO', 'SRI_RECHAZO', "
    "'EVIDENCIA_INCOMPLETA'"
)


def _timestamp_columns() -> list[sa.Column[sa.DateTime]]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "notification_channel_accounts",
        sa.Column("tenant_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(length=20), nullable=False),
        sa.Column("api_key_vault_ref", sa.String(length=200), nullable=True),
        sa.Column("sender_email", sa.String(length=320), nullable=True),
        sa.Column("sender_name", sa.String(length=200), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(length=1000), nullable=True),
        *_timestamp_columns(),
        sa.CheckConstraint(
            "provider IN ('STUB', 'BREVO')",
            name="ck_notification_channel_accounts_provider_valid",
        ),
        sa.CheckConstraint(
            "status IN ('NOT_CONFIGURED', 'PENDING_VERIFICATION', 'ACTIVE', 'ERROR')",
            name="ck_notification_channel_accounts_status_valid",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_notification_channel_accounts_tenant_id_tenants",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("tenant_id", name="pk_notification_channel_accounts"),
    )

    op.create_table(
        "notification_rules",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("rule_type", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("schedule_kind", sa.String(length=30), nullable=False),
        sa.Column("days_of_month", sa.String(length=100), nullable=True),
        sa.Column("offsets_days", sa.String(length=100), nullable=True),
        sa.Column("send_hour", sa.Integer(), nullable=False),
        sa.Column("channels", sa.String(length=100), nullable=False),
        sa.Column("audience_kind", sa.String(length=30), nullable=False),
        sa.Column("audience_roles", sa.JSON(), nullable=False),
        sa.Column("audience_emails", sa.JSON(), nullable=False),
        sa.Column("params", sa.JSON(), nullable=False),
        sa.Column("require_ack", sa.Boolean(), nullable=False),
        *_timestamp_columns(),
        sa.CheckConstraint(
            f"rule_type IN ({RULE_TYPES_SQL})",
            name="ck_notification_rules_rule_type_valid",
        ),
        sa.CheckConstraint(
            "schedule_kind IN ('DAY_OF_MONTH', 'OFFSET_TO_DUE', "
            "'LAST_BUSINESS_DAY', 'WEEKDAY')",
            name="ck_notification_rules_schedule_kind_valid",
        ),
        sa.CheckConstraint(
            "audience_kind IN ('TENANT_USERS', 'EXPLICIT_EMAILS', 'PARTY')",
            name="ck_notification_rules_audience_kind_valid",
        ),
        sa.CheckConstraint(
            "send_hour BETWEEN 0 AND 23",
            name="ck_notification_rules_send_hour_valid",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_notification_rules_tenant_id_tenants"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_notification_rules"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_notification_rules_tenant_id"),
    )
    op.create_index("ix_notification_rules_tenant_id", "notification_rules", ["tenant_id"])
    op.create_index(
        "ix_notification_rules_tenant_enabled",
        "notification_rules",
        ["tenant_id", "enabled"],
    )

    op.create_table(
        "notification_templates",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("rule_type", sa.String(length=40), nullable=False),
        sa.Column("subject", sa.String(length=300), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        *_timestamp_columns(),
        sa.CheckConstraint(
            f"rule_type IN ({RULE_TYPES_SQL})",
            name="ck_notification_templates_rule_type_valid",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_notification_templates_tenant_id_tenants"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_notification_templates"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_notification_templates_tenant_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "rule_type",
            name="uq_notification_templates_tenant_rule_type",
        ),
    )
    op.create_index("ix_notification_templates_tenant_id", "notification_templates", ["tenant_id"])

    op.create_table(
        "notification_events",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("rule_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("rule_type", sa.String(length=40), nullable=False),
        sa.Column("dedupe_key", sa.String(length=200), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("error_message", sa.String(length=1000), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ack_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ack_by", sa.String(length=200), nullable=True),
        *_timestamp_columns(),
        sa.CheckConstraint(
            f"rule_type IN ({RULE_TYPES_SQL})",
            name="ck_notification_events_rule_type_valid",
        ),
        sa.CheckConstraint(
            "status IN ('PENDING', 'PROCESSING', 'SENT', 'STUBBED', 'SKIPPED', "
            "'FAILED', 'CANCELLED')",
            name="ck_notification_events_status_valid",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_notification_events_tenant_id_tenants"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "rule_id"],
            ["notification_rules.tenant_id", "notification_rules.id"],
            name="fk_notification_events_tenant_rule",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_notification_events"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_notification_events_tenant_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "dedupe_key",
            name="uq_notification_events_tenant_dedupe_key",
        ),
    )
    op.create_index("ix_notification_events_tenant_id", "notification_events", ["tenant_id"])
    op.create_index(
        "ix_notification_events_due",
        "notification_events",
        ["tenant_id", "status", "scheduled_at"],
    )

    op.create_table(
        "notification_deliveries",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("event_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("channel", sa.String(length=20), nullable=False),
        sa.Column("recipient", sa.String(length=320), nullable=False),
        sa.Column("provider", sa.String(length=20), nullable=False),
        sa.Column("provider_message_id", sa.String(length=200), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("error_message", sa.String(length=1000), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamp_columns(),
        sa.CheckConstraint(
            "status IN ('PENDING', 'STUBBED', 'SENT', 'FAILED', 'BOUNCED', 'COMPLAINED')",
            name="ck_notification_deliveries_status_valid",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_notification_deliveries_tenant_id_tenants"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "event_id"],
            ["notification_events.tenant_id", "notification_events.id"],
            name="fk_notification_deliveries_tenant_event",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_notification_deliveries"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_notification_deliveries_tenant_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "event_id",
            "recipient",
            name="uq_notification_deliveries_event_recipient",
        ),
    )
    op.create_index(
        "ix_notification_deliveries_tenant_id", "notification_deliveries", ["tenant_id"]
    )
    op.create_index(
        "ix_notification_deliveries_tenant_event",
        "notification_deliveries",
        ["tenant_id", "event_id"],
    )


def downgrade() -> None:
    op.drop_table("notification_deliveries")
    op.drop_table("notification_events")
    op.drop_table("notification_templates")
    op.drop_table("notification_rules")
    op.drop_table("notification_channel_accounts")
