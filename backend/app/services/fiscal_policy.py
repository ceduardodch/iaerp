"""Motor de calculo fiscal versionado (ADR 0008, Accepted 2026-07-04).

``FiscalCalculationPolicy`` es inmutable: cada version congela el orden de
operaciones, la precision intermedia y las reglas de cuantizacion vigentes
desde una fecha. Backend, XML/RIDE (fases posteriores) y pruebas comparten la
misma version para una fecha de emision dada, evitando divergencias entre lo
que se firma, se muestra y se concilia contra el SRI.

Reglas tomadas de ``docs/adrs/0008-fiscal-calculation-rounding.md`` (Ficha
Tecnica de Comprobantes Electronicos Esquema Offline del SRI, numeral 8.17,
tablas 16/17):

1. ``cantidad``/``precioUnitario`` se cuantizan a 6 decimales (HALF_UP) al
   ingresar; ``descuento`` (valor absoluto por linea) se cuantiza a 2.
2. ``bruto = cantidad * precioUnitario`` sin cuantizar (precision completa).
3. ``precioTotalSinImpuesto`` (base imponible de la linea) =
   ``quantize(bruto - descuento, 0.01, HALF_UP)``. Unico punto de redondeo de
   la linea.
4. El ``valor`` de IVA por linea que se declara en el detalle es informativo
   (``quantize(base_linea * tarifa / 100, 0.01, HALF_UP)``): los totales del
   documento NUNCA se derivan de el.
5. Las lineas se agrupan por ``(codigoPorcentaje, tarifa)``. La
   ``baseImponible`` de cada grupo es la suma EXACTA (sin re-redondeo) de las
   bases de linea ya cuantizadas a 2 decimales. El ``valor`` de IVA del grupo
   se recalcula sobre esa base agregada (``quantize(base_grupo * tarifa / 100,
   0.01, HALF_UP)``) -- NO es la suma de los valores informativos de linea,
   que pueden diferir en centavos (ver vector de prueba de redondeo).
6. Los totales del documento (``totalSinImpuestos``, ``totalImpuesto`` por
   grupo sumado, ``importeTotal``) son sumas exactas de cantidades ya
   cuantizadas a 2 decimales; no hay redondeo final adicional.

Unico modo de redondeo permitido: ``ROUND_HALF_UP``. Cambiar una tarifa o una
regla crea una version nueva con su propia ``valid_from``; nunca se reescriben
documentos historicos ni autorizados.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

# Cuantizacion de cantidad y precio unitario: hasta 6 decimales (NUMERIC(18,6)).
_QUANTIZE_QUANTITY_PRICE = Decimal("0.000001")
# Cuantizacion de base imponible, impuesto y totales: 2 decimales (numeral 8.17).
_QUANTIZE_AMOUNT = Decimal("0.01")
_ROUNDING = ROUND_HALF_UP


@dataclass(frozen=True)
class LineInput:
    """Datos crudos de una linea, antes de cuantizar."""

    quantity: Decimal
    unit_price: Decimal
    discount: Decimal
    tax_rate: Decimal
    tax_sri_code: str


@dataclass(frozen=True)
class LineCalculation:
    """Resultado cuantizado de una linea, listo para persistir.

    ``tax_amount`` es el ``valor`` informativo de IVA por linea (numeral 5 del
    docstring del modulo): se persiste porque el XML de detalle lo exige, pero
    el total del documento se deriva de ``TaxSummaryEntry.tax_amount``
    (recalculado sobre la base agregada del grupo), nunca de la suma de estos
    valores por linea.
    """

    quantity: Decimal
    unit_price: Decimal
    discount: Decimal
    base_amount: Decimal
    tax_rate: Decimal
    tax_sri_code: str
    tax_amount: Decimal


@dataclass(frozen=True)
class TaxSummaryEntry:
    """Agregado de base e impuesto por tarifa/codigo SRI (``totalImpuesto``).

    ``base_amount`` es la suma exacta de las bases de linea del grupo.
    ``tax_amount`` se recalcula sobre esa base agregada, tal como exige el ADR
    0008 (no es la suma de los ``tax_amount`` informativos de cada linea).
    """

    tax_sri_code: str
    tax_rate: Decimal
    base_amount: Decimal
    tax_amount: Decimal


@dataclass(frozen=True)
class DocumentCalculation:
    """Totales del documento, agregados a partir de lineas ya cuantizadas."""

    lines: list[LineCalculation]
    tax_summary: list[TaxSummaryEntry]
    subtotal: Decimal
    tax_total: Decimal
    total: Decimal


def _quantize_amount(value: Decimal) -> Decimal:
    return value.quantize(_QUANTIZE_AMOUNT, rounding=_ROUNDING)


def _quantize_tax(base_amount: Decimal, tax_rate: Decimal) -> Decimal:
    return _quantize_amount(base_amount * tax_rate / Decimal(100))


@dataclass(frozen=True)
class FiscalCalculationPolicy:
    """Version inmutable del motor de calculo, vigente desde ``valid_from``.

    Ver el docstring del modulo para el detalle normativo completo (ADR 0008).
    """

    version: str
    valid_from: date

    def calculate_line(self, line: LineInput) -> LineCalculation:
        quantity = line.quantity.quantize(_QUANTIZE_QUANTITY_PRICE, rounding=_ROUNDING)
        unit_price = line.unit_price.quantize(_QUANTIZE_QUANTITY_PRICE, rounding=_ROUNDING)
        discount = _quantize_amount(line.discount)

        gross_amount = quantity * unit_price
        net_amount = gross_amount - discount
        base_amount = _quantize_amount(net_amount)

        # Valor informativo del detalle XML; el total del documento se deriva
        # de TaxSummaryEntry.tax_amount (recalculado sobre la base del grupo).
        tax_amount = _quantize_tax(base_amount, line.tax_rate)

        return LineCalculation(
            quantity=quantity,
            unit_price=unit_price,
            discount=discount,
            base_amount=base_amount,
            tax_rate=line.tax_rate,
            tax_sri_code=line.tax_sri_code,
            tax_amount=tax_amount,
        )

    def calculate_document(self, lines: list[LineInput]) -> DocumentCalculation:
        if not lines:
            raise ValueError("A sales document requires at least one line")

        calculated_lines = [self.calculate_line(line) for line in lines]

        # Paso 1: agregar SOLO las bases (suma exacta, sin re-redondeo, de
        # valores ya cuantizados a 2 decimales).
        base_by_rate: dict[tuple[str, Decimal], Decimal] = {}
        for calculated in calculated_lines:
            key = (calculated.tax_sri_code, calculated.tax_rate)
            base_by_rate[key] = base_by_rate.get(key, Decimal("0.00")) + calculated.base_amount

        # Paso 2: recalcular el impuesto de cada grupo sobre su base agregada,
        # nunca como suma de los valores informativos de linea (ADR 0008 #5).
        tax_summary = [
            TaxSummaryEntry(
                tax_sri_code=tax_sri_code,
                tax_rate=tax_rate,
                base_amount=base_amount,
                tax_amount=_quantize_tax(base_amount, tax_rate),
            )
            for (tax_sri_code, tax_rate), base_amount in base_by_rate.items()
        ]

        subtotal = sum((entry.base_amount for entry in tax_summary), Decimal("0.00"))
        tax_total = sum((entry.tax_amount for entry in tax_summary), Decimal("0.00"))
        total = subtotal + tax_total

        return DocumentCalculation(
            lines=calculated_lines,
            tax_summary=tax_summary,
            subtotal=subtotal,
            tax_total=tax_total,
            total=total,
        )


# Version historica, agregada en Fase 5 (E4-07) para poder resolver la
# politica vigente en la FECHA DE EMISION DE LA FACTURA DE SUSTENTO de una
# nota de credito emitida hoy sobre un documento anterior a 2024-04-01 (ADR
# 0008, seccion 5 y vector de prueba 7: "sustento de marzo 2024 con 12% se
# acredita al 12% aunque la NC se emita en 2026"). El motor de calculo
# (orden de operaciones, precision intermedia, ROUND_HALF_UP) es identico al
# de ``ec-iva-v1``: el ADR no documenta un cambio de regla aritmetica antes
# de 2024-04-01, solo un cambio de tarifa general (12% -> 15%, Decreto
# Ejecutivo 198), que se modela con la tarifa/``codigoPorcentaje`` de
# ``TaxCategory``/``SalesDocumentLine``, no con el motor de calculo. La
# fecha ``valid_from`` es deliberadamente un piso tecnico amplio (no una
# fecha normativa de inicio del IVA en Ecuador): esta version solo se
# resuelve para documentos de sustento anteriores a ``FISCAL_POLICY_V1``, y
# ninguna factura nueva se emite con fecha anterior a 2024-04-01 en este
# sistema (ver ``create_invoice_draft``, que valida ``issue_date`` contra
# ``today``, no contra el pasado -- el unico caso real es una NC 2026 sobre
# un documento historico ya existente en el dataset/fixture).
FISCAL_POLICY_V0 = FiscalCalculationPolicy(
    version="ec-iva-v0",
    valid_from=date(2000, 1, 1),
)

# Version inicial, aceptada en el ADR 0008 (2026-07-04) como "ec-iva-v1",
# vigente desde el arranque del regimen de IVA 15% (2024-04-01, Decreto
# Ejecutivo 198). Cambiar una tarifa o regla crea ``FISCAL_POLICY_V2`` con su
# propia ``valid_from`` en vez de mutar esta instancia; los documentos ya
# emitidos conservan su ``fiscal_policy_version`` original.
FISCAL_POLICY_V1 = FiscalCalculationPolicy(
    version="ec-iva-v1",
    valid_from=date(2024, 4, 1),
)

_POLICIES_BY_VALID_FROM: list[FiscalCalculationPolicy] = [FISCAL_POLICY_V0, FISCAL_POLICY_V1]


def resolve_fiscal_policy(issue_date: date) -> FiscalCalculationPolicy:
    """Selecciona la version vigente para una fecha de emision dada.

    Se elige la version mas reciente cuyo ``valid_from`` no sea posterior a
    ``issue_date``. Si ninguna version aplica (fecha anterior a toda vigencia
    conocida) se rechaza explicitamente en vez de asumir una version por
    defecto silenciosamente.
    """

    applicable = [policy for policy in _POLICIES_BY_VALID_FROM if policy.valid_from <= issue_date]
    if not applicable:
        raise ValueError(f"No fiscal policy is defined for issue date {issue_date.isoformat()}")
    return max(applicable, key=lambda policy: policy.valid_from)


def new_correlation_id() -> str:
    """Helper compartido para IDs de correlacion legibles en auditoria."""

    return str(uuid.uuid4())


__all__ = [
    "DocumentCalculation",
    "FISCAL_POLICY_V0",
    "FISCAL_POLICY_V1",
    "FiscalCalculationPolicy",
    "LineCalculation",
    "LineInput",
    "TaxSummaryEntry",
    "resolve_fiscal_policy",
]
