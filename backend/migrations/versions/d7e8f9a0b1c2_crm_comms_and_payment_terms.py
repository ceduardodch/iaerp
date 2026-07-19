"""crm communications, payment terms and scheduled collections

Revision ID: d7e8f9a0b1c2
Revises: c4d5e6f7a8b9
"""

import base64
import hashlib
import os
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from cryptography.fernet import Fernet

revision: str = "d7e8f9a0b1c2"
down_revision: str | None = "c4d5e6f7a8b9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _token_cipher() -> Fernet:
    configured_key = os.getenv("IAERP_SECRETS_ENCRYPTION_KEY")
    if configured_key:
        key = configured_key.encode("ascii")
    elif os.getenv("APP_ENV", "development") in {"development", "test"}:
        secret = os.getenv("DEV_JWT_SECRET", "iaerp-dev-secret")
        key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())
    else:
        raise RuntimeError(
            "IAERP_SECRETS_ENCRYPTION_KEY is required to migrate legacy Gmail tokens"
        )
    return Fernet(key)


def _encrypt_legacy_gmail_tokens() -> None:
    connection = op.get_bind()
    cipher = _token_cipher()
    rows = connection.execute(
        sa.text(
            "SELECT id, access_token, refresh_token FROM crm_gmail_integrations "
            "WHERE access_token IS NOT NULL OR refresh_token IS NOT NULL"
        )
    ).mappings()
    for row in rows:
        access_token = row["access_token"]
        refresh_token = row["refresh_token"]
        if access_token and refresh_token:
            connection.execute(
                sa.text(
                    "UPDATE crm_gmail_integrations "
                    "SET access_token_encrypted = :access_encrypted, "
                    "refresh_token_encrypted = :refresh_encrypted, "
                    "access_token = NULL, refresh_token = NULL "
                    "WHERE id = :id"
                ),
                {
                    "id": row["id"],
                    "access_encrypted": cipher.encrypt(access_token.encode()).decode("ascii"),
                    "refresh_encrypted": cipher.encrypt(refresh_token.encode()).decode("ascii"),
                },
            )
        else:
            connection.execute(
                sa.text(
                    "UPDATE crm_gmail_integrations SET active = false, "
                    "access_token = NULL, refresh_token = NULL WHERE id = :id"
                ),
                {"id": row["id"]},
            )


def _restore_legacy_gmail_tokens() -> None:
    connection = op.get_bind()
    cipher = _token_cipher()
    rows = connection.execute(
        sa.text(
            "SELECT id, access_token_encrypted, refresh_token_encrypted "
            "FROM crm_gmail_integrations"
        )
    ).mappings()
    incomplete_ids: list[object] = []
    for row in rows:
        access_token = row["access_token_encrypted"]
        refresh_token = row["refresh_token_encrypted"]
        if not access_token or not refresh_token:
            incomplete_ids.append(row["id"])
            continue
        connection.execute(
            sa.text(
                "UPDATE crm_gmail_integrations SET access_token = :access_token, "
                "refresh_token = :refresh_token WHERE id = :id"
            ),
            {
                "id": row["id"],
                "access_token": cipher.decrypt(access_token.encode()).decode(),
                "refresh_token": cipher.decrypt(refresh_token.encode()).decode(),
            },
        )
    for integration_id in incomplete_ids:
        connection.execute(
            sa.text("DELETE FROM crm_gmail_integrations WHERE id = :id"),
            {"id": integration_id},
        )


def upgrade() -> None:
    op.add_column(
        "tenants",
        sa.Column("default_payment_terms_days", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("parties", sa.Column("payment_terms_days", sa.Integer(), nullable=True))
    op.create_check_constraint(
        "ck_tenants_payment_terms_days", "tenants", "default_payment_terms_days BETWEEN 0 AND 365"
    )
    op.create_check_constraint(
        "ck_parties_payment_terms_days",
        "parties",
        "payment_terms_days IS NULL OR payment_terms_days BETWEEN 0 AND 365",
    )

    op.add_column("crm_leads", sa.Column("title", sa.String(200), nullable=True))
    op.add_column("crm_leads", sa.Column("product_id", sa.Uuid(), nullable=True))
    op.execute("UPDATE crm_leads SET title = 'Oportunidad comercial' WHERE title IS NULL")
    op.alter_column("crm_leads", "title", nullable=False)
    op.create_foreign_key(
        "fk_crm_leads_tenant_product",
        "crm_leads",
        "products",
        ["tenant_id", "product_id"],
        ["tenant_id", "id"],
    )
    op.drop_constraint("ck_crm_activities_activity_type_valid", "crm_activities", type_="check")
    op.create_check_constraint(
        "ck_crm_activities_activity_type_valid",
        "crm_activities",
        "activity_type IN ('CALL','EMAIL','WHATSAPP','MEETING','NOTE','TASK')",
    )

    op.add_column("crm_gmail_integrations", sa.Column("email", sa.String(320), nullable=True))
    op.add_column(
        "crm_gmail_integrations", sa.Column("access_token_encrypted", sa.Text(), nullable=True)
    )
    op.add_column(
        "crm_gmail_integrations", sa.Column("refresh_token_encrypted", sa.Text(), nullable=True)
    )
    op.alter_column("crm_gmail_integrations", "access_token", nullable=True)
    op.alter_column("crm_gmail_integrations", "refresh_token", nullable=True)
    op.alter_column("crm_gmail_integrations", "token_expires_at", nullable=True)
    _encrypt_legacy_gmail_tokens()

    op.create_table(
        "crm_whatsapp_integrations",
        sa.Column("business_account_id", sa.String(100), nullable=False),
        sa.Column("phone_number_id", sa.String(100), nullable=False),
        sa.Column("display_phone_number", sa.String(40), nullable=True),
        sa.Column("access_token_encrypted", sa.Text(), nullable=False),
        sa.Column("app_secret_encrypted", sa.Text(), nullable=False),
        sa.Column("verify_token_encrypted", sa.Text(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", name="uq_crm_whatsapp_tenant"),
    )
    op.create_index(
        "ix_crm_whatsapp_integrations_tenant_id",
        "crm_whatsapp_integrations",
        ["tenant_id"],
    )

    op.create_table(
        "collection_policies",
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("offsets_days", sa.String(100), nullable=False, server_default="-3,0,3,7,15"),
        sa.Column("channels", sa.String(100), nullable=False, server_default="EMAIL"),
        sa.Column("send_hour", sa.Integer(), nullable=False, server_default="9"),
        sa.Column(
            "email_template_id", sa.String(100), nullable=False, server_default="payment_reminder"
        ),
        sa.Column(
            "whatsapp_template_id",
            sa.String(100),
            nullable=False,
            server_default="payment_reminder",
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )

    op.add_column("collection_reminders", sa.Column("receivable_id", sa.Uuid(), nullable=True))
    op.add_column("collection_reminders", sa.Column("installment_id", sa.Uuid(), nullable=True))
    op.add_column(
        "collection_reminders", sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "collection_reminders", sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "collection_reminders",
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "collection_reminders", sa.Column("error_message", sa.String(1000), nullable=True)
    )
    op.create_foreign_key(
        "fk_collection_reminders_tenant_receivable",
        "collection_reminders",
        "receivables",
        ["tenant_id", "receivable_id"],
        ["tenant_id", "id"],
    )
    op.create_foreign_key(
        "fk_collection_reminders_tenant_installment",
        "collection_reminders",
        "receivable_installments",
        ["tenant_id", "installment_id"],
        ["tenant_id", "id"],
    )
    op.drop_constraint(
        "ck_collection_reminders_status_valid", "collection_reminders", type_="check"
    )
    op.create_check_constraint(
        "ck_collection_reminders_status_valid",
        "collection_reminders",
        "status IN ('PENDING','PROCESSING','STUBBED','SENT','FAILED','SKIPPED')",
    )
    op.create_unique_constraint(
        "uq_collection_reminders_schedule",
        "collection_reminders",
        ["tenant_id", "installment_id", "channel", "scheduled_at"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_collection_reminders_schedule", "collection_reminders", type_="unique")
    op.drop_constraint(
        "fk_collection_reminders_tenant_installment", "collection_reminders", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_collection_reminders_tenant_receivable", "collection_reminders", type_="foreignkey"
    )
    op.drop_constraint(
        "ck_collection_reminders_status_valid", "collection_reminders", type_="check"
    )
    op.create_check_constraint(
        "ck_collection_reminders_status_valid",
        "collection_reminders",
        "status IN ('STUBBED','SENT','FAILED')",
    )
    for column in (
        "error_message",
        "attempts",
        "sent_at",
        "scheduled_at",
        "installment_id",
        "receivable_id",
    ):
        op.drop_column("collection_reminders", column)
    op.drop_table("collection_policies")
    op.drop_table("crm_whatsapp_integrations")
    _restore_legacy_gmail_tokens()
    for column in ("refresh_token_encrypted", "access_token_encrypted", "email"):
        op.drop_column("crm_gmail_integrations", column)
    op.alter_column("crm_gmail_integrations", "access_token", nullable=False)
    op.alter_column("crm_gmail_integrations", "refresh_token", nullable=False)
    op.alter_column("crm_gmail_integrations", "token_expires_at", nullable=False)
    op.drop_constraint("ck_crm_activities_activity_type_valid", "crm_activities", type_="check")
    op.create_check_constraint(
        "ck_crm_activities_activity_type_valid",
        "crm_activities",
        "activity_type IN ('CALL','EMAIL','MEETING','NOTE','TASK')",
    )
    op.drop_constraint("fk_crm_leads_tenant_product", "crm_leads", type_="foreignkey")
    op.drop_column("crm_leads", "product_id")
    op.drop_column("crm_leads", "title")
    op.drop_constraint("ck_parties_payment_terms_days", "parties", type_="check")
    op.drop_constraint("ck_tenants_payment_terms_days", "tenants", type_="check")
    op.drop_column("parties", "payment_terms_days")
    op.drop_column("tenants", "default_payment_terms_days")
