from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.db.session import SessionFactory
from app.models.billing import DocumentArtifact, SalesDocument, Sequence
from app.models.receivables import Receivable, ReceivableInstallment
from app.services import sky_franquicia_migration as migration
from app.services.storage import UploadResult
from tests.conftest import TENANT_A


def _row(*, xml: str | None = "<factura/>") -> dict[str, object]:
    return {
        "id": "00000000-0000-4000-8000-000000000001",
        "status": "AUTHORIZED",
        "establishment": "001",
        "emission_point": "001",
        "sequential": "000000123",
        "issue_date": date(2026, 7, 17),
        "subtotal_15": "100.00",
        "subtotal_0": "0.00",
        "discount": "0.00",
        "tax": "15.00",
        "total": "115.00",
        "sri_access_key": "1" * 49,
        "sri_auth_code": "1" * 49,
        "sri_authorization_date": "2026-07-17T12:00:00-05:00",
        "sri_xml": xml,
        "customer_name": "Cliente migrado",
        "customer_document_type": "05",
        "customer_document_number": "1712345678",
        "customer_email": "cliente@example.test",
        "customer_phone": None,
        "customer_address": None,
        "franchise_name": "BTOB matriz",
        "franchise_location": "Quito",
        "line_count": 1,
        "line_subtotal": "100.00",
        "lines": [
            {
                "description": "Servicio historico",
                "quantity": "1",
                "unit_price": "100.00",
                "discount": "0.00",
                "total": "100.00",
                "is_taxable": True,
            }
        ],
    }


@pytest.mark.asyncio
async def test_load_authorized_invoice_creates_document_artifact_and_receivable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = _row()

    async def fake_extract(**_kwargs: object) -> list[dict[str, object]]:
        return [row]

    async def fake_upload(**kwargs: object) -> UploadResult:
        assert kwargs["artifact_type"] == "xml-signed"
        assert kwargs["data"] == b"<factura/>"
        return UploadResult(object_key="tenant/document.xml", sha256="a" * 64, size_bytes=10)

    monkeypatch.setattr(migration, "extract_authorized_source_invoices", fake_extract)
    monkeypatch.setattr(migration.storage, "upload_artifact", fake_upload)  # type: ignore[attr-defined]

    async with SessionFactory() as session:
        result = await migration.load_authorized_invoices(
            session=session,
            source_url="postgresql+asyncpg://not-used",
            ruc="1799999999001",
            tenant_id=str(TENANT_A),
        )
        assert result["loaded"] == 1
        assert result["skipped"] == []

    async with SessionFactory() as session:
        document = await session.scalar(select(SalesDocument))
        assert document is not None
        assert document.status == "AUTHORIZED"
        assert document.total == Decimal("115.00")
        assert document.access_key == "1" * 49
        assert await session.scalar(select(func.count()).select_from(DocumentArtifact)) == 1
        receivable = await session.scalar(select(Receivable))
        assert receivable is not None
        assert receivable.original_amount == Decimal("115.00")
        installment = await session.scalar(select(ReceivableInstallment))
        assert installment is not None
        assert installment.due_date == date(2026, 7, 17)
        sequence = await session.scalar(select(Sequence))
        assert sequence is not None
        assert sequence.next_value == 124


@pytest.mark.asyncio
async def test_loader_skips_authorized_invoice_without_artifacts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_extract(**_kwargs: object) -> list[dict[str, object]]:
        return [_row(xml=None)]

    monkeypatch.setattr(migration, "extract_authorized_source_invoices", fake_extract)

    async with SessionFactory() as session:
        result = await migration.load_authorized_invoices(
            session=session,
            source_url="postgresql+asyncpg://not-used",
            ruc="1799999999001",
            tenant_id=str(TENANT_A),
        )
        assert result["loaded"] == 0
        assert result["skipped"][0]["reason"] == "AUTHORIZED_ARTIFACT_GAP"

    async with SessionFactory() as session:
        assert await session.scalar(select(func.count()).select_from(SalesDocument)) == 0
