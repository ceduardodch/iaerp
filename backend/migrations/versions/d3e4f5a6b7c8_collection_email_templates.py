"""store tenant collection email templates and payment instructions

Revision ID: d3e4f5a6b7c8
Revises: c2d3e4f5a6b7
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d3e4f5a6b7c8"  # pragma: allowlist secret
down_revision: str | None = "c2d3e4f5a6b7"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DEFAULT_SUBJECT = "Recordatorio de pago - {{empresa}}"
_DEFAULT_BODY = (
    "Estimado/a {{cliente}},\n\n"
    "Le recordamos que mantiene un saldo pendiente. "
    "Revise el detalle y realice el pago hasta {{vencimiento}}."
)


def upgrade() -> None:
    op.add_column(
        "collection_policies",
        sa.Column(
            "email_subject", sa.String(length=200), nullable=False, server_default=_DEFAULT_SUBJECT
        ),
    )
    op.add_column(
        "collection_policies",
        sa.Column(
            "email_body", sa.String(length=5000), nullable=False, server_default=_DEFAULT_BODY
        ),
    )
    op.add_column(
        "collection_policies",
        sa.Column(
            "payment_instructions", sa.String(length=1500), nullable=False, server_default=""
        ),
    )
    op.alter_column("collection_policies", "email_subject", server_default=None)
    op.alter_column("collection_policies", "email_body", server_default=None)
    op.alter_column("collection_policies", "payment_instructions", server_default=None)


def downgrade() -> None:
    op.drop_column("collection_policies", "payment_instructions")
    op.drop_column("collection_policies", "email_body")
    op.drop_column("collection_policies", "email_subject")
