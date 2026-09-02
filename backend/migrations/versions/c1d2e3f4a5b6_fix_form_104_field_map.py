"""fix Form 104 purchase fields

Revision ID: c1d2e3f4a5b6
Revises: b0c1d2e3f4a5
Create Date: 2026-09-02 10:00:00.000000
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import date

import sqlalchemy as sa
from alembic import op

revision: str = "c1d2e3f4a5b6"  # pragma: allowlist secret -- Alembic revision ID
down_revision: str | None = "b0c1d2e3f4a5"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


FIELD_MAP = sa.table(
    "tax_form_field_maps",
    sa.column("id", sa.Uuid()),
    sa.column("tenant_id", sa.Uuid()),
    sa.column("form_code", sa.String()),
    sa.column("field_code", sa.String()),
    sa.column("label", sa.String()),
    sa.column("source_key", sa.String()),
    sa.column("is_paste", sa.Boolean()),
    sa.column("valid_from", sa.Date()),
    sa.column("valid_to", sa.Date()),
)

INCORRECT_CONTROL_DEFAULTS = {
    "500": (
        "Adquisiciones gravadas con tarifa distinta de 0% - valor bruto",
        "compras_gravadas_bruta_base",
    ),
    "510": (
        "Adquisiciones gravadas con tarifa distinta de 0% - valor neto",
        "compras_gravadas_base",
    ),
    "564": (
        "Credito tributario aplicable segun proporcionalidad o contabilidad",
        "iva_credito_tributario",
    ),
}

MISSING_FIELDS = {
    "531": (
        "Adquisiciones no objeto de IVA - valor bruto",
        "compras_no_objeto_bruta_base",
    ),
    "541": (
        "Adquisiciones no objeto de IVA - valor neto",
        "compras_no_objeto_base",
    ),
    "532": (
        "Adquisiciones exentas del pago de IVA - valor bruto",
        "compras_exentas_bruta_base",
    ),
    "542": (
        "Adquisiciones exentas del pago de IVA - valor neto",
        "compras_exentas_base",
    ),
}


def upgrade() -> None:
    connection = op.get_bind()
    for field_code, (label, source_key) in INCORRECT_CONTROL_DEFAULTS.items():
        connection.execute(
            sa.update(FIELD_MAP)
            .where(
                FIELD_MAP.c.form_code == "104",
                FIELD_MAP.c.field_code == field_code,
                FIELD_MAP.c.label == label,
                FIELD_MAP.c.source_key == source_key,
                FIELD_MAP.c.is_paste.is_(False),
            )
            .values(is_paste=True)
        )

    tenant_ids = list(
        connection.scalars(
            sa.select(FIELD_MAP.c.tenant_id)
            .where(FIELD_MAP.c.form_code == "104")
            .distinct()
        )
    )
    for tenant_id in tenant_ids:
        existing_codes = set(
            connection.scalars(
                sa.select(FIELD_MAP.c.field_code).where(
                    FIELD_MAP.c.tenant_id == tenant_id,
                    FIELD_MAP.c.form_code == "104",
                )
            )
        )
        rows = [
            {
                "id": uuid.uuid4(),
                "tenant_id": tenant_id,
                "form_code": "104",
                "field_code": field_code,
                "label": label,
                "source_key": source_key,
                "is_paste": True,
                "valid_from": date(2024, 1, 1),
                "valid_to": None,
            }
            for field_code, (label, source_key) in MISSING_FIELDS.items()
            if field_code not in existing_codes
        ]
        if rows:
            connection.execute(sa.insert(FIELD_MAP), rows)


def downgrade() -> None:
    # Es una correccion de datos sin cambio de esquema. Revertirla no es seguro:
    # despues del upgrade no se puede distinguir una fila migrada de un mapa que
    # el tenant haya confirmado o editado con los mismos valores. El downgrade
    # conserva los datos y solo permite retroceder la revision de Alembic.
    pass
