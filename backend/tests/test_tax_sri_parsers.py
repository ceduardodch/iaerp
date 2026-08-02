"""Lectura de comprobantes y listados del SRI (E2).

Los fixtures replican la estructura de archivos REALES descargados del portal
(anonimizados): el sobre `<autorizacion>` con CDATA, y el TXT separado por
tabuladores en ISO-8859-1.
"""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi import HTTPException

from app.services.tax.sri_xml import parse_authorized_document
from app.services.tax.txt_import import decode_portal_text, parse_received_txt

FIXTURES = Path(__file__).parent / "fixtures" / "sri"


def read_fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def test_parses_invoice_with_zero_rated_iva() -> None:
    document = parse_authorized_document(read_fixture("factura_recibida_autorizada.xml"))

    assert document.doc_type == "FACTURA"
    # La fecha viene del comprobante (dd/mm/yyyy), no del nombre del archivo.
    assert document.issue_date == date(2025, 11, 30)
    assert document.issuer_identification == "0999999999001"
    assert document.receiver_identification == "0777777777001"
    assert document.establishment_code == "001"
    assert document.emission_point_code == "010"
    assert document.sequential == "000007956"
    assert document.subtotal == Decimal("276.3")
    assert document.total == Decimal("276.3")
    assert document.payment_methods == ["20"]

    assert len(document.taxes) == 1
    tax = document.taxes[0]
    # codigoPorcentaje 0 = tarifa 0%: es base sin IVA, no una compra gravada.
    assert tax.sri_tax_code == "0"
    assert tax.tax_bracket == "TARIFA_CERO"
    assert tax.base_amount == Decimal("276.3")
    assert tax.tax_amount == Decimal("0")


def test_parses_invoice_with_iva_15() -> None:
    document = parse_authorized_document(read_fixture("factura_recibida_iva15.xml"))

    assert document.issue_date == date(2025, 11, 11)
    assert document.subtotal == Decimal("13.13")
    assert document.tax_total == Decimal("1.97")
    assert document.total == Decimal("15.10")
    assert document.payment_methods == ["20"]

    tax = document.taxes[0]
    assert tax.sri_tax_code == "4"
    assert tax.tax_bracket == "GRAVADO"
    assert tax.rate == Decimal("15.00")
    assert tax.base_amount == Decimal("13.13")
    assert tax.tax_amount == Decimal("1.97")


def test_parses_retention_separating_iva_from_renta() -> None:
    document = parse_authorized_document(read_fixture("retencion_recibida_autorizada.xml"))

    assert document.doc_type == "RETENCION"
    assert document.issue_date == date(2025, 11, 10)
    assert document.issuer_identification == "0666666666001"

    kinds = {item.kind: item for item in document.retentions}
    assert set(kinds) == {"IVA", "RENTA"}

    # Regla del ADR 0012: el 609 del formulario 104 es SOLO la retencion de IVA.
    iva = kinds["IVA"]
    assert iva.sri_code == "2"
    assert iva.percentage == Decimal("70.00")
    assert iva.base_amount == Decimal("46.86")
    assert iva.retained_amount == Decimal("32.80")

    renta = kinds["RENTA"]
    assert renta.sri_code == "3440"
    assert renta.percentage == Decimal("2.75")
    assert renta.retained_amount == Decimal("8.59")

    # El documento sustento permite conciliar el cobro de la factura.
    assert iva.supporting_document_number == "001001000000045"
    assert document.total == Decimal("41.39")


def test_rejects_document_that_is_not_authorized() -> None:
    xml = read_fixture("factura_recibida_autorizada.xml").replace(
        b"<estado>AUTORIZADO</estado>", b"<estado>NO AUTORIZADO</estado>"
    )
    with pytest.raises(HTTPException) as error:
        parse_authorized_document(xml)
    assert error.value.status_code == 422


def test_rejects_xml_without_authorization_envelope() -> None:
    with pytest.raises(HTTPException) as error:
        parse_authorized_document(b"<factura><infoTributaria/></factura>")
    assert error.value.status_code == 422


def test_portal_txt_is_decoded_as_latin1() -> None:
    # El export real del portal NO es UTF-8: si se asume UTF-8 falla o corrompe.
    raw = read_fixture("recibidos_portal.txt")
    with pytest.raises(UnicodeDecodeError):
        raw.decode("utf-8")
    assert "Retención" in decode_portal_text(raw)


def test_txt_rows_use_real_issue_date_not_folder_name() -> None:
    # El archivo real venia en una carpeta "Diciembre 2025" con comprobantes
    # emitidos en NOVIEMBRE: el periodo debe salir de la fecha del comprobante.
    rows = parse_received_txt(read_fixture("recibidos_portal.txt"))
    invoices = [row for row in rows if row.doc_type == "FACTURA"]

    assert [row.issue_date for row in invoices] == [date(2025, 11, 11), date(2025, 11, 30)]
    assert all(row.issue_date.month == 11 for row in invoices)


def test_txt_invoice_values_are_read() -> None:
    rows = parse_received_txt(read_fixture("recibidos_portal.txt"))
    invoice = next(row for row in rows if row.access_key.endswith("2795212911"))

    assert invoice.subtotal == Decimal("13.13")
    assert invoice.tax_total == Decimal("1.97")
    assert invoice.total == Decimal("15.1")
    assert invoice.is_preliminary is False


def test_txt_retention_without_values_is_marked_preliminary() -> None:
    rows = parse_received_txt(read_fixture("recibidos_portal.txt"))
    retention = next(row for row in rows if row.doc_type == "RETENCION")

    # El portal no entrega los valores de la retencion en el TXT: no se inventan.
    assert retention.subtotal is None
    assert retention.total is None
    assert retention.is_preliminary is True
    assert retention.preliminary_reason is not None
    assert "XML" in retention.preliminary_reason
    assert retention.modified_document == "26041039465"


def test_txt_rejects_unrelated_file() -> None:
    with pytest.raises(HTTPException) as error:
        parse_received_txt(b"columna1\tcolumna2\nvalor1\tvalor2\n")
    assert error.value.status_code == 422
