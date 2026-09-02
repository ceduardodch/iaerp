"""notification channel accounts: reply-to del tenant

Revision ID: a5b6c7d8e9f0
Revises: f4a5b6c7d8e9
Create Date: 2026-09-02 21:30:00.000000

F2 del modulo de avisos. Con una sola cuenta Brevo de plataforma, el ``From``
sale del dominio verificado de IAERP (el unico autenticado con SPF/DKIM) y el
``Reply-To`` es lo que devuelve la conversacion a la empresa correcta.

Columna nullable y sin backfill: sin valor, el correo simplemente no lleva
Reply-To, que es el comportamiento actual.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a5b6c7d8e9f0"  # pragma: allowlist secret -- Alembic revision ID
down_revision: str | None = "f4a5b6c7d8e9"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "notification_channel_accounts",
        sa.Column("reply_to", sa.String(length=320), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("notification_channel_accounts", "reply_to")
