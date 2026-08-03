"""Add the tenant invoice delivery email template.

Revision ID: b7c8d9e0f1a2
Revises: a6b7c8d9e0f1
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b7c8d9e0f1a2"  # pragma: allowlist secret -- Alembic revision ID
down_revision: str | None = "a6b7c8d9e0f1"  # pragma: allowlist secret -- Alembic revision ID
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DEFAULT_SUBJECT = "Factura {{numero_factura}} · {{empresa}}"
DEFAULT_BODY = (
    "Hola {{cliente}},\n\n"
    "Adjuntamos la factura {{numero_factura}}, su RIDE en PDF y el XML firmado.\n\n"
    "Fecha de emisión: {{fecha_emision}}\n"
    "Fecha límite de pago: {{vencimiento}}\n"
    "Plazo acordado: {{plazo}}\n"
    "Total: ${{total}}\n\n"
    "Nota de pago: por favor realiza el pago hasta la fecha indicada."
)


def upgrade() -> None:
    op.add_column(
        "tenant_fiscal_settings",
        sa.Column(
            "invoice_email_subject",
            sa.String(length=500),
            nullable=False,
            server_default=DEFAULT_SUBJECT,
        ),
    )
    op.add_column(
        "tenant_fiscal_settings",
        sa.Column("invoice_email_body", sa.Text(), nullable=False, server_default=DEFAULT_BODY),
    )


def downgrade() -> None:
    op.drop_column("tenant_fiscal_settings", "invoice_email_body")
    op.drop_column("tenant_fiscal_settings", "invoice_email_subject")
