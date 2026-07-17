"""add collection_reminder and party.consent_opt_out

Revision ID: add_collection_reminder
Revises: f170c0d8901c
Create Date: 2026-07-06

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'add_collection_reminder'
down_revision: str | None = 'f170c0d8901c'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Add consent_opt_out column to parties table
    op.add_column(
        'parties',
        sa.Column('consent_opt_out', sa.Boolean(), nullable=False, server_default='0')
    )

    # Create collection_reminders table
    # Tipos de id/tenant_id/party_id deben coincidir EXACTAMENTE con
    # UUIDPrimaryKeyMixin/TenantEntityMixin (app/db/base.py) y parties.id
    # (sa.Uuid()), igual que el resto de tablas de receivables
    # (ver migrations/versions/f170c0d8901c_receivables_cartera.py), o la
    # FK compuesta (tenant_id, party_id) -> parties(tenant_id, id) falla
    # con DatatypeMismatchError en PostgreSQL.
    op.create_table(
        'collection_reminders',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text('now()'),
        ),
        sa.Column(
            'updated_at',
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text('now()'),
        ),
        sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column('party_id', sa.Uuid(), nullable=False),
        sa.Column('channel', sa.String(length=50), nullable=False),
        sa.Column('template_id', sa.String(length=100), nullable=False),
        sa.Column('recipient', sa.String(length=320), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='STUBBED'),
        sa.CheckConstraint(
            "status IN ('STUBBED', 'SENT', 'FAILED')",
            name='ck_collection_reminders_status_valid'
        ),
        sa.ForeignKeyConstraint(
            ['tenant_id', 'party_id'],
            ['parties.tenant_id', 'parties.id'],
            name='fk_collection_reminders_tenant_party'
        ),
        sa.ForeignKeyConstraint(
            ['tenant_id'],
            ['tenants.id'],
            name='fk_collection_reminders_tenant_id'
        ),
        sa.PrimaryKeyConstraint('id', name='pk_collection_reminders'),
        sa.UniqueConstraint('tenant_id', 'id', name='uq_collection_reminders_tenant_id')
    )
    op.create_index(
        'ix_collection_reminders_tenant_party',
        'collection_reminders',
        ['tenant_id', 'party_id']
    )
    op.create_index(
        'ix_collection_reminders_tenant_status',
        'collection_reminders',
        ['tenant_id', 'status']
    )
    op.create_index(
        'ix_collection_reminders_created_at',
        'collection_reminders',
        ['tenant_id', 'created_at']
    )
    op.create_index(
        'ix_collection_reminders_tenant_id',
        'collection_reminders',
        ['tenant_id']
    )


def downgrade() -> None:
    op.drop_index('ix_collection_reminders_tenant_id', table_name='collection_reminders')
    op.drop_index('ix_collection_reminders_created_at', table_name='collection_reminders')
    op.drop_index('ix_collection_reminders_tenant_status', table_name='collection_reminders')
    op.drop_index('ix_collection_reminders_tenant_party', table_name='collection_reminders')
    op.drop_table('collection_reminders')
    op.drop_column('parties', 'consent_opt_out')
