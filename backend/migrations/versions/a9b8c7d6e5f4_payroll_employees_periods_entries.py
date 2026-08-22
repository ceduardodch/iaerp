"""payroll employees periods entries

Revision ID: a9b8c7d6e5f4
Revises: e2f3a4b5c6d7
Create Date: 2026-08-22 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a9b8c7d6e5f4"
down_revision: str | None = "e2f3a4b5c6d7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "payroll_employees",
        sa.Column("full_name", sa.String(length=200), nullable=False),
        sa.Column("identification_number", sa.String(length=20), nullable=False),
        sa.Column("position", sa.String(length=120), nullable=True),
        sa.Column("sueldo_mensual", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("fecha_ingreso", sa.Date(), nullable=False),
        sa.Column("fecha_salida", sa.Date(), nullable=True),
        sa.Column("decimo_tercero_mensualizado", sa.Boolean(), nullable=False),
        sa.Column("decimo_cuarto_mensualizado", sa.Boolean(), nullable=False),
        sa.Column("fondos_reserva_mensualizados", sa.Boolean(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "sueldo_mensual >= 0", name="ck_payroll_employees_sueldo_mensual_non_negative"
        ),
        sa.CheckConstraint(
            "fecha_salida IS NULL OR fecha_salida >= fecha_ingreso",
            name="ck_payroll_employees_fecha_salida_after_ingreso",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_payroll_employees_tenant_id_tenants")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_payroll_employees")),
        sa.UniqueConstraint("tenant_id", "id", name="uq_payroll_employees_tenant_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "identification_number",
            name="uq_payroll_employees_tenant_identification",
        ),
    )
    op.create_index(
        op.f("ix_payroll_employees_tenant_id"), "payroll_employees", ["tenant_id"], unique=False
    )

    op.create_table(
        "payroll_periods",
        sa.Column("anio", sa.Integer(), nullable=False),
        sa.Column("mes", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint("mes >= 1 AND mes <= 12", name="ck_payroll_periods_mes_valid"),
        sa.CheckConstraint(
            "status IN ('DRAFT', 'APPROVED')", name="ck_payroll_periods_status_valid"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_payroll_periods_tenant_id_tenants")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_payroll_periods")),
        sa.UniqueConstraint("tenant_id", "id", name="uq_payroll_periods_tenant_id"),
        sa.UniqueConstraint(
            "tenant_id", "anio", "mes", name="uq_payroll_periods_tenant_anio_mes"
        ),
    )
    op.create_index(
        op.f("ix_payroll_periods_tenant_id"), "payroll_periods", ["tenant_id"], unique=False
    )

    op.create_table(
        "payroll_entries",
        sa.Column("period_id", sa.Uuid(), nullable=False),
        sa.Column("employee_id", sa.Uuid(), nullable=False),
        sa.Column("dias_trabajados", sa.Integer(), nullable=False),
        sa.Column("imponible", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("decimo_tercero", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("decimo_cuarto", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("fondos_reserva", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("total_ingresos", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("aporte_iess", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("total_descuentos", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("liquido", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("sbu_aplicado", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("tasa_iess_aplicada", sa.Numeric(precision=9, scale=6), nullable=False),
        sa.Column("tasa_fondos_aplicada", sa.Numeric(precision=9, scale=6), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "dias_trabajados >= 0 AND dias_trabajados <= 30",
            name="ck_payroll_entries_dias_trabajados_valid",
        ),
        sa.CheckConstraint("imponible >= 0", name="ck_payroll_entries_imponible_non_negative"),
        sa.CheckConstraint(
            "total_ingresos >= 0", name="ck_payroll_entries_total_ingresos_non_negative"
        ),
        sa.CheckConstraint(
            "total_descuentos >= 0", name="ck_payroll_entries_total_descuentos_non_negative"
        ),
        sa.CheckConstraint("liquido >= 0", name="ck_payroll_entries_liquido_non_negative"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "employee_id"],
            ["payroll_employees.tenant_id", "payroll_employees.id"],
            name="fk_payroll_entries_tenant_employee",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "period_id"],
            ["payroll_periods.tenant_id", "payroll_periods.id"],
            name="fk_payroll_entries_tenant_period",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_payroll_entries_tenant_id_tenants")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_payroll_entries")),
        sa.UniqueConstraint("tenant_id", "id", name="uq_payroll_entries_tenant_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "period_id",
            "employee_id",
            name="uq_payroll_entries_tenant_period_employee",
        ),
    )
    op.create_index(
        op.f("ix_payroll_entries_tenant_id"), "payroll_entries", ["tenant_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_payroll_entries_tenant_id"), table_name="payroll_entries")
    op.drop_table("payroll_entries")
    op.drop_index(op.f("ix_payroll_periods_tenant_id"), table_name="payroll_periods")
    op.drop_table("payroll_periods")
    op.drop_index(op.f("ix_payroll_employees_tenant_id"), table_name="payroll_employees")
    op.drop_table("payroll_employees")
