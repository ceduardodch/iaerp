"""Pruebas del RIDE PDF: no vacio y con la clave de acceso presente en el texto.

Usa ``pypdf`` (dev-dependency) para extraer el texto del PDF generado y
verificar que los mismos datos que el XML (clave de acceso, totales) aparecen
en el documento, confirmando que ambos artefactos no pueden divergir porque
parten de los mismos campos persistidos en ``SalesDocument``/``SalesDocumentLine``.
"""

import io
import uuid
from datetime import date
from decimal import Decimal

import pytest
from pypdf import PdfReader

from app.models.billing import SalesDocument, SalesDocumentLine
from app.models.masters import EmissionPoint, Establishment, Party
from app.services.access_key import AccessKeyInput, build_access_key
from app.services.fiscal_policy import FISCAL_POLICY_V1, LineInput
from app.services.ride import build_ride_pdf

_ACCESS_KEY = build_access_key(
    AccessKeyInput(
        issue_date=date(2026, 7, 4),
        document_code="01",
        ruc="1799999999001",
        environment="1",
        establishment_code="001",
        emission_point_code="001",
        sequential="000000001",
        numeric_code="12345678",
    )
)


_FixtureTuple = tuple[SalesDocument, list[SalesDocumentLine], Establishment, EmissionPoint, Party]


def _build_fixture() -> _FixtureTuple:
    tenant_id = uuid.uuid4()
    document_id = uuid.uuid4()

    line_inputs = [
        LineInput(
            quantity=Decimal("2"),
            unit_price=Decimal("50.00"),
            discount=Decimal("0.00"),
            tax_rate=Decimal("15"),
            tax_sri_code="4",
        )
    ]
    calculation = FISCAL_POLICY_V1.calculate_document(line_inputs)

    document = SalesDocument(
        id=document_id,
        tenant_id=tenant_id,
        document_type="INVOICE",
        establishment_id=uuid.uuid4(),
        emission_point_id=uuid.uuid4(),
        sequential="000000001",
        access_key=_ACCESS_KEY,
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
            description="Consultoria julio",
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
    establishment = Establishment(
        id=document.establishment_id,
        tenant_id=tenant_id,
        code="001",
        name="Matriz",
        address="Av. Siempre Viva 123",
        active=True,
    )
    emission_point = EmissionPoint(
        id=document.emission_point_id,
        tenant_id=tenant_id,
        establishment_id=establishment.id,
        code="001",
        active=True,
    )
    buyer = Party(
        id=document.party_id,
        tenant_id=tenant_id,
        name="Cliente Facturable",
        identification_type="CEDULA",
        identification_number="1790000001",
        roles=["CUSTOMER"],
        email=None,
        phone=None,
        address=None,
        active=True,
    )
    return document, lines, establishment, emission_point, buyer


def _extract_text(pdf_bytes: bytes) -> str:
    reader = PdfReader(io.BytesIO(pdf_bytes))
    return "\n".join(page.extract_text() for page in reader.pages)


def test_build_ride_pdf_requires_access_key() -> None:
    document, lines, establishment, emission_point, buyer = _build_fixture()
    document.access_key = None
    with pytest.raises(ValueError, match="access key"):
        build_ride_pdf(
            document=document,
            lines=lines,
            establishment=establishment,
            emission_point=emission_point,
            tenant_ruc="1799999999001",
            tenant_legal_name="IAERP Demo S.A.",
            buyer=buyer,
        )


def test_build_ride_pdf_is_not_empty_and_contains_access_key() -> None:
    document, lines, establishment, emission_point, buyer = _build_fixture()

    pdf_bytes = build_ride_pdf(
        document=document,
        lines=lines,
        establishment=establishment,
        emission_point=emission_point,
        tenant_ruc="1799999999001",
        tenant_legal_name="IAERP Demo S.A.",
        buyer=buyer,
    )

    assert len(pdf_bytes) > 0
    assert pdf_bytes.startswith(b"%PDF")

    text = _extract_text(pdf_bytes)
    assert document.access_key in text.replace(" ", "")
    assert "1799999999001" in text
    assert "Cliente Facturable" in text
    assert "115.00" in text  # importeTotal, mismo dato que el XML
    assert "001-001-000000001" in text


def test_build_ride_pdf_reflects_same_totals_as_document_without_recalculating() -> None:
    document, lines, establishment, emission_point, buyer = _build_fixture()
    pdf_bytes = build_ride_pdf(
        document=document,
        lines=lines,
        establishment=establishment,
        emission_point=emission_point,
        tenant_ruc="1799999999001",
        tenant_legal_name="IAERP Demo S.A.",
        buyer=buyer,
    )
    text = _extract_text(pdf_bytes)
    assert "100.00" in text  # subtotal
    assert "15.00" in text  # tax_total
