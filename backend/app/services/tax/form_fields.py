"""Mapa de campos del formulario hacia las cifras calculadas (ADR 0012).

Los codigos del formulario 104 NO se codifican en el motor: viven en
``TaxFormFieldMap``, con vigencia, para que renumerar el formulario no obligue a
tocar el calculo. Este modulo solo aporta un **seed inicial editable**.

``is_paste`` distingue lo que el usuario copia al formulario de lo que el SRI
autocalcula (solo control): mezclarlos hace que se pisen valores calculados por
el propio formulario.

⚠️ Los codigos marcados ``needs_review`` requieren evidencia adicional antes de
declarar. El 564 depende del factor de proporcionalidad o de la contabilidad y
no puede deducirse solo de los XML. El 609 es solo retencion de IVA recibida.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthContext
from app.models.tax import TaxFormFieldMap


@dataclass(frozen=True)
class FieldSeed:
    field_code: str
    label: str
    source_key: str
    is_paste: bool
    needs_review: bool = False


# Seed del formulario 104. Editable desde la base sin tocar codigo.
FORM_104_SEED: tuple[FieldSeed, ...] = (
    FieldSeed(
        "401",
        "Ventas locales gravadas con tarifa distinta de 0% - valor bruto",
        "ventas_gravadas_bruta_base",
        True,
    ),
    FieldSeed(
        "411",
        "Ventas locales gravadas con tarifa distinta de 0% - valor neto",
        "ventas_gravadas_base",
        True,
    ),
    FieldSeed(
        "500",
        "Adquisiciones gravadas con tarifa distinta de 0% - valor bruto",
        "compras_gravadas_bruta_base",
        True,
        needs_review=True,
    ),
    FieldSeed(
        "510",
        "Adquisiciones gravadas con tarifa distinta de 0% - valor neto",
        "compras_gravadas_base",
        True,
        needs_review=True,
    ),
    FieldSeed(
        "517",
        "Adquisiciones gravadas con tarifa 0% - valor neto",
        "compras_tarifa_cero_base",
        True,
    ),
    FieldSeed(
        "507",
        "Adquisiciones y pagos (incluye activos fijos) gravados con tarifa 0% - valor bruto",
        "compras_tarifa_cero_bruta_base",
        True,
    ),
    FieldSeed(
        "531",
        "Adquisiciones no objeto de IVA - valor bruto",
        "compras_no_objeto_bruta_base",
        True,
    ),
    FieldSeed(
        "541",
        "Adquisiciones no objeto de IVA - valor neto",
        "compras_no_objeto_base",
        True,
    ),
    FieldSeed(
        "532",
        "Adquisiciones exentas del pago de IVA - valor bruto",
        "compras_exentas_bruta_base",
        True,
    ),
    FieldSeed(
        "542",
        "Adquisiciones exentas del pago de IVA - valor neto",
        "compras_exentas_base",
        True,
    ),
    FieldSeed(
        "564",
        "Credito tributario aplicable segun proporcionalidad o contabilidad",
        "iva_credito_tributario",
        True,
        needs_review=True,
    ),
    # Confirmado por el usuario: el 609 es SOLO retencion de IVA recibida.
    FieldSeed("609", "Retenciones de IVA que le efectuaron", "retenciones_iva_recibidas", True),
)


async def ensure_form_field_map(
    session: AsyncSession,
    context: AuthContext,
    *,
    form_code: str = "104",
    valid_from: date | None = None,
) -> list[TaxFormFieldMap]:
    """Devuelve el mapa del formulario, sembrandolo la primera vez.

    No sobrescribe lo que el usuario ya haya ajustado: solo agrega los codigos
    que falten.
    """
    effective_from = valid_from or date(2024, 1, 1)
    existing = list(
        await session.scalars(
            select(TaxFormFieldMap).where(
                TaxFormFieldMap.tenant_id == context.tenant_id,
                TaxFormFieldMap.form_code == form_code,
            )
        )
    )
    known = {record.field_code for record in existing}

    # Corrige los seeds antiguos solo si siguen intactos. Si el tenant edito
    # cualquiera de estos valores, se conserva su mapa sin cambios.
    legacy_defaults = {
        "401": (
            "Ventas locales gravadas con tarifa distinta de 0%",
            "ventas_gravadas_base",
            True,
        ),
        "411": (
            "Ventas locales gravadas con tarifa 0%",
            "ventas_tarifa_cero_base",
            True,
        ),
        "500": ("Total de ventas y otras operaciones", "ventas_brutas", False),
        "510": (
            "Adquisiciones gravadas con tarifa distinta de 0%",
            "compras_gravadas_base",
            True,
        ),
        "517": (
            "Adquisiciones gravadas con tarifa 0%",
            "compras_tarifa_cero_base",
            True,
        ),
        "507": (
            "Total de adquisiciones y pagos (confirmar contra el formulario vigente)",
            "compras_totales_base",
            False,
        ),
    }
    seeds_by_code = {seed.field_code: seed for seed in FORM_104_SEED}
    for record in existing:
        legacy = legacy_defaults.get(record.field_code)
        seed = seeds_by_code.get(record.field_code)
        if legacy is not None and seed is not None:
            legacy_label, legacy_source, legacy_paste = legacy
            if (
                record.label == legacy_label
                and record.source_key == legacy_source
                and record.is_paste is legacy_paste
            ):
                record.label = seed.label
                record.source_key = seed.source_key
                record.is_paste = seed.is_paste

    for seed in FORM_104_SEED:
        if seed.field_code in known:
            continue
        record = TaxFormFieldMap(
            tenant_id=context.tenant_id,
            form_code=form_code,
            field_code=seed.field_code,
            label=seed.label,
            source_key=seed.source_key,
            is_paste=seed.is_paste,
            valid_from=effective_from,
        )
        session.add(record)
        existing.append(record)

    await session.flush()
    return sorted(existing, key=lambda record: record.field_code)


def fields_for_date(records: list[TaxFormFieldMap], moment: date) -> list[TaxFormFieldMap]:
    """Filtra el mapa por vigencia (el formulario cambia entre periodos)."""
    return [
        record
        for record in records
        if record.valid_from <= moment and (record.valid_to is None or record.valid_to >= moment)
    ]


def review_pending_codes() -> set[str]:
    """Codigos cuyo valor requiere confirmar un criterio tributario o contable."""
    return {seed.field_code for seed in FORM_104_SEED if seed.needs_review}


def period_reference_date(year: int, month: int) -> date:
    return date(year, month, 1)


def field_map_id(record: TaxFormFieldMap) -> uuid.UUID:
    return record.id


__all__ = [
    "FORM_104_SEED",
    "FieldSeed",
    "ensure_form_field_map",
    "fields_for_date",
    "period_reference_date",
    "review_pending_codes",
]
