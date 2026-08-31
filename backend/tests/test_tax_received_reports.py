"""Flujo diario de reportes recibidos: REST y caso de uso compartido."""

from datetime import date

import pytest
from sqlalchemy import func, select

from app.db.session import SessionFactory
from app.models.platform import OutboxEvent
from app.models.tax import FiscalDocument
from app.services import access_key, storage
from app.services.tax import evidence as evidence_service
from app.services.tax import received_reports
from tests.test_tax_foundation import TENANT_A, TENANT_B, auth, token_for

REPORT_DATE = date(2026, 8, 30)
TAX_SCOPES = ["tax:read", "tax:write"]


@pytest.fixture
def stored_objects(monkeypatch) -> dict[str, bytes]:
    objects: dict[str, bytes] = {}

    async def upload(*, object_key: str, data: bytes, **_kwargs) -> None:
        objects[object_key] = data

    async def download(*, object_key: str) -> bytes:
        return objects[object_key]

    monkeypatch.setattr(evidence_service.storage, "upload_private_object", upload)
    monkeypatch.setattr(storage, "download_artifact", download)
    return objects


def _key(*, document_code: str, sequential: int, issue_date: date = REPORT_DATE) -> str:
    return access_key.build_access_key(
        access_key.AccessKeyInput(
            issue_date=issue_date,
            document_code=document_code,
            ruc="1790000000001",
            environment=access_key.ENVIRONMENT_PRODUCTION,
            establishment_code="001",
            emission_point_code="002",
            sequential=f"{sequential:09d}",
            numeric_code=f"{sequential:08d}",
        )
    )


def _report(
    *,
    label: str = "Factura",
    document_code: str = access_key.INVOICE_DOCUMENT_CODE,
    sequential: int = 1,
    issue_date: date = REPORT_DATE,
) -> bytes:
    key = _key(
        document_code=document_code,
        sequential=sequential,
        issue_date=issue_date,
    )
    formatted = issue_date.strftime("%d/%m/%Y")
    content = (
        "RUC_EMISOR\tRAZON_SOCIAL_EMISOR\tTIPO_COMPROBANTE\tSERIE_COMPROBANTE\t"
        "CLAVE_ACCESO\tFECHA_AUTORIZACION\tFECHA_EMISION\tIDENTIFICACION_RECEPTOR\t"
        "VALOR_SIN_IMPUESTOS\tIVA\tIMPORTE_TOTAL\tNUMERO_DOCUMENTO_MODIFICADO\n"
        f"1790000000001\tPROVEEDOR DEMO\t{label}\t001-002-{sequential:09d}\t"
        f"{key}\t{formatted}\t{formatted}\t1799999999001\t10.00\t1.50\t11.50\t\n"
    )
    return content.encode("iso-8859-1")


async def _upload(client, token: str, filename: str, content: bytes) -> str:
    response = await client.post(
        "/api/v1/tax/evidence",
        headers=auth(token, f"upload-{filename}-0001"),
        files={"file": (filename, content, "text/plain")},
        data={"origin": "PORTAL_SRI"},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def test_process_received_reports_imports_all_types_and_queues_one_recovery(
    client,
    stored_objects,
) -> None:
    token = await token_for(client, "a@iaerp.local", TENANT_A, TAX_SCOPES)
    invoice_id = await _upload(client, token, "facturas.txt", _report())
    credit_note_id = await _upload(
        client,
        token,
        "notas.txt",
        _report(
            label="Nota de crédito",
            document_code=access_key.CREDIT_NOTE_DOCUMENT_CODE,
            sequential=2,
        ),
    )
    payload = {
        "evidenceIds": [invoice_id, credit_note_id],
        "reportDate": REPORT_DATE.isoformat(),
    }

    response = await client.post(
        "/api/v1/tax/received-reports/process",
        headers=auth(token, "received-reports-20260830"),
        json=payload,
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["evidenceCount"] == 2
    assert body["listedRows"] == 2
    assert body["documentTypes"] == {"FACTURA": 1, "NOTA_CREDITO": 1}
    assert body["created"] == 2
    assert body["preliminary"] == 2
    assert body["recoveryJob"]["status"] == "QUEUED"
    assert body["recoveryJob"]["totalCount"] == 2

    replay = await client.post(
        "/api/v1/tax/received-reports/process",
        headers=auth(token, "received-reports-20260830"),
        json=payload,
    )
    assert replay.status_code == 201
    assert replay.json() == body

    async with SessionFactory() as session:
        document_count = await session.scalar(select(func.count()).select_from(FiscalDocument))
        recovery_events = await session.scalar(
            select(func.count())
            .select_from(OutboxEvent)
            .where(OutboxEvent.event_type == "tax.xml_recovery.requested")
        )
    assert document_count == 2
    assert recovery_events == 1


async def test_process_received_reports_rejects_a_row_from_another_day_without_writes(
    client,
    stored_objects,
) -> None:
    token = await token_for(client, "a@iaerp.local", TENANT_A, TAX_SCOPES)
    evidence_id = await _upload(
        client,
        token,
        "fecha-errada.txt",
        _report(issue_date=date(2026, 8, 29)),
    )
    response = await client.post(
        "/api/v1/tax/received-reports/process",
        headers=auth(token, "received-reports-wrong-date"),
        json={"evidenceIds": [evidence_id], "reportDate": REPORT_DATE.isoformat()},
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "Every report row must match reportDate"

    async with SessionFactory() as session:
        count = await session.scalar(select(func.count()).select_from(FiscalDocument))
    assert count == 0


async def test_process_received_reports_is_tenant_scoped(client, stored_objects) -> None:
    token_a = await token_for(client, "a@iaerp.local", TENANT_A, TAX_SCOPES)
    token_b = await token_for(client, "b@iaerp.local", TENANT_B, TAX_SCOPES)
    evidence_id = await _upload(client, token_a, "tenant-a.txt", _report())

    response = await client.post(
        "/api/v1/tax/received-reports/process",
        headers=auth(token_b, "received-reports-tenant-b"),
        json={"evidenceIds": [evidence_id], "reportDate": REPORT_DATE.isoformat()},
    )
    assert response.status_code == 404


async def test_process_received_reports_rejects_duplicate_evidence_ids(
    client,
    stored_objects,
) -> None:
    token = await token_for(client, "a@iaerp.local", TENANT_A, TAX_SCOPES)
    evidence_id = await _upload(client, token, "duplicate.txt", _report())
    response = await client.post(
        "/api/v1/tax/received-reports/process",
        headers=auth(token, "received-reports-duplicate"),
        json={
            "evidenceIds": [evidence_id, evidence_id],
            "reportDate": REPORT_DATE.isoformat(),
        },
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "Evidence IDs must be unique"


async def test_service_limit_matches_the_five_sri_report_types() -> None:
    assert received_reports.MAX_DAILY_REPORTS == 5
