"""Generacion del ATS (E4) y formato de importes.

El orden de nodos y las reglas verificadas aqui salen de dos ATS **aceptados**
por el SRI (2025-07 y 2026-04) entregados por el usuario, y de los rechazos que
sufrio antes: mes sin cero inicial, falta de `tipoEmision`, `numeroComprobantes`
fuera de lugar, forma de pago ausente sobre el umbral y ZIP con archivos extra.
"""

import io
import zipfile
from decimal import Decimal
from xml.etree.ElementTree import fromstring

import pytest

from app.services.tax.ats import (
    AtsInput,
    AtsPurchase,
    AtsSale,
    ats_filename,
    build_ats_xml,
    build_ats_zip,
    format_month,
    validate_ats_zip,
)
from app.services.tax.formatting import format_amount


def sample_input() -> AtsInput:
    return AtsInput(
        identification="0777777777001",
        legal_name="EMPRESA DEMO S.A.S.",
        year=2026,
        month=4,
        purchases=[
            AtsPurchase(
                supplier_identification="0999999999001",
                establishment="001",
                emission_point="010",
                sequential="000008603",
                issue_date="19/04/2026",
                registration_date="19/04/2026",
                authorization="1904202601099999999900120010100000086031234567818",
                base_zero_rate=Decimal("522.89"),
                payment_methods=["20"],
            ),
            AtsPurchase(
                supplier_identification="0888888888001",
                establishment="001",
                emission_point="002",
                sequential="000019877",
                issue_date="04/04/2026",
                registration_date="04/04/2026",
                authorization="0404202601088888888800120010020000198772795205918",
                base_taxed=Decimal("13.13"),
                iva_amount=Decimal("1.97"),
            ),
        ],
        sales=[
            AtsSale(
                customer_identification="0666666666001",
                base_taxed=Decimal("1836.00"),
                iva_amount=Decimal("275.40"),
                withheld_iva=Decimal("192.78"),
                withheld_income_tax=Decimal("50.49"),
                payment_methods=["01"],
            )
        ],
    )


def parse(xml_bytes: bytes):
    return fromstring(xml_bytes)


def child_tags(node) -> list[str]:
    return [child.tag for child in node]


def test_month_always_has_two_digits() -> None:
    # Rechazo conocido: el SRI espera "01", nunca "1".
    assert format_month(1) == "01"
    assert format_month(4) == "04"
    assert format_month(12) == "12"


def test_root_and_header_order_match_accepted_ats() -> None:
    root = parse(build_ats_xml(sample_input()))

    # La raiz del ATS es <iva> (el ADI usa <adi>).
    assert root.tag == "iva"
    # razonSocial va ANTES de Anio/Mes, y la etiqueta lleva "ID" en mayuscula.
    assert child_tags(root)[:8] == [
        "TipoIDInformante",
        "IdInformante",
        "razonSocial",
        "Anio",
        "Mes",
        "numEstabRuc",
        "totalVentas",
        "codigoOperativo",
    ]
    assert root.findtext("Mes") == "04"
    assert root.findtext("codigoOperativo") == "IVA"


def test_sales_detail_puts_emission_type_before_document_count() -> None:
    root = parse(build_ats_xml(sample_input()))
    sale = root.find("ventas/detalleVentas")
    assert sale is not None

    tags = child_tags(sale)
    # Dos rechazos conocidos: falta `tipoEmision` y `numeroComprobantes` mal ubicado.
    assert "tipoEmision" in tags
    assert tags.index("tipoEmision") < tags.index("numeroComprobantes")
    assert tags[:6] == [
        "tpIdCliente",
        "idCliente",
        "parteRelVtas",
        "tipoComprobante",
        "tipoEmision",
        "numeroComprobantes",
    ]
    assert sale.findtext("valorRetIva") == "192.78"
    assert sale.findtext("valorRetRenta") == "50.49"


def test_purchase_over_threshold_declares_payment_method() -> None:
    root = parse(build_ats_xml(sample_input()))
    purchases = root.findall("compras/detalleCompras")

    over_threshold = purchases[0]
    under_threshold = purchases[1]

    # Rechazo conocido: falta forma de pago cuando el total supera el umbral.
    assert over_threshold.find("formasDePago") is not None
    assert over_threshold.findtext("formasDePago/formaPago") == "20"
    assert under_threshold.find("formasDePago") is None


@pytest.mark.parametrize(
    ("base", "iva", "expected"),
    [
        ("128.00", "19.20", False),
        ("434.78", "65.22", False),
        ("434.79", "65.22", True),
        ("500.01", "0.00", True),
    ],
)
def test_purchase_payment_block_respects_threshold_without_losing_source(
    base: str, iva: str, expected: bool,
) -> None:
    data = sample_input()
    purchase = data.purchases[0]
    purchase.base_zero_rate = Decimal("0.00")
    purchase.base_taxed = Decimal(base)
    purchase.iva_amount = Decimal(iva)
    purchase.payment_methods = ["20"]
    data.purchases = [purchase]

    root = parse(build_ats_xml(data))

    block = root.find("compras/detalleCompras/formasDePago")
    assert (block is not None) is expected
    if expected:
        assert block.findtext("formaPago") == "20"
    assert purchase.payment_methods == ["20"]
    assert root.findtext("compras/detalleCompras/baseImpGrav") == base
    assert root.findtext("compras/detalleCompras/montoIva") == iva
    # Las ventas no usan el umbral de compras.
    assert root.findtext("ventas/detalleVentas/formasDePago/formaPago") == "01"


def test_sale_keeps_authorized_fifteen_percent_iva() -> None:
    data = sample_input()
    data.year, data.month = 2026, 7
    data.sales[0].base_taxed = Decimal("1001.23")
    data.sales[0].iva_amount = Decimal("150.18")

    root = parse(build_ats_xml(data))

    assert root.findtext("ventas/detalleVentas/baseImpGrav") == "1001.23"
    assert root.findtext("ventas/detalleVentas/montoIva") == "150.18"


def test_amounts_use_two_decimals_and_no_thousand_separator() -> None:
    root = parse(build_ats_xml(sample_input()))

    assert root.findtext("totalVentas") == "1836.00"
    assert root.findtext("compras/detalleCompras/baseImponible") == "522.89"
    assert format_amount(Decimal("1234.5")) == "1234.50"
    assert format_amount(1234567.891) == "1234567.89"
    assert "," not in format_amount(Decimal("1234567.89"))


def test_zip_contains_exactly_one_xml_at_root() -> None:
    data = sample_input()
    xml_bytes = build_ats_xml(data)
    filename = ats_filename(data)
    assert filename == "AT042026.xml"

    zip_bytes = build_ats_zip(xml_bytes, filename=filename)
    archive = zipfile.ZipFile(io.BytesIO(zip_bytes))

    assert archive.namelist() == [filename]
    assert validate_ats_zip(zip_bytes) == []


def test_validator_detects_macos_metadata_that_sri_rejects() -> None:
    # Comprimir desde el Finder agrega __MACOSX/._archivo.xml y el SRI lo rechaza;
    # ocurrio con un ZIP real del usuario.
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("AT112025.xml", b"<iva/>")
        archive.writestr("__MACOSX/._AT112025.xml", b"metadata")

    problems = validate_ats_zip(buffer.getvalue())
    assert problems
    assert any("__MACOSX" in problem for problem in problems)


def test_validator_detects_multiple_xml_at_root() -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("AT112025.xml", b"<iva/>")
        archive.writestr("AT122025.xml", b"<iva/>")

    problems = validate_ats_zip(buffer.getvalue())
    assert any("exactamente un XML" in problem for problem in problems)

@pytest.mark.parametrize(
    ("exempt", "ice", "expected"),
    [("500.00", "0.00", False), ("500.01", "0.00", True),
     ("450.00", "50.00", False), ("450.00", "50.01", True)],
)
def test_purchase_threshold_includes_exempt_base_and_ice(
    exempt: str, ice: str, expected: bool,
) -> None:
    data = sample_input()
    purchase = data.purchases[0]
    purchase.base_zero_rate = Decimal("0.00")
    purchase.base_exempt = Decimal(exempt)
    purchase.ice_amount = Decimal(ice)
    purchase.payment_methods = ["20"]
    data.purchases = [purchase]

    root = parse(build_ats_xml(data))

    assert (root.find("compras/detalleCompras/formasDePago") is not None) is expected
    assert root.findtext("compras/detalleCompras/baseImpExe") == exempt
    assert root.findtext("compras/detalleCompras/montoIce") == ice
