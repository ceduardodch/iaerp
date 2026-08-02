"""Convierte comprobantes fiscales respaldados en la entrada del ATS.

Este modulo no completa campos con valores por defecto. Si al documento le
falta un dato que el ATS exige, devuelve el faltante para que la API lo reporte
antes de crear un anexo que el SRI rechazaria.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from app.models.tax import FiscalDocument, FiscalDocumentTax, FiscalRetention, TaxPeriod
from app.services.tax.ats import AtsInput, AtsPurchase, AtsSale

_ADD = {"FACTURA", "LIQUIDACION", "NOTA_DEBITO"}
_SUBTRACT = {"NOTA_CREDITO"}
_DOC_CODES = {
    "FACTURA": "01",
    "LIQUIDACION": "03",
    "NOTA_CREDITO": "04",
    "NOTA_DEBITO": "05",
}


@dataclass
class AtsBuildResult:
    """Entrada lista para serializar y faltantes que impiden hacerlo."""

    data: AtsInput
    missing: list[str] = field(default_factory=list)


def _identification_type(value: str | None, *, sale: bool) -> str | None:
    """Tipo ATS deducible solo de la longitud de una identificacion real."""
    digits = "".join(char for char in value or "" if char.isdigit())
    if len(digits) == 13:
        return "04" if sale else "01"
    if len(digits) == 10:
        return "05" if sale else "02"
    if len(digits) >= 5:
        return "06" if sale else "03"
    return None


def _date(value: date) -> str:
    return value.strftime("%d/%m/%Y")


def _series(document: FiscalDocument) -> str | None:
    if not all((document.establishment_code, document.emission_point_code, document.sequential)):
        return None
    assert document.establishment_code is not None
    assert document.emission_point_code is not None
    assert document.sequential is not None
    return "-".join(
        (document.establishment_code, document.emission_point_code, document.sequential)
    )


def build_ats_input(
    *,
    period: TaxPeriod,
    identification: str,
    legal_name: str,
    documents: list[FiscalDocument],
    taxes: list[FiscalDocumentTax],
    retentions: list[FiscalRetention],
) -> AtsBuildResult:
    """Arma el ATS exclusivamente desde documentos del periodo.

    La forma de pago no existe aun en el modelo fiscal. Por eso una venta (o
    compra sobre el umbral) sin esa evidencia queda como faltante, en lugar de
    asignarle ``01`` o ``20`` de manera ficticia.
    """
    by_document: dict[object, list[FiscalDocumentTax]] = defaultdict(list)
    for tax in taxes:
        by_document[tax.fiscal_document_id].append(tax)

    missing: list[str] = []
    purchases: list[AtsPurchase] = []
    sales_groups: dict[tuple[str, str, str], AtsSale] = {}
    sales_by_establishment: dict[str, Decimal] = defaultdict(lambda: Decimal("0.00"))
    retained_by_support: dict[str, list[FiscalRetention]] = defaultdict(list)
    for retention in retentions:
        if retention.supporting_document_number:
            retained_by_support[retention.supporting_document_number].append(retention)

    for document in documents:
        if document.doc_type not in _ADD | _SUBTRACT:
            continue
        if document.is_preliminary:
            missing.append(
                f"{document.doc_type} del {_date(document.issue_date)} está preliminar; "
                "carga su XML autorizado."
            )
            continue
        doc_code = _DOC_CODES[document.doc_type]
        sign = Decimal("-1") if document.doc_type in _SUBTRACT else Decimal("1")
        document_taxes = by_document.get(document.id, [])

        if document.direction == "RECIBIDO":
            id_type = _identification_type(
                document.counterparty_identification, sale=False
            )
            if not id_type or not document.counterparty_identification:
                missing.append(
                    f"Compra del {_date(document.issue_date)} sin identificación válida "
                    "del proveedor."
                )
                continue
            if not all(
                (document.establishment_code, document.emission_point_code, document.sequential)
            ):
                missing.append(
                    f"Compra del {_date(document.issue_date)} sin serie del comprobante."
                )
                continue
            if not document.authorization_number:
                missing.append(f"Compra del {_date(document.issue_date)} sin autorización SRI.")
                continue
            bases: defaultdict[str, Decimal] = defaultdict(lambda: Decimal("0.00"))
            iva = Decimal("0.00")
            for tax in document_taxes:
                bases[tax.tax_bracket] += sign * tax.base_amount
                iva += sign * tax.tax_amount
            purchases.append(
                AtsPurchase(
                    supplier_identification=document.counterparty_identification,
                    supplier_identification_type=id_type,
                    document_type=doc_code,
                    establishment=str(document.establishment_code),
                    emission_point=str(document.emission_point_code),
                    sequential=str(document.sequential),
                    issue_date=_date(document.issue_date),
                    registration_date=_date(document.issue_date),
                    authorization=document.authorization_number,
                    base_no_iva=bases["NO_OBJETO"],
                    base_zero_rate=bases["TARIFA_CERO"],
                    base_taxed=bases["GRAVADO"],
                    base_exempt=bases["EXENTO"],
                    iva_amount=iva,
                )
            )
            continue

        id_type = _identification_type(document.counterparty_identification, sale=True)
        if not id_type or not document.counterparty_identification:
            missing.append(
                f"Venta del {_date(document.issue_date)} sin identificación válida del cliente."
            )
            continue
        key = (document.counterparty_identification, id_type, doc_code)
        sale = sales_groups.get(key)
        if sale is None:
            sale = AtsSale(
                customer_identification=document.counterparty_identification,
                customer_identification_type=id_type,
                document_type=doc_code,
                payment_methods=[],
            )
            sales_groups[key] = sale
        else:
            sale.document_count += 1
        for tax in document_taxes:
            if tax.tax_bracket == "NO_OBJETO":
                sale.base_no_iva += sign * tax.base_amount
            elif tax.tax_bracket == "TARIFA_CERO":
                sale.base_zero_rate += sign * tax.base_amount
            elif tax.tax_bracket == "GRAVADO":
                sale.base_taxed += sign * tax.base_amount
            sale.iva_amount += sign * tax.tax_amount
        for retention in retained_by_support.get(_series(document) or "", []):
            if retention.kind == "IVA":
                sale.withheld_iva += retention.retained_amount
            elif retention.kind == "RENTA":
                sale.withheld_income_tax += retention.retained_amount
        if document.establishment_code:
            sales_by_establishment[document.establishment_code] += sign * document.subtotal
        # El SRI exige formasDePago en ventas, pero no hay evidencia de ella.
        missing.append(
            f"Venta {(_series(document) or _date(document.issue_date))} "
            "sin forma de pago respaldada."
        )

    for purchase in purchases:
        if purchase.total > Decimal("500.00"):
            missing.append(
                f"Compra {purchase.establishment}-{purchase.emission_point}-{purchase.sequential} "
                "supera el umbral ATS y no tiene forma de pago respaldada."
            )

    return AtsBuildResult(
        data=AtsInput(
            identification=identification,
            legal_name=legal_name,
            year=period.year,
            month=period.month,
            purchases=purchases,
            sales=list(sales_groups.values()),
            sales_by_establishment=dict(sales_by_establishment),
        ),
        missing=list(dict.fromkeys(missing)),
    )


__all__ = ["AtsBuildResult", "build_ats_input"]
