"""Motor de calculo del IVA mensual (ADR 0012).

Toma los comprobantes ya conciliados del periodo y devuelve cada cifra junto con
**los documentos que la componen**: ningun numero aparece sin poder rastrearse
hasta su evidencia.

Reglas que aplica, tal como las definio el usuario:

- Las ventas salen de los comprobantes EMITIDOS. Nunca se infieren desde las
  retenciones recibidas.
- Las notas de credito RESTAN del grupo al que corresponden (ventas o compras).
- Las compras se separan en gravadas, tarifa 0%, exentas y no objeto.
- La retencion de IVA recibida (campo 609) es distinta de la retencion de renta,
  que se reserva para la conciliacion/renta anual y NO entra al IVA mensual.
- Si algun comprobante del periodo esta marcado preliminar, el resultado completo
  se marca preliminar: hay evidencia incompleta y el usuario debe saberlo antes
  de declarar.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthContext
from app.models.tax import FiscalDocument, FiscalDocumentTax, FiscalRetention, TaxPeriod
from app.services.tax.formatting import format_amount, quantize_amount

# Documentos que suman y que restan dentro de su grupo.
_ADDITIVE = ("FACTURA", "NOTA_DEBITO", "LIQUIDACION")
_SUBTRACTIVE = ("NOTA_CREDITO",)


@dataclass
class TracedAmount:
    """Un importe y la evidencia que lo respalda."""

    value: Decimal = Decimal("0.00")
    document_ids: list[uuid.UUID] = field(default_factory=list)

    def add(self, amount: Decimal, document_id: uuid.UUID) -> None:
        self.value += amount
        if document_id not in self.document_ids:
            self.document_ids.append(document_id)

    @property
    def formatted(self) -> str:
        return format_amount(self.value)


@dataclass
class IvaSummary:
    """Resultado del periodo. Las claves son las que consume `TaxFormFieldMap`."""

    amounts: dict[str, TracedAmount]
    is_preliminary: bool
    preliminary_reasons: list[str]
    document_count: int

    def value(self, key: str) -> Decimal:
        return self.amounts[key].value if key in self.amounts else Decimal("0.00")

    def as_dict(self) -> dict[str, str]:
        return {key: amount.formatted for key, amount in self.amounts.items()}


# Claves semanticas del motor. El mapa de campos del formulario apunta a estas,
# de modo que renumerar el 104 no obligue a tocar el calculo.
AMOUNT_KEYS = (
    "ventas_gravadas_bruta_base",
    "ventas_gravadas_base",
    "ventas_tarifa_cero_base",
    "ventas_exentas_base",
    "ventas_no_objeto_base",
    "ventas_brutas",
    "ventas_netas",
    "iva_generado",
    "compras_gravadas_bruta_base",
    "compras_gravadas_base",
    "compras_tarifa_cero_bruta_base",
    "compras_tarifa_cero_base",
    "compras_exentas_base",
    "compras_no_objeto_base",
    "compras_totales_base",
    "iva_credito_tributario",
    "retenciones_iva_recibidas",
    "retenciones_renta_recibidas",
    "impuesto_causado",
    "saldo_a_pagar",
    "credito_a_favor",
)

_BRACKET_KEYS = {
    "GRAVADO": "gravadas_base",
    "TARIFA_CERO": "tarifa_cero_base",
    "EXENTO": "exentas_base",
    "NO_OBJETO": "no_objeto_base",
}


async def compute_iva(
    session: AsyncSession,
    context: AuthContext,
    *,
    period: TaxPeriod,
) -> IvaSummary:
    """Calcula el IVA del periodo a partir de sus comprobantes."""
    amounts = {key: TracedAmount() for key in AMOUNT_KEYS}

    documents = list(
        await session.scalars(
            select(FiscalDocument).where(
                FiscalDocument.tenant_id == context.tenant_id,
                FiscalDocument.tax_period_id == period.id,
            )
        )
    )
    documents_by_id = {document.id: document for document in documents}

    preliminary_reasons: list[str] = []
    preliminary_documents = [document for document in documents if document.is_preliminary]
    if preliminary_documents:
        preliminary_reasons.append(
            f"{len(preliminary_documents)} comprobante(s) sin detalle confirmado: "
            "carga su XML autorizado antes de declarar."
        )

    if not documents_by_id:
        # Periodo sin comprobantes: todo queda en cero y se reporta el faltante,
        # en vez de simular un calculo sin evidencia.
        for amount in amounts.values():
            amount.value = quantize_amount(amount.value)
        preliminary_reasons.append(
            "El periodo no tiene comprobantes cargados: sube la evidencia del SRI."
        )
        return IvaSummary(
            amounts=amounts,
            is_preliminary=True,
            preliminary_reasons=preliminary_reasons,
            document_count=0,
        )

    document_ids = list(documents_by_id.keys())
    taxes = list(
        await session.scalars(
            select(FiscalDocumentTax).where(
                FiscalDocumentTax.tenant_id == context.tenant_id,
                FiscalDocumentTax.fiscal_document_id.in_(document_ids),
            )
        )
    )

    for tax in taxes:
        document = documents_by_id.get(tax.fiscal_document_id)
        if document is None or document.doc_type == "RETENCION":
            continue
        if document.doc_type in _SUBTRACTIVE:
            sign = Decimal("-1")
        elif document.doc_type in _ADDITIVE:
            sign = Decimal("1")
        else:
            continue

        side = "ventas" if document.direction == "EMITIDO" else "compras"
        bracket_key = _BRACKET_KEYS.get(tax.tax_bracket)
        if bracket_key is None:
            continue

        base = sign * tax.base_amount
        value = sign * tax.tax_amount

        amounts[f"{side}_{bracket_key}"].add(base, document.id)
        if side == "ventas":
            if sign > 0 and tax.tax_bracket == "GRAVADO":
                amounts["ventas_gravadas_bruta_base"].add(tax.base_amount, document.id)
            amounts["ventas_brutas"].add(base, document.id)
            amounts["iva_generado"].add(value, document.id)
        else:
            if sign > 0 and tax.tax_bracket == "GRAVADO":
                amounts["compras_gravadas_bruta_base"].add(tax.base_amount, document.id)
            elif sign > 0 and tax.tax_bracket == "TARIFA_CERO":
                amounts["compras_tarifa_cero_bruta_base"].add(
                    tax.base_amount, document.id
                )
            amounts["compras_totales_base"].add(base, document.id)
            amounts["iva_credito_tributario"].add(value, document.id)

    # Las ventas netas ya vienen netas de notas de credito: las NC entraron con
    # signo negativo. Se expone igual para que la pantalla lo muestre explicito.
    amounts["ventas_netas"].value = amounts["ventas_brutas"].value
    amounts["ventas_netas"].document_ids = list(amounts["ventas_brutas"].document_ids)

    retentions = list(
        await session.scalars(
            select(FiscalRetention).where(
                FiscalRetention.tenant_id == context.tenant_id,
                FiscalRetention.fiscal_document_id.in_(document_ids),
            )
        )
    )
    for retention in retentions:
        document = documents_by_id.get(retention.fiscal_document_id)
        # Solo cuentan las retenciones que le hicieron a la entidad, es decir las
        # que llegan en comprobantes RECIBIDOS.
        if document is None or document.direction != "RECIBIDO":
            continue
        key = (
            "retenciones_iva_recibidas"
            if retention.kind == "IVA"
            else "retenciones_renta_recibidas"
        )
        amounts[key].add(retention.retained_amount, document.id)

    causado = amounts["iva_generado"].value - amounts["iva_credito_tributario"].value
    amounts["impuesto_causado"].value = quantize_amount(causado)

    # La retencion de RENTA no entra aqui: es para la renta anual.
    balance = causado - amounts["retenciones_iva_recibidas"].value
    if balance >= 0:
        amounts["saldo_a_pagar"].value = quantize_amount(balance)
        amounts["credito_a_favor"].value = Decimal("0.00")
    else:
        amounts["saldo_a_pagar"].value = Decimal("0.00")
        amounts["credito_a_favor"].value = quantize_amount(-balance)

    for amount in amounts.values():
        amount.value = quantize_amount(amount.value)

    return IvaSummary(
        amounts=amounts,
        is_preliminary=bool(preliminary_reasons),
        preliminary_reasons=preliminary_reasons,
        document_count=len(documents),
    )


__all__ = ["AMOUNT_KEYS", "IvaSummary", "TracedAmount", "compute_iva"]
