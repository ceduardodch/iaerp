"""product name: 300 caracteres, el tope de descripcion del SRI

Revision ID: b6c7d8e9f0a1
Revises: a5b6c7d8e9f0
Create Date: 2026-09-10 08:05:00.000000

Un servicio contratado por concurso publico se nombra con el objeto completo,
la entidad y el numero de proceso ("CONTRATO DE ENCARGO DE TRATAMIENTO DE
DATOS PERSONALES ... No.0XX-CM-2026 DEL (1 JULIO 2026 AL 31 JULIO 2026)"): 268
caracteres en un caso real. Con la columna en 200 el alta moria con
"name: String should have at most 200 characters" y no habia forma de guardar
el producto.

El techo nuevo es 300 y no un numero mayor porque este nombre es la
descripcion por defecto de la linea de factura, o sea el texto que viaja a
``detalle/descripcion`` del XML, limitado a 300 en el esquema SRI 1.1.0.
Permitir mas aqui solo cambiaria el error de sitio: pasaria de un 422 al crear
el producto a un comprobante rechazado al transmitirlo.

Ampliar la longitud de un ``varchar`` en PostgreSQL no reescribe la tabla ni
reconstruye ``ix_products_tenant_name``, y ningun dato existente cambia. El
downgrade solo puede correr si todavia ningun producto supera los 200
caracteres; si alguno los supera, PostgreSQL aborta el ALTER y hay que acortar
esos nombres antes.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b6c7d8e9f0a1"  # pragma: allowlist secret -- Alembic revision ID
down_revision: str | None = "a5b6c7d8e9f0"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "products",
        "name",
        existing_type=sa.String(length=200),
        type_=sa.String(length=300),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "products",
        "name",
        existing_type=sa.String(length=300),
        type_=sa.String(length=200),
        existing_nullable=False,
    )
