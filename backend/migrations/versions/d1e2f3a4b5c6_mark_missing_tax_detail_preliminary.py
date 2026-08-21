"""mark fiscal documents without tax detail as preliminary

Revision ID: d1e2f3a4b5c6
Revises: d0e1f2a3b4c5
"""

from collections.abc import Sequence

from alembic import op

revision: str = "d1e2f3a4b5c6"  # pragma: allowlist secret -- Alembic revision ID
down_revision: str | None = "d0e1f2a3b4c5"  # pragma: allowlist secret -- Alembic revision ID
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_MISSING_TAX_DETAIL = """
    SELECT 1
    FROM fiscal_document_taxes AS tax
    WHERE tax.tenant_id = document.tenant_id
      AND tax.fiscal_document_id = document.id
"""


def upgrade() -> None:
    op.execute(
        f"""
        UPDATE fiscal_documents AS document
        SET is_preliminary = true
        WHERE document.doc_type IN (
            'FACTURA', 'NOTA_CREDITO', 'NOTA_DEBITO', 'LIQUIDACION'
        )
          AND NOT EXISTS ({_MISSING_TAX_DETAIL})
        """
    )
    op.execute(
        """
        UPDATE payables AS payable
        SET evidence_status = 'PRELIMINARY'
        FROM fiscal_documents AS document
        WHERE payable.tenant_id = document.tenant_id
          AND payable.fiscal_document_id = document.id
          AND document.is_preliminary = true
          AND document.doc_type IN (
              'FACTURA', 'NOTA_CREDITO', 'NOTA_DEBITO', 'LIQUIDACION'
          )
        """
    )
    op.execute(
        """
        UPDATE tax_periods AS period
        SET status = 'EVIDENCIA_INCOMPLETA'
        WHERE period.status <> 'DECLARADO'
          AND EXISTS (
              SELECT 1
              FROM fiscal_documents AS document
              WHERE document.tenant_id = period.tenant_id
                AND document.tax_period_id = period.id
                AND document.is_preliminary = true
          )
        """
    )
    op.execute(
        """
        UPDATE tax_tasks AS task
        SET status = 'DESCARTADO'
        FROM tax_periods AS period
        WHERE task.tenant_id = period.tenant_id
          AND task.tax_period_id = period.id
          AND period.status = 'EVIDENCIA_INCOMPLETA'
          AND task.task_type IN ('REVISAR_IVA', 'PREPARAR_ATS')
          AND task.status IN ('PENDIENTE', 'EN_PROCESO')
        """
    )


def downgrade() -> None:
    # No se vuelve a declarar completo un comprobante que carece de desglose:
    # el estado anterior era una clasificación incorrecta, no información útil.
    pass
