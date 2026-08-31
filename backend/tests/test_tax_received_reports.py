"""Flujo mensual de reportes recibidos: REST y caso de uso compartido."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.db.session import SessionFactory
from app.models.platform import AutomationSettings, OutboxEvent, Tenant
from app.models.tax import FiscalDocument
from app.services import access_key, storage
from app.services.tax import evidence as evidence_service
from app.services.tax import received_reports
from tests.test_tax_foundation import TENANT_A, TENANT_B, auth, token_for

REPORT_DATE = date(2026, 8, 30)
REPORT_YEAR = REPORT_DATE.year
REPORT_MONTH = REPORT_DATE.month
TAX_SCOPES = ["tax:read", "tax:write"]


@pytest.fixture(autouse=True)
async def automation_writes_enabled() -> None:
    async with SessionFactory.begin() as session:
        for tenant_id in (TENANT_A, TENANT_B):
            settings = await session.get(AutomationSettings, tenant_id)
            assert settings is not None
            settings.writes_enabled = True


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
    if document_code not in {
        access_key.INVOICE_DOCUMENT_CODE,
        access_key.CREDIT_NOTE_DOCUMENT_CODE,
    }:
        base = (
            f"{issue_date:%d%m%Y}{document_code}1790000000001"
            f"{access_key.ENVIRONMENT_PRODUCTION}001002{sequential:09d}"
            f"{sequential:08d}1"
        )
        return f"{base}{access_key.compute_verifier_digit(base)}"
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
    receiver_identification: str = "1799999999001",
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
        f"{key}\t{formatted}\t{formatted}\t{receiver_identification}\t"
        "10.00\t1.50\t11.50\t\n"
    )
    return content.encode("iso-8859-1")


def _merge_reports(*reports: bytes) -> bytes:
    decoded = [report.decode("iso-8859-1").splitlines() for report in reports]
    lines = [decoded[0][0], *(line for item in decoded for line in item[1:])]
    return ("\n".join(lines) + "\n").encode("iso-8859-1")


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
    invoice_id = await _upload(
        client,
        token,
        "facturas.txt",
        _merge_reports(
            _report(issue_date=date(2026, 8, 1)),
            _report(sequential=3, issue_date=date(2026, 8, 30)),
        ),
    )
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
    liquidation_id = await _upload(
        client,
        token,
        "liquidaciones.txt",
        _report(label="Liquidación de compra", document_code="03", sequential=4),
    )
    debit_note_id = await _upload(
        client,
        token,
        "notas-debito.txt",
        _report(label="Nota de débito", document_code="05", sequential=5),
    )
    retention_id = await _upload(
        client,
        token,
        "retenciones.txt",
        _report(label="Comprobante de retención", document_code="07", sequential=6),
    )
    payload = {
        "evidenceIds": [
            invoice_id,
            credit_note_id,
            liquidation_id,
            debit_note_id,
            retention_id,
        ],
        "reportYear": REPORT_YEAR,
        "reportMonth": REPORT_MONTH,
    }

    response = await client.post(
        "/api/v1/tax/received-reports/process",
        headers=auth(token, "received-reports-20260830"),
        json=payload,
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["evidenceCount"] == 5
    assert body["reportYear"] == REPORT_YEAR
    assert body["reportMonth"] == REPORT_MONTH
    assert body["listedRows"] == 6
    assert body["documentTypes"] == {
        "FACTURA": 2,
        "LIQUIDACION": 1,
        "NOTA_CREDITO": 1,
        "NOTA_DEBITO": 1,
        "RETENCION": 1,
    }
    assert body["created"] == 6
    assert body["preliminary"] == 6
    assert body["recoveryJob"]["status"] == "QUEUED"
    assert body["recoveryJob"]["totalCount"] == 6

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
    assert document_count == 6
    assert recovery_events == 1


async def test_process_received_reports_rejects_a_row_from_another_month_without_writes(
    client,
    stored_objects,
) -> None:
    token = await token_for(client, "a@iaerp.local", TENANT_A, TAX_SCOPES)
    evidence_id = await _upload(
        client,
        token,
        "fecha-errada.txt",
        _report(issue_date=date(2026, 7, 31)),
    )
    response = await client.post(
        "/api/v1/tax/received-reports/process",
        headers=auth(token, "received-reports-wrong-date"),
        json={
            "evidenceIds": [evidence_id],
            "reportYear": REPORT_YEAR,
            "reportMonth": REPORT_MONTH,
        },
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "Every report row must match reportYear and reportMonth"

    async with SessionFactory() as session:
        count = await session.scalar(select(func.count()).select_from(FiscalDocument))
    assert count == 0


async def test_process_received_reports_requires_automation_policy(
    client,
    stored_objects,
) -> None:
    token = await token_for(client, "a@iaerp.local", TENANT_A, TAX_SCOPES)
    evidence_id = await _upload(client, token, "policy-off.txt", _report())
    async with SessionFactory.begin() as session:
        settings = await session.get(AutomationSettings, TENANT_A)
        assert settings is not None
        settings.writes_enabled = False

    response = await client.post(
        "/api/v1/tax/received-reports/process",
        headers=auth(token, "received-reports-policy-off"),
        json={
            "evidenceIds": [evidence_id],
            "reportYear": REPORT_YEAR,
            "reportMonth": REPORT_MONTH,
        },
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "Automation writes are disabled for this tenant"

    async with SessionFactory() as session:
        count = await session.scalar(select(func.count()).select_from(FiscalDocument))
    assert count == 0


async def test_process_received_reports_rejects_rows_for_another_tenant(
    client,
    stored_objects,
) -> None:
    token = await token_for(client, "a@iaerp.local", TENANT_A, TAX_SCOPES)
    evidence_id = await _upload(
        client,
        token,
        "tenant-errado.txt",
        _report(receiver_identification="1799999999002"),
    )
    response = await client.post(
        "/api/v1/tax/received-reports/process",
        headers=auth(token, "received-reports-wrong-tenant"),
        json={
            "evidenceIds": [evidence_id],
            "reportYear": REPORT_YEAR,
            "reportMonth": REPORT_MONTH,
        },
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "Every report row must belong to the active tenant"

    async with SessionFactory() as session:
        count = await session.scalar(select(func.count()).select_from(FiscalDocument))
    assert count == 0


async def test_process_received_reports_accepts_cedula_for_natural_person_tenant(
    client,
    stored_objects,
) -> None:
    async with SessionFactory.begin() as session:
        tenant = await session.get(Tenant, TENANT_A)
        assert tenant is not None
        tenant.ruc = "1712345675001"

    token = await token_for(client, "a@iaerp.local", TENANT_A, TAX_SCOPES)
    evidence_id = await _upload(
        client,
        token,
        "persona-natural.txt",
        _report(receiver_identification="1712345675"),
    )
    response = await client.post(
        "/api/v1/tax/received-reports/process",
        headers=auth(token, "received-reports-natural-person"),
        json={
            "evidenceIds": [evidence_id],
            "reportYear": REPORT_YEAR,
            "reportMonth": REPORT_MONTH,
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["created"] == 1


async def test_process_received_reports_rejects_incoherent_access_key(
    client,
    stored_objects,
) -> None:
    token = await token_for(client, "a@iaerp.local", TENANT_A, TAX_SCOPES)
    report = _report()
    lines = report.decode("iso-8859-1").splitlines()
    columns = lines[1].split("\t")
    columns[4] = columns[4][:-1] + ("0" if columns[4][-1] != "0" else "1")
    invalid_report = (lines[0] + "\n" + "\t".join(columns) + "\n").encode("iso-8859-1")
    evidence_id = await _upload(client, token, "clave-invalida.txt", invalid_report)

    response = await client.post(
        "/api/v1/tax/received-reports/process",
        headers=auth(token, "received-reports-invalid-key"),
        json={
            "evidenceIds": [evidence_id],
            "reportYear": REPORT_YEAR,
            "reportMonth": REPORT_MONTH,
        },
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "Every report row must have a coherent SRI access key"


async def test_process_received_reports_is_tenant_scoped(client, stored_objects) -> None:
    token_a = await token_for(client, "a@iaerp.local", TENANT_A, TAX_SCOPES)
    token_b = await token_for(client, "b@iaerp.local", TENANT_B, TAX_SCOPES)
    evidence_id = await _upload(client, token_a, "tenant-a.txt", _report())

    response = await client.post(
        "/api/v1/tax/received-reports/process",
        headers=auth(token_b, "received-reports-tenant-b"),
        json={
            "evidenceIds": [evidence_id],
            "reportYear": REPORT_YEAR,
            "reportMonth": REPORT_MONTH,
        },
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
            "reportYear": REPORT_YEAR,
            "reportMonth": REPORT_MONTH,
        },
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "Evidence IDs must be unique"


async def test_process_received_reports_rejects_unknown_input_fields(
    client,
    stored_objects,
) -> None:
    token = await token_for(client, "a@iaerp.local", TENANT_A, TAX_SCOPES)
    evidence_id = await _upload(client, token, "extra-field.txt", _report())
    response = await client.post(
        "/api/v1/tax/received-reports/process",
        headers=auth(token, "received-reports-extra-field"),
        json={
            "evidenceIds": [evidence_id],
            "reportYear": REPORT_YEAR,
            "reportMonth": REPORT_MONTH,
            "tenantId": str(TENANT_B),
        },
    )
    assert response.status_code == 422
    assert response.json()["detail"][0]["type"] == "extra_forbidden"


async def test_monthly_refresh_updates_existing_documents_without_duplicates(
    client,
    stored_objects,
) -> None:
    token = await token_for(client, "a@iaerp.local", TENANT_A, TAX_SCOPES)
    first_id = await _upload(client, token, "facturas-corte-1.txt", _report())
    first = await client.post(
        "/api/v1/tax/received-reports/process",
        headers=auth(token, "received-month-first-0001"),
        json={
            "evidenceIds": [first_id],
            "reportYear": REPORT_YEAR,
            "reportMonth": REPORT_MONTH,
        },
    )
    assert first.status_code == 201, first.text
    assert first.json()["created"] == 1

    refreshed_id = await _upload(
        client,
        token,
        "facturas-corte-2.txt",
        _merge_reports(_report(), _report(sequential=2, issue_date=date(2026, 8, 31))),
    )
    refreshed = await client.post(
        "/api/v1/tax/received-reports/process",
        headers=auth(token, "received-month-refresh-0002"),
        json={
            "evidenceIds": [refreshed_id],
            "reportYear": REPORT_YEAR,
            "reportMonth": REPORT_MONTH,
        },
    )
    assert refreshed.status_code == 201, refreshed.text
    assert refreshed.json()["created"] == 1
    assert refreshed.json()["updated"] == 1

    async with SessionFactory() as session:
        count = await session.scalar(select(func.count()).select_from(FiscalDocument))
    assert count == 2


async def test_monthly_refresh_does_not_degrade_an_authorized_document(
    client,
    stored_objects,
) -> None:
    token = await token_for(client, "a@iaerp.local", TENANT_A, TAX_SCOPES)
    first_id = await _upload(client, token, "factura-preliminar.txt", _report())
    first = await client.post(
        "/api/v1/tax/received-reports/process",
        headers=auth(token, "received-authorized-first-0001"),
        json={
            "evidenceIds": [first_id],
            "reportYear": REPORT_YEAR,
            "reportMonth": REPORT_MONTH,
        },
    )
    assert first.status_code == 201, first.text

    async with SessionFactory.begin() as session:
        document = await session.scalar(select(FiscalDocument))
        assert document is not None
        original_evidence_id = document.evidence_id
        document.is_preliminary = False
        document.total = Decimal("99.99")

    refreshed_id = await _upload(
        client,
        token,
        "factura-refrescada.txt",
        _report(),
    )
    refreshed = await client.post(
        "/api/v1/tax/received-reports/process",
        headers=auth(token, "received-authorized-refresh-0002"),
        json={
            "evidenceIds": [refreshed_id],
            "reportYear": REPORT_YEAR,
            "reportMonth": REPORT_MONTH,
        },
    )
    assert refreshed.status_code == 201, refreshed.text
    assert refreshed.json()["skipped"] == 1

    async with SessionFactory() as session:
        document = await session.scalar(select(FiscalDocument))
        assert document is not None
        assert document.is_preliminary is False
        assert document.evidence_id == original_evidence_id
        assert document.total == Decimal("99.99")


async def test_service_limit_matches_the_five_sri_report_types() -> None:
    assert received_reports.MAX_MONTHLY_REPORTS == 5
