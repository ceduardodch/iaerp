"""sales_documents: campos de anulacion (reconciliacion con el SRI)

Revision ID: c7d8e9f0a1b2
Revises: b6c7d8e9f0a1
Create Date: 2026-09-10 09:00:00.000000

El estado ``VOIDED`` ("Anulada") ya existia en el enum del dominio pero nunca
tuvo transicion. Cuando el contribuyente anula un comprobante directamente en
el portal del SRI (acto externo sobre una factura ya AUTHORIZED), IAERP tiene
que poder reflejar ese estado para reconciliar. Estos dos campos guardan el
motivo declarado y el momento de la reconciliacion, en paralelo a los
``archived_*`` ya existentes. La clave de acceso, el actor y el momento quedan
ademas en el AuditEvent de la operacion; ni el XML firmado ni el RIDE se tocan.

Ambas columnas son nullable y sin default: agregar una columna nullable en
PostgreSQL no reescribe la tabla ni bloquea; ningun dato existente cambia. El
downgrade solo las elimina.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c7d8e9f0a1b2"  # pragma: allowlist secret -- Alembic revision ID
down_revision: str | None = "b6c7d8e9f0a1"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "sales_documents",
        sa.Column("voided_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "sales_documents",
        sa.Column("voided_reason", sa.String(length=500), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("sales_documents", "voided_reason")
    op.drop_column("sales_documents", "voided_at")
