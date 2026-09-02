import importlib.util
import uuid
from datetime import date
from pathlib import Path
from types import ModuleType

import sqlalchemy as sa


def load_migration() -> ModuleType:
    path = (
        Path(__file__).parents[1]
        / "migrations/versions/c1d2e3f4a5b6_fix_form_104_field_map.py"
    )
    spec = importlib.util.spec_from_file_location("form_104_field_map_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_upgrade_repairs_only_defaults_and_is_idempotent(monkeypatch) -> None:
    migration = load_migration()
    engine = sa.create_engine("sqlite://")
    metadata = sa.MetaData()
    field_map = sa.Table(
        "tax_form_field_maps",
        metadata,
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("form_code", sa.String(), nullable=False),
        sa.Column("field_code", sa.String(), nullable=False),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column("source_key", sa.String(), nullable=False),
        sa.Column("is_paste", sa.Boolean(), nullable=False),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.Column("valid_to", sa.Date()),
        sa.UniqueConstraint("tenant_id", "form_code", "field_code", "valid_from"),
    )
    metadata.create_all(engine)
    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()

    with engine.begin() as connection:
        connection.execute(
            sa.insert(field_map),
            [
                {
                    "id": uuid.uuid4(),
                    "tenant_id": tenant_a,
                    "form_code": "104",
                    "field_code": "500",
                    "label": "Adquisiciones gravadas con tarifa distinta de 0% - valor bruto",
                    "source_key": "compras_gravadas_bruta_base",
                    "is_paste": False,
                    "valid_from": date(2024, 1, 1),
                },
                {
                    "id": uuid.uuid4(),
                    "tenant_id": tenant_a,
                    "form_code": "104",
                    "field_code": "510",
                    "label": "Adquisiciones gravadas con tarifa distinta de 0% - valor neto",
                    "source_key": "compras_gravadas_base",
                    "is_paste": False,
                    "valid_from": date(2024, 1, 1),
                },
                {
                    "id": uuid.uuid4(),
                    "tenant_id": tenant_a,
                    "form_code": "104",
                    "field_code": "564",
                    "label": (
                        "Credito tributario aplicable segun proporcionalidad o contabilidad"
                    ),
                    "source_key": "iva_credito_tributario",
                    "is_paste": False,
                    "valid_from": date(2024, 1, 1),
                },
                {
                    "id": uuid.uuid4(),
                    "tenant_id": tenant_b,
                    "form_code": "104",
                    "field_code": "500",
                    "label": "Mapa personalizado por el tenant",
                    "source_key": "compras_gravadas_bruta_base",
                    "is_paste": False,
                    "valid_from": date(2024, 1, 1),
                },
            ],
        )
        monkeypatch.setattr(migration.op, "get_bind", lambda: connection)
        migration.upgrade()
        migration.upgrade()
        migration.downgrade()

        rows = list(connection.execute(sa.select(field_map)).mappings())

    default_500 = next(
        row for row in rows if row["tenant_id"] == tenant_a and row["field_code"] == "500"
    )
    custom_500 = next(
        row for row in rows if row["tenant_id"] == tenant_b and row["field_code"] == "500"
    )
    assert default_500["is_paste"] is True
    assert custom_500["is_paste"] is False
    repaired_codes = {
        row["field_code"]
        for row in rows
        if row["tenant_id"] == tenant_a
        and row["field_code"] in migration.INCORRECT_CONTROL_DEFAULTS
        and row["is_paste"] is True
    }
    assert repaired_codes == set(migration.INCORRECT_CONTROL_DEFAULTS)
    for tenant_id in (tenant_a, tenant_b):
        inserted_codes = {
            row["field_code"]
            for row in rows
            if row["tenant_id"] == tenant_id and row["field_code"] in migration.MISSING_FIELDS
        }
        assert inserted_codes == set(migration.MISSING_FIELDS)
        assert len(
            [
                row
                for row in rows
                if row["tenant_id"] == tenant_id
                and row["field_code"] in migration.MISSING_FIELDS
            ]
        ) == 4
