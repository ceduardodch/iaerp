"""Qué considera el ATS un dato sin respaldo, y qué no.

``build_ats_input`` decide qué bloquea la generación del anexo. No tenía
pruebas, y por eso pasó desapercibido que marcaba como "sin forma de pago"
CUALQUIER compra sobre el umbral, incluso cuando su XML sí la declaraba: la
condición miraba solo el monto. Con compras normales sobre 500 USD eso dejaba
el ATS imposible de generar.

Estas pruebas fijan las dos mitades de la regla: el monto Y la ausencia de
evidencia. Y siguen exigiendo el bloqueo real cuando el dato de verdad falta,
porque el ADR 0012 prohíbe rellenar una forma de pago inventada.
"""

import uuid
from datetime import date
from decimal import Decimal
from xml.etree.ElementTree import fromstring

from app.models.tax import FiscalDocument, FiscalDocumentTax, FiscalRetention, TaxPeriod
from app.services.tax.ats import PAYMENT_METHOD_THRESHOLD, build_ats_xml
from app.services.tax.ats_builder import build_ats_input

TENANT = uuid.UUID("11111111-1111-4111-8111-111111111111")


def _period() -> TaxPeriod:
    return TaxPeriod(tenant_id=TENANT, year=2026, month=7, obligation_type="IVA", status="ABIERTO")


def _purchase(
    *,
    sequential: str,
    base: Decimal,
    iva: Decimal,
    payment_methods: list[str],
    doc_type: str = "FACTURA",
) -> tuple[FiscalDocument, FiscalDocumentTax]:
    """Compra recibida con todo lo que el ATS exige, salvo lo que se prueba."""
    document = FiscalDocument(
        id=uuid.uuid4(),
        tenant_id=TENANT,
        direction="RECIBIDO",
        doc_type=doc_type,
        authorization_number="1107202601179999999900110010000086031234567819",
        issue_date=date(2026, 7, 11),
        establishment_code="001",
        emission_point_code="010",
        sequential=sequential,
        counterparty_identification="1790000000001",
        counterparty_name="PROVEEDOR DEMO",
        subtotal=base,
        tax_total=iva,
        total=base + iva,
        payment_methods=payment_methods,
        is_preliminary=False,
    )
    tax = FiscalDocumentTax(
        tenant_id=TENANT,
        fiscal_document_id=document.id,
        sri_tax_code="4",
        tax_bracket="GRAVADO",
        rate=Decimal("15.00"),
        base_amount=base,
        tax_amount=iva,
    )
    return document, tax


def _sale() -> tuple[FiscalDocument, FiscalDocumentTax]:
    """Factura emitida realista para fijar los códigos y totales del ATS."""
    base = Decimal("5769.00")
    iva = Decimal("865.35")
    document = FiscalDocument(
        id=uuid.uuid4(),
        tenant_id=TENANT,
        direction="EMITIDO",
        doc_type="FACTURA",
        authorization_number="1805202601179999999900120010017067686471234567818",
        issue_date=date(2026, 5, 18),
        establishment_code="001",
        emission_point_code="001",
        sequential="706768647",
        counterparty_identification="1790000000001",
        counterparty_name="CLIENTE DEMO",
        subtotal=base,
        tax_total=iva,
        total=base + iva,
        payment_methods=["01"],
        is_preliminary=False,
    )
    tax = FiscalDocumentTax(
        tenant_id=TENANT,
        fiscal_document_id=document.id,
        sri_tax_code="4",
        tax_bracket="GRAVADO",
        rate=Decimal("15.00"),
        base_amount=base,
        tax_amount=iva,
    )
    return document, tax


def _build(pairs: list[tuple[FiscalDocument, FiscalDocumentTax]]):
    return build_ats_input(
        period=_period(),
        identification="1799999999001",
        legal_name="EMPRESA DEMO",
        documents=[document for document, _ in pairs],
        taxes=[tax for _, tax in pairs],
        retentions=[],
    )


def test_purchase_over_threshold_with_payment_method_is_not_missing() -> None:
    """La regresión: tenía forma de pago y aun así bloqueaba el ATS."""
    result = _build([
        _purchase(
            sequential="000008603",
            base=Decimal("1000.00"),
            iva=Decimal("150.00"),
            payment_methods=["20"],
        )
    ])

    assert result.missing == []
    assert result.data.purchases[0].payment_methods == ["20"]


def test_non_preliminary_document_without_tax_rows_blocks_ats() -> None:
    document, _tax = _purchase(
        sequential="000008699",
        base=Decimal("100.00"),
        iva=Decimal("15.00"),
        payment_methods=["20"],
    )
    result = build_ats_input(
        period=_period(),
        identification="1799999999001",
        legal_name="EMPRESA DEMO",
        documents=[document],
        taxes=[],
        retentions=[],
    )

    assert len(result.missing) == 1
    assert "desglose tributario por tarifa" in result.missing[0]
    assert result.data.purchases == []


def test_purchase_over_threshold_without_payment_method_is_missing() -> None:
    result = _build([
        _purchase(
            sequential="000008604",
            base=Decimal("1000.00"),
            iva=Decimal("150.00"),
            payment_methods=[],
        )
    ])

    # Sigue bloqueando cuando el dato falta de verdad: no se inventa un "20".
    assert len(result.missing) == 1
    assert "001-010-000008604" in result.missing[0]
    assert "forma de pago" in result.missing[0]


def test_purchase_under_threshold_without_payment_method_is_allowed() -> None:
    """Bajo el umbral el SRI no exige declararla, así que no puede bloquear."""
    result = _build([
        _purchase(
            sequential="000008605",
            base=Decimal("100.00"),
            iva=Decimal("15.00"),
            payment_methods=[],
        )
    ])

    assert result.missing == []


def test_received_credit_note_is_reported_as_ats_code_04_with_positive_values() -> None:
    source = _purchase(
        sequential="000008608",
        base=Decimal("100.00"),
        iva=Decimal("15.00"),
        payment_methods=["20"],
    )
    note = _purchase(
        sequential="000008609",
        base=Decimal("5.00"),
        iva=Decimal("0.75"),
        payment_methods=[],
        doc_type="NOTA_CREDITO",
    )
    source[0].access_key = "1" * 49
    source[0].authorization_number = "1" * 49
    note[0].related_access_key = source[0].access_key
    note[0].related_document_number = "001-010-000008608"
    # La factura modificada puede pertenecer a otro período: se usa para los
    # campos obligatorios del tipo 04, pero no se suma como compra de este mes.
    result = build_ats_input(
        period=_period(),
        identification="1799999999001",
        legal_name="EMPRESA DEMO",
        documents=[note[0]],
        taxes=[note[1]],
        retentions=[],
        related_documents=[source[0]],
    )

    assert result.missing == []
    purchase = next(
        item for item in result.data.purchases if item.document_type == "04"
    )
    assert purchase.document_type == "04"
    assert purchase.base_taxed == Decimal("5.00")
    assert purchase.iva_amount == Decimal("0.75")
    root = fromstring(build_ats_xml(result.data))
    xml_note = next(
        item
        for item in root.findall("compras/detalleCompras")
        if item.findtext("tipoComprobante") == "04"
    )
    assert xml_note.findtext("docModificado") == "01"
    assert xml_note.findtext("estabModificado") == "001"
    assert xml_note.findtext("ptoEmiModificado") == "010"
    assert xml_note.findtext("secModificado") == "000008608"
    assert xml_note.findtext("autModificado") == "1" * 49
    tags = [child.tag for child in xml_note]
    assert tags.index("pagoExterior") < tags.index("docModificado")


def test_emitted_credit_note_has_positive_detail_and_net_sales_header() -> None:
    invoice = _sale()
    note = _sale()
    note[0].doc_type = "NOTA_CREDITO"
    note[0].sequential = "706768648"
    note[0].subtotal = Decimal("100.00")
    note[0].tax_total = Decimal("15.00")
    note[0].total = Decimal("115.00")
    note[1].base_amount = Decimal("100.00")
    note[1].tax_amount = Decimal("15.00")

    result = _build([invoice, note])
    root = fromstring(build_ats_xml(result.data))
    credit = next(
        item
        for item in root.findall("ventas/detalleVentas")
        if item.findtext("tipoComprobante") == "04"
    )

    assert credit.findtext("baseImpGrav") == "100.00"
    assert credit.findtext("montoIva") == "15.00"
    assert root.findtext("totalVentas") == "5669.00"
    assert root.findtext("ventasEstablecimiento/ventaEst/ventasEstab") == "5669.00"


def test_ats_blocks_negative_net_sales_from_credit_notes() -> None:
    note = _sale()
    note[0].doc_type = "NOTA_CREDITO"

    result = _build([note])

    assert any("superan las ventas del período" in item for item in result.missing)
    assert any("establecimiento 001" in item for item in result.missing)


def test_threshold_is_exclusive_at_the_exact_amount() -> None:
    """Justo EN el umbral no se exige; la regla es "supera", no "alcanza"."""
    base = PAYMENT_METHOD_THRESHOLD - Decimal("50.00")
    iva = Decimal("50.00")
    assert base + iva == PAYMENT_METHOD_THRESHOLD

    result = _build([
        _purchase(sequential="000008606", base=base, iva=iva, payment_methods=[])
    ])

    assert result.missing == []


def test_one_purchase_without_evidence_does_not_hide_the_others() -> None:
    result = _build([
        _purchase(
            sequential="000008607",
            base=Decimal("900.00"),
            iva=Decimal("135.00"),
            payment_methods=["01"],
        ),
        _purchase(
            sequential="000008608",
            base=Decimal("800.00"),
            iva=Decimal("120.00"),
            payment_methods=[],
        ),
    ])

    # Solo se reporta la que realmente carece de respaldo, con su serie, para
    # que la persona sepa cuál comprobante ir a buscar.
    assert len(result.missing) == 1
    assert "001-010-000008608" in result.missing[0]
    assert len(result.data.purchases) == 2


def test_sale_uses_ats_code_18_and_establishment_total_matches_header() -> None:
    """Regresión del rechazo SRI: total de ventas no puede sumar contra cero."""
    document, tax = _sale()
    retention_document_id = uuid.uuid4()
    retentions = [
        FiscalRetention(
            tenant_id=TENANT,
            fiscal_document_id=retention_document_id,
            kind="IVA",
            sri_code="2",
            percentage=Decimal("30.00"),
            base_amount=Decimal("865.35"),
            retained_amount=Decimal("259.61"),
            supporting_document_number="001001706768647",
        ),
        FiscalRetention(
            tenant_id=TENANT,
            fiscal_document_id=retention_document_id,
            kind="RENTA",
            sri_code="312",
            percentage=Decimal("2.00"),
            base_amount=Decimal("5769.00"),
            retained_amount=Decimal("115.38"),
            supporting_document_number="001001706768647",
        ),
    ]
    result = build_ats_input(
        period=TaxPeriod(
            tenant_id=TENANT,
            year=2026,
            month=5,
            obligation_type="IVA",
            status="ABIERTO",
        ),
        identification="1799999999001",
        legal_name="EMPRESA DEMO",
        documents=[document],
        taxes=[tax],
        retentions=retentions,
    )

    assert result.missing == []
    root = fromstring(build_ats_xml(result.data))
    assert root.findtext("totalVentas") == "5769.00"
    assert root.findtext("ventas/detalleVentas/tipoComprobante") == "18"
    assert root.findtext("ventas/detalleVentas/baseImpGrav") == "5769.00"
    assert root.findtext("ventas/detalleVentas/montoIva") == "865.35"
    assert root.findtext("ventas/detalleVentas/valorRetIva") == "259.61"
    assert root.findtext("ventas/detalleVentas/valorRetRenta") == "115.38"
    assert root.findtext("ventasEstablecimiento/ventaEst/ventasEstab") == "5769.00"
