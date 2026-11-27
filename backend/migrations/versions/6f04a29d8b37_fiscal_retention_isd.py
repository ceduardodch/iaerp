"""Reconocer el ISD como impuesto independiente en las retenciones."""

from alembic import op

revision = "6f04a29d8b37"  # pragma: allowlist secret -- Alembic revision ID
down_revision = "b43a137c928f"  # pragma: allowlist secret -- Alembic revision ID
branch_labels = None
depends_on = None


def upgrade() -> None:
    # La migración fundacional aplicó dos veces el prefijo de la convención;
    # las bases inicializadas desde el modelo llevan el nombre corto.
    op.execute(
        "ALTER TABLE fiscal_retentions "
        "DROP CONSTRAINT IF EXISTS ck_fiscal_retentions_ck_fiscal_retentions_kind_valid, "
        "DROP CONSTRAINT IF EXISTS ck_fiscal_retentions_kind_valid, "
        "ADD CONSTRAINT ck_fiscal_retentions_kind_valid CHECK (kind IN ('IVA', 'RENTA', 'ISD'))"
    )


def downgrade() -> None:
    op.execute(
        """DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM fiscal_retentions WHERE kind = 'ISD') THEN
                RAISE EXCEPTION 'Existen retenciones ISD. No se puede revertir la migración.';
            END IF;
        END $$"""
    )
    op.execute(
        "ALTER TABLE fiscal_retentions "
        "DROP CONSTRAINT ck_fiscal_retentions_kind_valid, "
        "ADD CONSTRAINT ck_fiscal_retentions_ck_fiscal_retentions_kind_valid "
        "CHECK (kind IN ('IVA', 'RENTA'))"
    )
