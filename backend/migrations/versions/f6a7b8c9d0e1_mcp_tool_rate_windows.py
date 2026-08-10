"""add durable automation rate windows

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f6a7b8c9d0e1"  # pragma: allowlist secret -- Alembic revision ID
down_revision: str | None = "e5f6a7b8c9d0"  # pragma: allowlist secret -- Alembic revision ID
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "automation_rate_windows",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.String(200), nullable=False),
        sa.Column("tool_name", sa.String(120), nullable=False),
        sa.Column("window_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "actor_id",
            "tool_name",
            name="uq_automation_rate_tenant_actor_tool",
        ),
    )
    op.create_index(
        "ix_automation_rate_tenant_id",
        "automation_rate_windows",
        ["tenant_id"],
    )
    op.create_index(
        "ix_automation_rate_tenant_window",
        "automation_rate_windows",
        ["tenant_id", "window_started_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_automation_rate_tenant_window", table_name="automation_rate_windows")
    op.drop_index("ix_automation_rate_tenant_id", table_name="automation_rate_windows")
    op.drop_table("automation_rate_windows")
