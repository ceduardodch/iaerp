"""Pruebas de generacion de XML SRI contra un ``SalesDocument`` de fixture.

El vector usado (tres lineas de 1 x 1.05, cp 4 / 15%) es el vector 3 del ADR
0008: la suma de los ``valor`` informativos por linea (0.16 x 3 = 0.48) NO
coincide con el ``valor`` de grupo recalculado sobre la base agregada (0.47).
Este modulo de XML no debe volver a calcular nada; debe reflejar exactamente
lo que ``fiscal_policy.py`` ya persistio, por lo que las aserciones verifican
que ``totalImpuesto`` declare 0.47 (y NO 0.48) y que cada ``detalle`` declare
0.16 (el valor informativo por linea, tal cual el ADR exige que se
serialice).
"""

import uuid
from datetime import date
from decimal import Decimal

import pytest
from lxml import etree

from app.models.billing import SalesDocument, SalesDocumentLine
from app.models.masters import EmissionPoint, Establishment, Party
from app.services.fiscal_policy import FISCAL_POLICY_V1, LineInput
from app.services.sri_xml import build_credit_note_xml, build_invoice_xml

_NAMESPACE_FREE = {}  # el esquema SRI factura no usa namespaces


def _build_document_and_lines(
    *,
    document_type: str = "INVOICE",
    access_key: str | None = "0" * 49,
) -> tuple[SalesDocument, list[SalesDocumentLine]]:
    tenant_id = uuid.uuid4()
    document_id = uuid.uuid4()

    line_inputs = [
        LineInput(
            quantity=Decimal("1"),
            unit_price=Decimal("1.05"),
            discount=Decimal("0.00"),
            tax_rate=Decimal("15"),
            tax_sri_code="4",
        )
        for _ in range(3)
    ]
    calculation = FISCAL_POLICY_V1.calculate_document(line_inputs)

    document = SalesDocument(
        id=document_id,
        tenant_id=tenant_id,
        document_type=document_type,
        establishment_id=uuid.uuid4(),
        emission_point_id=uuid.uuid4(),
        sequential="000000001",
        access_key=access_key,
        party_id=uuid.uuid4(),
        issue_date=date(2026, 7, 4),
        status="SIGNED",
        currency="USD",
        subtotal=calculation.subtotal,
        tax_total=calculation.tax_total,
        total=calculation.total,
        fiscal_policy_version=FISCAL_POLICY_V1.version,
        reason=None,
    )

    lines = [
        SalesDocumentLine(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            sales_document_id=document_id,
            line_number=index,
            product_id=None,
            description=f"Linea {index}",
            quantity=calculated.quantity,
            unit_price=calculated.unit_price,
            discount=calculated.discount,
            base_amount=calculated.base_amount,
            tax_sri_code=calculated.tax_sri_code,
            tax_rate=calculated.tax_rate,
            tax_amount=calculated.tax_amount,
        )
        for index, calculated in enumerate(calculation.lines, start=1)
    ]
    return document, lines


def _establishment_and_point() -> tuple[Establishment, EmissionPoint]:
    establishment = Establishment(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        code="001",
        name="Matriz",
        address="Av. Siempre Viva 123",
        active=True,
    )
    emission_point = EmissionPoint(
        id=uuid.uuid4(),
        tenant_id=establishment.tenant_id,
        establishment_id=establishment.id,
        code="001",
        active=True,
    )
    return establishment, emission_point


def _buyer(identification_type: str = "CEDULA") -> Party:
    return Party(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        name="Cliente Facturable",
        identification_type=identification_type,
        identification_number="1790000001",
        roles=["CUSTOMER"],
        email=None,
        phone=None,
        address=None,
        active=True,
    )


def test_build_invoice_xml_requires_access_key() -> None:
    document, lines = _build_document_and_lines(access_key=None)
    establishment, emission_point = _establishment_and_point()
    with pytest.raises(ValueError, match="access key"):
        build_invoice_xml(
            document=document,
            lines=lines,
            establishment=establishment,
            emission_point=emission_point,
            tenant_ruc="1799999999001",
            tenant_legal_name="IAERP Demo S.A.",
            tenant_commercial_address="Av. Amazonas N30",
            buyer=_buyer(),
        )


def test_build_invoice_xml_rejects_credit_note_document() -> None:
    document, lines = _build_document_and_lines(document_type="CREDIT_NOTE")
    establishment, emission_point = _establishment_and_point()
    with pytest.raises(ValueError, match="INVOICE"):
        build_invoice_xml(
            document=document,
            lines=lines,
            establishment=establishment,
            emission_point=emission_point,
            tenant_ruc="1799999999001",
            tenant_legal_name="IAERP Demo S.A.",
            tenant_commercial_address="Av. Amazonas N30",
            buyer=_buyer(),
        )


def test_invoice_xml_structure_and_adr_0008_vector_3_rounding() -> None:
    document, lines = _build_document_and_lines()
    establishment, emission_point = _establishment_and_point()
    buyer = _buyer()

    result = build_invoice_xml(
        document=document,
        lines=lines,
        establishment=establishment,
        emission_point=emission_point,
        tenant_ruc="1799999999001",
        tenant_legal_name="IAERP Demo S.A.",
        tenant_commercial_address="Av. Amazonas N30",
        buyer=buyer,
    )

    root = result.root
    assert root.tag == "factura"
    assert root.get("version") == "1.1.0"

    info_tributaria = root.find("infoTributaria")
    assert info_tributaria is not None
    assert info_tributaria.findtext("claveAcceso") == document.access_key
    assert info_tributaria.findtext("ruc") == "1799999999001"
    assert info_tributaria.findtext("estab") == "001"
    assert info_tributaria.findtext("ptoEmi") == "001"
    assert info_tributaria.findtext("secuencial") == "000000001"
    assert info_tributaria.findtext("codDoc") == "01"

    info_factura = root.find("infoFactura")
    assert info_factura is not None
    assert info_factura.findtext("fechaEmision") == "04/07/2026"
    assert info_factura.findtext("razonSocialComprador") == "Cliente Facturable"
    assert info_factura.findtext("identificacionComprador") == "1790000001"

    # ADR 0008 vector 3: precioTotalSinImpuesto por linea 1.05, informativo
    # 0.16 por linea, pero el totalImpuesto de grupo es 0.47 (no 0.48).
    assert info_factura.findtext("totalSinImpuestos") == "3.15"
    assert info_factura.findtext("importeTotal") == "3.62"

    total_impuestos = info_factura.findall("totalConImpuestos/totalImpuesto")
    assert len(total_impuestos) == 1
    assert total_impuestos[0].findtext("baseImponible") == "3.15"
    assert total_impuestos[0].findtext("valor") == "0.47"
    assert total_impuestos[0].findtext("codigoPorcentaje") == "4"

    detalles = root.findall("detalles/detalle")
    assert len(detalles) == 3
    for detalle in detalles:
        assert detalle.findtext("cantidad") == "1.000000"
        assert detalle.findtext("precioUnitario") == "1.050000"
        assert detalle.findtext("precioTotalSinImpuesto") == "1.05"
        assert detalle.findtext("impuestos/impuesto/valor") == "0.16"

    # El XML serializado debe ser bien formado y contener la clave de acceso.
    parsed = etree.fromstring(result.xml_bytes)
    assert parsed.findtext("infoTributaria/claveAcceso") == document.access_key


def test_invoice_xml_final_consumer_uses_generic_identification() -> None:
    document, lines = _build_document_and_lines()
    establishment, emission_point = _establishment_and_point()
    buyer = _buyer(identification_type="FINAL_CONSUMER")

    result = build_invoice_xml(
        document=document,
        lines=lines,
        establishment=establishment,
        emission_point=emission_point,
        tenant_ruc="1799999999001",
        tenant_legal_name="IAERP Demo S.A.",
        tenant_commercial_address="Av. Amazonas N30",
        buyer=buyer,
    )
    info_factura = result.root.find("infoFactura")
    assert info_factura is not None
    assert info_factura.findtext("identificacionComprador") == "9999999999999"
    assert info_factura.findtext("tipoIdentificacionComprador") == "07"


def test_build_credit_note_xml_structure() -> None:
    document, lines = _build_document_and_lines(document_type="CREDIT_NOTE")
    establishment, emission_point = _establishment_and_point()
    buyer = _buyer()

    result = build_credit_note_xml(
        document=document,
        lines=lines,
        establishment=establishment,
        emission_point=emission_point,
        tenant_ruc="1799999999001",
        tenant_legal_name="IAERP Demo S.A.",
        tenant_commercial_address="Av. Amazonas N30",
        buyer=buyer,
        related_invoice_sequential_full="001-001-000000042",
        related_invoice_issue_date=date(2024, 3, 15),
        related_invoice_access_key="1" * 49,
        reason="Devolucion parcial",
    )

    root = result.root
    assert root.tag == "notaCredito"
    info_nc = root.find("infoNotaCredito")
    assert info_nc is not None
    assert info_nc.findtext("codDocModificado") == "01"
    assert info_nc.findtext("numDocModificado") == "001-001-000000042"
    assert info_nc.findtext("fechaEmisionDocSustento") == "15/03/2024"
    assert info_nc.findtext("valorModificacion") == "3.62"
    assert info_nc.findtext("motivo") == "Devolucion parcial"

    total_impuestos = info_nc.findall("totalConImpuestos/totalImpuesto")
    assert len(total_impuestos) == 1
    assert total_impuestos[0].findtext("valor") == "0.47"


def test_build_credit_note_xml_rejects_invoice_document() -> None:
    document, lines = _build_document_and_lines(document_type="INVOICE")
    establishment, emission_point = _establishment_and_point()
    with pytest.raises(ValueError, match="CREDIT_NOTE"):
        build_credit_note_xml(
            document=document,
            lines=lines,
            establishment=establishment,
            emission_point=emission_point,
            tenant_ruc="1799999999001",
            tenant_legal_name="IAERP Demo S.A.",
            tenant_commercial_address="Av. Amazonas N30",
            buyer=_buyer(),
            related_invoice_sequential_full="001-001-000000042",
            related_invoice_issue_date=date(2024, 3, 15),
            related_invoice_access_key="1" * 49,
            reason="Devolucion",
        )


def test_mixed_tax_groups_produce_multiple_total_impuesto_entries() -> None:
    """Vector 5 del ADR 0008 (mezcla de tarifas) genera un grupo por tarifa."""

    tenant_id = uuid.uuid4()
    document_id = uuid.uuid4()
    line_inputs = [
        LineInput(
            quantity=Decimal("1"),
            unit_price=Decimal("100.00"),
            discount=Decimal("0.00"),
            tax_rate=Decimal("15"),
            tax_sri_code="4",
        ),
        LineInput(
            quantity=Decimal("2"),
            unit_price=Decimal("25.00"),
            discount=Decimal("0.00"),
            tax_rate=Decimal("0"),
            tax_sri_code="0",
        ),
        LineInput(
            quantity=Decimal("10"),
            unit_price=Decimal("8.457"),
            discount=Decimal("0.00"),
            tax_rate=Decimal("5"),
            tax_sri_code="5",
        ),
    ]
    calculation = FISCAL_POLICY_V1.calculate_document(line_inputs)
    document = SalesDocument(
        id=document_id,
        tenant_id=tenant_id,
        document_type="INVOICE",
        establishment_id=uuid.uuid4(),
        emission_point_id=uuid.uuid4(),
        sequential="000000002",
        access_key="2" * 49,
        party_id=uuid.uuid4(),
        issue_date=date(2026, 7, 4),
        status="SIGNED",
        currency="USD",
        subtotal=calculation.subtotal,
        tax_total=calculation.tax_total,
        total=calculation.total,
        fiscal_policy_version=FISCAL_POLICY_V1.version,
        reason=None,
    )
    lines = [
        SalesDocumentLine(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            sales_document_id=document_id,
            line_number=index,
            product_id=None,
            description=f"Linea {index}",
            quantity=calculated.quantity,
            unit_price=calculated.unit_price,
            discount=calculated.discount,
            base_amount=calculated.base_amount,
            tax_sri_code=calculated.tax_sri_code,
            tax_rate=calculated.tax_rate,
            tax_amount=calculated.tax_amount,
        )
        for index, calculated in enumerate(calculation.lines, start=1)
    ]
    establishment, emission_point = _establishment_and_point()

    result = build_invoice_xml(
        document=document,
        lines=lines,
        establishment=establishment,
        emission_point=emission_point,
        tenant_ruc="1799999999001",
        tenant_legal_name="IAERP Demo S.A.",
        tenant_commercial_address="Av. Amazonas N30",
        buyer=_buyer(),
    )
    info_factura = result.root.find("infoFactura")
    assert info_factura is not None
    assert info_factura.findtext("importeTotal") == "253.80"
    total_impuestos = info_factura.findall("totalConImpuestos/totalImpuesto")
    assert len(total_impuestos) == 3
    values_by_code = {
        entry.findtext("codigoPorcentaje"): entry.findtext("valor") for entry in total_impuestos
    }
    assert values_by_code == {"4": "15.00", "0": "0.00", "5": "4.23"}
