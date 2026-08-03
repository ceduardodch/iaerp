"""tax module foundation: evidence, periods and fiscal documents

Revision ID: e4f5a6b7c8d9
Revises: d3e4f5a6b7c8
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e4f5a6b7c8d9"  # pragma: allowlist secret
down_revision: str | None = "d3e4f5a6b7c8"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tenant_tax_profiles",
        sa.Column("tenant_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("alias", sa.String(length=120), nullable=True),
        sa.Column("person_type", sa.String(length=20), nullable=True),
        sa.Column("tax_regime", sa.String(length=60), nullable=True),
        sa.Column("obligations", sa.JSON(), nullable=False),
        sa.Column("vault_ref", sa.String(length=200), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_tenant_tax_profiles_tenant_id_tenants",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("tenant_id", name="pk_tenant_tax_profiles"),
    )

    op.create_table(
        "tax_periods",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("month", sa.Integer(), nullable=False),
        sa.Column("obligation_type", sa.String(length=10), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("month BETWEEN 1 AND 12", name="ck_tax_periods_month_valid"),
        sa.CheckConstraint("year BETWEEN 2000 AND 2100", name="ck_tax_periods_year_valid"),
        sa.CheckConstraint(
            "obligation_type IN ('IVA', 'ATS', 'RDEP', 'RENTA', 'ADI')",
            name="ck_tax_periods_obligation_type_valid",
        ),
        sa.CheckConstraint(
            "status IN ('PENDIENTE_DESCARGA', 'EVIDENCIA_INCOMPLETA', "
            "'LISTO_REVISAR', 'LISTO_DECLARAR', 'DECLARADO')",
            name="ck_tax_periods_status_valid",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_tax_periods_tenant_id_tenants"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_tax_periods"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_tax_periods_tenant_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "year",
            "month",
            "obligation_type",
            name="uq_tax_periods_tenant_year_month_obligation",
        ),
    )
    op.create_index("ix_tax_periods_tenant_id", "tax_periods", ["tenant_id"])
    op.create_index(
        "ix_tax_periods_tenant_year_month", "tax_periods", ["tenant_id", "year", "month"]
    )

    op.create_table(
        "tax_evidence",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("tax_period_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("file_type", sa.String(length=10), nullable=False),
        sa.Column("object_key", sa.Text(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("origin", sa.String(length=30), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processing_notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "file_type IN ('XML', 'TXT', 'PDF', 'ZIP', 'OTHER')",
            name="ck_tax_evidence_file_type_valid",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_tax_evidence_tenant_id_tenants"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_tax_evidence"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_tax_evidence_tenant_id"),
        sa.UniqueConstraint("tenant_id", "sha256", name="uq_tax_evidence_tenant_sha256"),
    )
    op.create_index("ix_tax_evidence_tenant_id", "tax_evidence", ["tenant_id"])
    op.create_index(
        "ix_tax_evidence_tenant_period", "tax_evidence", ["tenant_id", "tax_period_id"]
    )

    op.create_table(
        "fiscal_documents",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("tax_period_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("direction", sa.String(length=10), nullable=False),
        sa.Column("doc_type", sa.String(length=20), nullable=False),
        sa.Column("access_key", sa.String(length=49), nullable=True),
        sa.Column("authorization_number", sa.String(length=49), nullable=True),
        sa.Column("authorized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("issue_date", sa.Date(), nullable=False),
        sa.Column("establishment_code", sa.String(length=3), nullable=True),
        sa.Column("emission_point_code", sa.String(length=3), nullable=True),
        sa.Column("sequential", sa.String(length=9), nullable=True),
        sa.Column("counterparty_identification", sa.String(length=20), nullable=True),
        sa.Column("counterparty_name", sa.String(length=300), nullable=True),
        sa.Column("subtotal", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("tax_total", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("total", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("is_preliminary", sa.Boolean(), nullable=False),
        sa.Column("related_access_key", sa.String(length=49), nullable=True),
        sa.Column("sales_document_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("evidence_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "direction IN ('EMITIDO', 'RECIBIDO')", name="ck_fiscal_documents_direction_valid"
        ),
        sa.CheckConstraint(
            "doc_type IN ('FACTURA', 'NOTA_CREDITO', 'NOTA_DEBITO', "
            "'RETENCION', 'LIQUIDACION')",
            name="ck_fiscal_documents_doc_type_valid",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_fiscal_documents_tenant_id_tenants"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_fiscal_documents"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_fiscal_documents_tenant_id"),
        sa.UniqueConstraint(
            "tenant_id", "access_key", name="uq_fiscal_documents_tenant_access_key"
        ),
    )
    op.create_index("ix_fiscal_documents_tenant_id", "fiscal_documents", ["tenant_id"])
    op.create_index(
        "ix_fiscal_documents_tenant_issue_date",
        "fiscal_documents",
        ["tenant_id", "issue_date"],
    )
    op.create_index(
        "ix_fiscal_documents_tenant_period",
        "fiscal_documents",
        ["tenant_id", "tax_period_id"],
    )

    op.create_table(
        "fiscal_document_taxes",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("fiscal_document_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("sri_tax_code", sa.String(length=10), nullable=False),
        sa.Column("tax_bracket", sa.String(length=20), nullable=False),
        sa.Column("rate", sa.Numeric(precision=9, scale=6), nullable=False),
        sa.Column("base_amount", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("tax_amount", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.CheckConstraint(
            "tax_bracket IN ('GRAVADO', 'TARIFA_CERO', 'EXENTO', 'NO_OBJETO')",
            name="ck_fiscal_document_taxes_tax_bracket_valid",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "fiscal_document_id"],
            ["fiscal_documents.tenant_id", "fiscal_documents.id"],
            name="fk_fiscal_document_taxes_tenant_fiscal_document",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_fiscal_document_taxes_tenant_id_tenants"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_fiscal_document_taxes"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_fiscal_document_taxes_tenant_id"),
    )
    op.create_index("ix_fiscal_document_taxes_tenant_id", "fiscal_document_taxes", ["tenant_id"])
    op.create_index(
        "ix_fiscal_document_taxes_document",
        "fiscal_document_taxes",
        ["tenant_id", "fiscal_document_id"],
    )

    op.create_table(
        "fiscal_retentions",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("fiscal_document_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(length=10), nullable=False),
        sa.Column("sri_code", sa.String(length=10), nullable=False),
        sa.Column("percentage", sa.Numeric(precision=9, scale=4), nullable=False),
        sa.Column("base_amount", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("retained_amount", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("supporting_access_key", sa.String(length=49), nullable=True),
        sa.Column("supporting_document_number", sa.String(length=30), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("kind IN ('IVA', 'RENTA')", name="ck_fiscal_retentions_kind_valid"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "fiscal_document_id"],
            ["fiscal_documents.tenant_id", "fiscal_documents.id"],
            name="fk_fiscal_retentions_tenant_fiscal_document",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_fiscal_retentions_tenant_id_tenants"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_fiscal_retentions"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_fiscal_retentions_tenant_id"),
    )
    op.create_index("ix_fiscal_retentions_tenant_id", "fiscal_retentions", ["tenant_id"])
    op.create_index(
        "ix_fiscal_retentions_tenant_document",
        "fiscal_retentions",
        ["tenant_id", "fiscal_document_id"],
    )

    op.create_table(
        "tax_form_field_maps",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("form_code", sa.String(length=10), nullable=False),
        sa.Column("field_code", sa.String(length=10), nullable=False),
        sa.Column("label", sa.String(length=200), nullable=False),
        sa.Column("source_key", sa.String(length=60), nullable=False),
        sa.Column("is_paste", sa.Boolean(), nullable=False),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.Column("valid_to", sa.Date(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_tax_form_field_maps_tenant_id_tenants"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_tax_form_field_maps"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_tax_form_field_maps_tenant_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "form_code",
            "field_code",
            "valid_from",
            name="uq_tax_form_field_maps_tenant_form_field_valid",
        ),
    )
    op.create_index("ix_tax_form_field_maps_tenant_id", "tax_form_field_maps", ["tenant_id"])
    op.create_index(
        "ix_tax_form_field_maps_tenant_form", "tax_form_field_maps", ["tenant_id", "form_code"]
    )

    op.create_table(
        "tax_return_drafts",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("tax_period_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("form_code", sa.String(length=10), nullable=False),
        sa.Column("fields", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("observations", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "tax_period_id"],
            ["tax_periods.tenant_id", "tax_periods.id"],
            name="fk_tax_return_drafts_tenant_tax_period",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_tax_return_drafts_tenant_id_tenants"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_tax_return_drafts"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_tax_return_drafts_tenant_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "tax_period_id",
            "form_code",
            name="uq_tax_return_drafts_tenant_period_form",
        ),
    )
    op.create_index("ix_tax_return_drafts_tenant_id", "tax_return_drafts", ["tenant_id"])

    op.create_table(
        "tax_annexes",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("tax_period_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("annex_type", sa.String(length=10), nullable=False),
        sa.Column("xml_object_key", sa.Text(), nullable=True),
        sa.Column("zip_object_key", sa.Text(), nullable=True),
        sa.Column("xml_sha256", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "annex_type IN ('ATS', 'RDEP', 'ADI')", name="ck_tax_annexes_annex_type_valid"
        ),
        sa.CheckConstraint(
            "status IN ('GENERADO', 'VALIDADO', 'RECHAZADO', 'ENTREGADO')",
            name="ck_tax_annexes_status_valid",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "tax_period_id"],
            ["tax_periods.tenant_id", "tax_periods.id"],
            name="fk_tax_annexes_tenant_tax_period",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_tax_annexes_tenant_id_tenants"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_tax_annexes"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_tax_annexes_tenant_id"),
    )
    op.create_index("ix_tax_annexes_tenant_id", "tax_annexes", ["tenant_id"])
    op.create_index("ix_tax_annexes_tenant_period", "tax_annexes", ["tenant_id", "tax_period_id"])

    op.create_table(
        "sri_validation_issues",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("tax_annex_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("fiscal_document_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("severity", sa.String(length=20), nullable=False),
        sa.Column("line_number", sa.Integer(), nullable=True),
        sa.Column("column_number", sa.Integer(), nullable=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("suggested_fix", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "severity IN ('ERROR', 'ADVERTENCIA')", name="ck_sri_validation_issues_severity_valid"
        ),
        sa.CheckConstraint(
            "status IN ('PENDIENTE', 'CORREGIDO')", name="ck_sri_validation_issues_status_valid"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_sri_validation_issues_tenant_id_tenants"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_sri_validation_issues"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_sri_validation_issues_tenant_id"),
    )
    op.create_index("ix_sri_validation_issues_tenant_id", "sri_validation_issues", ["tenant_id"])
    op.create_index(
        "ix_sri_validation_issues_tenant_annex",
        "sri_validation_issues",
        ["tenant_id", "tax_annex_id"],
    )

    op.create_table(
        "tax_tasks",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("tax_period_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("task_type", sa.String(length=40), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("requires_approval", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "status IN ('PENDIENTE', 'EN_PROCESO', 'HECHO', 'DESCARTADO')",
            name="ck_tax_tasks_status_valid",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_tax_tasks_tenant_id_tenants"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_tax_tasks"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_tax_tasks_tenant_id"),
    )
    op.create_index("ix_tax_tasks_tenant_id", "tax_tasks", ["tenant_id"])
    op.create_index("ix_tax_tasks_tenant_status", "tax_tasks", ["tenant_id", "status"])


def downgrade() -> None:
    op.drop_table("tax_tasks")
    op.drop_table("sri_validation_issues")
    op.drop_table("tax_annexes")
    op.drop_table("tax_return_drafts")
    op.drop_table("tax_form_field_maps")
    op.drop_table("fiscal_retentions")
    op.drop_table("fiscal_document_taxes")
    op.drop_table("fiscal_documents")
    op.drop_table("tax_evidence")
    op.drop_table("tax_periods")
    op.drop_table("tenant_tax_profiles")
