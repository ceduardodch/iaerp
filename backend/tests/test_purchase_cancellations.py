"""Compras anuladas localmente: evidencia, cierres, pagos y fuentes intactas."""

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.core.auth import AuthContext
from app.db.session import SessionFactory
from app.models.payables import Payable, PayableMovement, SupplierPaymentSchedule
from app.models.platform import AuditEvent
from app.models.tax import FiscalDocument, FiscalDocumentTax, TaxEvidence, TaxPeriod
from app.services.tax import ats_builder, iva, purchase_cancellations, reporting
from tests.test_tax_foundation import TENANT_A, TENANT_B, auth, token_for
from tests.test_tax_received_reports import _key, _report

SCOPES = ["tax:read", "tax:write", "payables:read", "payables:write", "payables:extract"]


@pytest.fixture
def private_storage(monkeypatch):
    objects = {}

    async def upload(*, object_key, data, **kwargs):
        objects[object_key] = data

    async def exists(*, object_key, **kwargs):
        return object_key in objects

    async def download(*, object_key, **kwargs):
        return objects[object_key]

    monkeypatch.setattr(purchase_cancellations.storage, "upload_private_object", upload)
    monkeypatch.setattr(purchase_cancellations.storage, "object_exists", exists)
    monkeypatch.setattr(purchase_cancellations.storage, "download_artifact", download)
    return objects


async def _case(client, *, with_payable=True):
    token = await token_for(client, "a@iaerp.local", TENANT_A, SCOPES)
    key = _key(document_code="01", sequential=1, issue_date=date(2026, 8, 1))
    async with SessionFactory.begin() as session:
        period = TaxPeriod(
            tenant_id=TENANT_A,
            year=2026,
            month=8,
            obligation_type="IVA",
            status="LISTO_REVISAR",
        )
        session.add(period)
        await session.flush()
        document = FiscalDocument(
            tenant_id=TENANT_A,
            tax_period_id=period.id,
            direction="RECIBIDO",
            doc_type="FACTURA",
            access_key=key,
            issue_date=date(2026, 8, 1),
            establishment_code="001",
            emission_point_code="002",
            sequential="000000001",
            counterparty_identification="1790000000001",
            counterparty_name="Proveedor sintético",
            subtotal=Decimal("100.00"),
            tax_total=Decimal("15.00"),
            total=Decimal("115.00"),
            payment_methods=["20"],
            is_preliminary=False,
        )
        session.add(document)
        await session.flush()
        session.add(
            FiscalDocumentTax(
                tenant_id=TENANT_A,
                fiscal_document_id=document.id,
                sri_tax_code="4",
                tax_bracket="GRAVADO",
                rate=Decimal("15"),
                base_amount=Decimal("100.00"),
                tax_amount=Decimal("15.00"),
            )
        )
        document_id, period_id = str(document.id), str(period.id)
    payable = None
    if with_payable:
        response = await client.post(
            "/api/v1/payables/from-document",
            headers=auth(token, "cancellation-seed-payable"),
            json={"documentId": document_id},
        )
        assert response.status_code == 201, response.text
        payable = response.json()
    response = await client.post(
        "/api/v1/tax/evidence",
        headers=auth(token, "cancellation-proof-upload"),
        files={"file": ("anulado-sintetico.txt", b"SRI ANULADO: " + key.encode())},
    )
    assert response.status_code == 201, response.text
    payload = {
        "sriStatus": "ANULADO",
        "economicOutcome": "OPERATION_CANCELLED",
        "effectiveDate": "2026-08-02",
        "reason": "Estado ANULADO confirmado para la clave exacta",
        "evidenceId": response.json()["id"],
    }
    return token, document_id, period_id, payable, payload


async def _cancel(client, token, document_id, payload, key="cancellation-confirmed-once"):
    return await client.post(
        f"/api/v1/tax/purchases/{document_id}/cancellation",
        headers=auth(token, key),
        json=payload,
    )


def _context():
    return AuthContext("synthetic-user", "USER", TENANT_A, frozenset(), frozenset(SCOPES), "test")


async def test_cancel_preserves_history_excludes_tax_dashboard_and_debt(client, private_storage):
    token, doc_id, period_id, payable, payload = await _case(client)
    async with SessionFactory.begin() as session:
        item = await session.get(Payable, uuid.UUID(payable["id"]))
        item.tax_classification = "DEDUCTIBLE_CONFIRMED"
        item.internal_classification = "REAL"
    async with SessionFactory() as session:
        before_report = await reporting.dashboard_tax_report(
            session, _context(), as_of=date(2026, 8, 10), months=6
        )
        assert before_report.annual.deductible_purchases_base == Decimal("100.00")
        assert before_report.annual.internal_real_expenses_total == Decimal("115.00")
    async with SessionFactory() as session:
        period = await session.get(TaxPeriod, uuid.UUID(period_id))
        before = await iva.compute_iva(session, _context(), period=period)
        assert before.value("iva_credito_tributario") == Decimal("15.00")
    response = await _cancel(client, token, doc_id, payload)
    assert response.status_code == 200, response.text
    assert response.json()["lifecycleStatus"] == "CANCELLED"
    assert response.json()["total"] == "115.00"
    assert response.json()["cancellation"]["evidenceId"] == payload["evidenceId"]
    assert response.json()["cancellation"]["economicOutcome"] == "OPERATION_CANCELLED"
    replay = await _cancel(client, token, doc_id, payload)
    assert replay.json() == response.json()
    conflict = await _cancel(client, token, doc_id, {**payload, "reason": "Otra razón"})
    assert conflict.status_code == 409
    rows = await client.get("/api/v1/tax/purchases", headers=auth(token))
    assert len(rows.json()) == 1
    assert rows.json()[0]["lifecycleStatus"] == "CANCELLED"
    assert rows.json()[0]["cancellation"]["economicOutcome"] == "OPERATION_CANCELLED"
    paid = await client.get(f"/api/v1/payables/{payable['id']}", headers=auth(token))
    assert paid.json()["status"] == "VOIDED"
    assert paid.json()["paymentStatus"] == "OPEN"
    assert paid.json()["openAmount"] == "0.00"
    async with SessionFactory() as session:
        document = await session.get(FiscalDocument, uuid.UUID(doc_id))
        period = await session.get(TaxPeriod, uuid.UUID(period_id))
        after = await iva.compute_iva(session, _context(), period=period)
        assert after.value("iva_credito_tributario") == Decimal("0.00")
        assert after.document_count == 0
        assert not after.is_preliminary
        assert period.status == "LISTO_REVISAR"
        taxes = list(await session.scalars(select(FiscalDocumentTax)))
        built = ats_builder.build_ats_input(
            period=period,
            identification="1799999999001",
            legal_name="SINTETICO",
            documents=[document],
            taxes=taxes,
            retentions=[],
        )
        assert built.data.purchases == []
        assert built.missing == []
        dashboard = await reporting.dashboard_tax_report(
            session, _context(), as_of=date(2026, 8, 10), months=6
        )
        assert dashboard.current_month.purchase_count == 0
        assert dashboard.current_month.purchases_total == Decimal("0.00")
        assert dashboard.annual.internal_real_expenses_total == Decimal("0.00")
        assert dashboard.annual.deductible_purchases_base == Decimal("0.00")
        assert (
            await session.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.action == "tax.purchase.cancelled_locally")
            )
            == 1
        )
        audit = await session.scalar(
            select(AuditEvent).where(AuditEvent.action == "tax.purchase.cancelled_locally")
        )
        assert audit.details["economic_outcome"] == "OPERATION_CANCELLED"
        assert document.total == Decimal("115.00")
        assert len(taxes) == 1
        assert await session.scalar(select(func.count()).select_from(TaxEvidence)) == 1
        assert await session.scalar(select(func.count()).select_from(PayableMovement)) == 0


@pytest.mark.parametrize("obligation,month", [("IVA", 8), ("ATS", 8), ("RENTA", 12)])
async def test_declared_period_blocks_without_changing_source(
    client, private_storage, obligation, month
):
    token, doc_id, period_id, payable, payload = await _case(client)
    async with SessionFactory.begin() as session:
        if obligation == "IVA":
            period = await session.get(TaxPeriod, uuid.UUID(period_id))
            period.status = "DECLARADO"
        else:
            session.add(
                TaxPeriod(
                    tenant_id=TENANT_A,
                    year=2026,
                    month=month,
                    obligation_type=obligation,
                    status="DECLARADO",
                )
            )
    result = await _cancel(client, token, doc_id, payload)
    assert result.status_code == 409, result.text
    assert "declarado" in result.json()["detail"]
    async with SessionFactory() as session:
        assert (await session.get(FiscalDocument, uuid.UUID(doc_id))).cancelled_at is None
        assert (await session.get(Payable, uuid.UUID(payable["id"]))).status == "OPEN"


@pytest.mark.parametrize("kind", ["PAYMENT", "RETENTION", "CREDIT_NOTE"])
async def test_applied_movements_block_and_keep_payment_history(client, private_storage, kind):
    token, doc_id, _, payable, payload = await _case(client)
    route = "payments" if kind == "PAYMENT" else "adjustments"
    data = {"amount": "5.00", "reference": "respaldo sintético"}
    if kind == "PAYMENT":
        data.update(paymentDate="2026-08-01", method="TRANSFER")
    else:
        data.update(effectiveDate="2026-08-01", movementType=kind)
    response = await client.post(
        f"/api/v1/payables/{payable['id']}/{route}",
        headers=auth(token, "cancellation-seed-movement"),
        json=data,
    )
    assert response.status_code == 201, response.text
    result = await _cancel(client, token, doc_id, payload)
    assert result.status_code == 409
    assert "conciliación" in result.json()["detail"]
    async with SessionFactory() as session:
        assert (await session.get(FiscalDocument, uuid.UUID(doc_id))).cancelled_at is None
        assert await session.scalar(select(func.count()).select_from(PayableMovement)) == 1


@pytest.mark.parametrize(
    "change",
    [
        {"sriStatus": "PENDIENTE_ANULAR"},
        {"sriStatus": "NO_AUTORIZADO"},
        {"effectiveDate": "2026-07-31"},
        {"effectiveDate": "2099-01-01"},
        {"reason": "   "},
        {"evidenceId": None},
    ],
)
async def test_invalid_confirmation_rejected(client, private_storage, change):
    token, doc_id, _, _, payload = await _case(client)
    result = await _cancel(client, token, doc_id, {**payload, **change})
    assert result.status_code == 422


async def test_tenant_isolation_and_missing_stored_evidence(client, private_storage):
    token, doc_id, _, _, payload = await _case(client)
    other = await token_for(client, "b@iaerp.local", TENANT_B, SCOPES)
    result = await _cancel(client, other, doc_id, payload)
    assert result.status_code == 404
    async with SessionFactory.begin() as session:
        proof = await session.get(TaxEvidence, uuid.UUID(payload["evidenceId"]))
        proof.tenant_id = TENANT_B
    result = await _cancel(client, token, doc_id, payload)
    assert result.status_code == 404
    async with SessionFactory.begin() as session:
        proof = await session.get(TaxEvidence, uuid.UUID(payload["evidenceId"]))
        proof.tenant_id = TENANT_A
    private_storage.clear()
    result = await _cancel(client, token, doc_id, payload)
    assert result.status_code == 409


async def test_without_payable_preserves_purchase_no_artificial_debt(client, private_storage):
    token, doc_id, _, _, payload = await _case(client, with_payable=False)
    response = await _cancel(client, token, doc_id, payload)
    assert response.status_code == 200, response.text
    async with SessionFactory() as session:
        assert await session.scalar(select(func.count()).select_from(Payable)) == 0
    recreated = await client.post(
        "/api/v1/payables/from-document",
        headers=auth(token, "cancellation-no-recreate"),
        json={"documentId": doc_id},
    )
    assert recreated.status_code == 422


async def _ingest(client, token, content, filename, key):
    uploaded = await client.post(
        "/api/v1/tax/evidence",
        headers=auth(token, f"upload-{key}"),
        files={"file": (filename, content)},
    )
    assert uploaded.status_code == 201, uploaded.text
    result = await client.post(
        f"/api/v1/tax/evidence/{uploaded.json()['id']}/ingest",
        headers=auth(token, f"ingest-{key}"),
    )
    return result


def _source_xml():
    key = _key(document_code="01", sequential=1, issue_date=date(2026, 8, 1))
    return f"""<autorizacion><estado>AUTORIZADO</estado>
    <numeroAutorizacion>{key}</numeroAutorizacion><comprobante><![CDATA[
    <factura><infoTributaria><ruc>1790000000001</ruc><razonSocial>PROVEEDOR DEMO</razonSocial>
    <codDoc>01</codDoc><estab>001</estab><ptoEmi>002</ptoEmi><secuencial>000000001</secuencial>
    <claveAcceso>{key}</claveAcceso></infoTributaria><infoFactura>
    <fechaEmision>01/08/2026</fechaEmision><identificacionComprador>1799999999001</identificacionComprador>
    <totalSinImpuestos>100.00</totalSinImpuestos><importeTotal>115.00</importeTotal>
    <totalConImpuestos><totalImpuesto><codigo>2</codigo><codigoPorcentaje>4</codigoPorcentaje>
    <tarifa>15</tarifa><baseImponible>100.00</baseImponible><valor>15.00</valor></totalImpuesto>
    </totalConImpuestos></infoFactura></factura>]]></comprobante></autorizacion>""".encode()


async def test_reimport_xml_txt_and_rule_do_not_reactivate_cancelled_purchase(
    client, private_storage
):
    from app.models.payables import PurchaseTaxRule
    from app.models.platform import AutomationSettings
    from app.services import purchase_tax_rules

    token, doc_id, period_id, payable, payload = await _case(client)
    assert (await _cancel(client, token, doc_id, payload)).status_code == 200
    for attempt in range(2):
        xml = await _ingest(client, token, _source_xml(), "invoice.xml", f"source-xml-{attempt}")
        assert xml.status_code == 200, xml.text
        txt = await _ingest(
            client,
            token,
            _report(issue_date=date(2026, 8, 1)),
            "source.txt",
            f"source-txt-{attempt}",
        )
        assert txt.status_code == 200, txt.text
    async with SessionFactory.begin() as session:
        (await session.get(AutomationSettings, TENANT_A)).writes_enabled = True
        session.add(
            PurchaseTaxRule(
                tenant_id=TENANT_A,
                supplier_ruc="1790000000001",
                tax_classification="DEDUCTIBLE_CONFIRMED",
                active=True,
            )
        )
        await session.flush()
        document = await session.get(FiscalDocument, uuid.UUID(doc_id))
        await purchase_tax_rules.apply_recovered_invoice_rule(
            session,
            _context(),
            document=document,
            period=await session.get(TaxPeriod, uuid.UUID(period_id)),
            job_id=uuid.uuid4(),
        )
        assert document.cancelled_at is not None
        assert document.cancellation_evidence_id == uuid.UUID(payload["evidenceId"])
        item = await session.get(Payable, uuid.UUID(payable["id"]))
        assert item.status == "VOID"
        assert item.tax_classification == "DEDUCTIBLE_PENDING_REVIEW"
        assert await session.scalar(select(func.count()).select_from(Payable)) == 1
        assert await session.scalar(select(func.count()).select_from(FiscalDocument)) == 1


async def test_late_credit_note_rejected_without_second_fiscal_reduction(client, private_storage):
    from tests.fixtures.sri_documents import CREDIT_NOTE_RECEIVED_IVA15_XML

    token, doc_id, period_id, _, payload = await _case(client)
    assert (await _cancel(client, token, doc_id, payload)).status_code == 200
    xml = (
        CREDIT_NOTE_RECEIVED_IVA15_XML.replace(b"0888888888001", b"1790000000001")
        .replace(b"0777777777001", b"1799999999001")
        .replace(b"001-002-000019877", b"001-002-000000001")
    )
    result = await _ingest(client, token, xml, "late-nc.xml", "late-note-proof")
    assert result.status_code == 409, result.text
    assert "compra anulada" in result.json()["detail"]
    async with SessionFactory() as session:
        assert await session.scalar(select(func.count()).select_from(FiscalDocument)) == 1
        assert await session.scalar(select(func.count()).select_from(PayableMovement)) == 0
        period = await session.get(TaxPeriod, uuid.UUID(period_id))
        assert (await iva.compute_iva(session, _context(), period=period)).value(
            "iva_credito_tributario"
        ) == Decimal("0.00")


@pytest.mark.parametrize("missing", ["tax:write", "payables:write"])
async def test_both_scopes_required(client, private_storage, missing):
    token, doc_id, _, _, payload = await _case(client)
    limited = await token_for(
        client, "a@iaerp.local", TENANT_A, [s for s in SCOPES if s != missing]
    )
    assert (await _cancel(client, limited, doc_id, payload)).status_code == 403


async def test_service_account_cannot_confirm_even_with_both_scopes(client, private_storage):
    from fastapi import HTTPException

    from app.schemas.tax import PurchaseCancellationCreate

    _, doc_id, _, _, payload = await _case(client)
    context = AuthContext(
        "synthetic-agent", "SERVICE_ACCOUNT", TENANT_A, frozenset(), frozenset(SCOPES), "test"
    )
    async with SessionFactory.begin() as session:
        with pytest.raises(HTTPException) as error:
            await purchase_cancellations.cancel_purchase(
                session,
                context,
                document_id=uuid.UUID(doc_id),
                data=PurchaseCancellationCreate.model_validate(payload),
            )
        assert error.value.status_code == 403


def _supplier_retention_xml():
    from pathlib import Path

    source = Path(__file__).parent / "fixtures/sri/retencion_recibida_autorizada.xml"
    return (
        source.read_bytes()
        .replace(b"0666666666001", b"1799999999001")
        .replace(b"0777777777001", b"1790000000001")
        .replace(b"001001000000045", b"001002000000001")
    )


async def test_existing_supplier_retention_xml_blocks_without_manual_movement(
    client, private_storage
):
    token, doc_id, _, _, payload = await _case(client)
    imported = await _ingest(
        client, token, _supplier_retention_xml(), "retention.xml", "prior-retention"
    )
    assert imported.status_code == 200, imported.text
    async with SessionFactory() as session:
        assert await session.scalar(select(func.count()).select_from(PayableMovement)) == 0
    response = await _cancel(client, token, doc_id, payload)
    assert response.status_code == 409, response.text
    assert "retención emitida" in response.json()["detail"]


async def test_late_supplier_retention_xml_rejected(client, private_storage):
    token, doc_id, _, _, payload = await _case(client)
    assert (await _cancel(client, token, doc_id, payload)).status_code == 200
    result = await _ingest(
        client, token, _supplier_retention_xml(), "late-ret.xml", "late-retention"
    )
    assert result.status_code == 409, result.text
    async with SessionFactory() as session:
        assert await session.scalar(select(func.count()).select_from(FiscalDocument)) == 1


@pytest.mark.parametrize("already_queued", [False, True])
async def test_cancelled_preliminary_invoice_not_recovered_from_sri(
    client, private_storage, already_queued
):
    from app.models.tax import TaxXmlRecoveryItem, TaxXmlRecoveryJob
    from app.services.tax import xml_recovery
    from app.workers.tax_xml_recovery import run_recovery_job

    token, doc_id, period_id, _, payload = await _case(client)
    async with SessionFactory.begin() as session:
        document = await session.get(FiscalDocument, uuid.UUID(doc_id))
        document.is_preliminary = True
        await session.flush()
        document_id = document.id
        if already_queued:
            job = await xml_recovery.create_job(session, _context(), period_id=uuid.UUID(period_id))
            job_id = job.id
            assert job.total_count == 1
    result = await _cancel(client, token, doc_id, payload)
    assert result.status_code == 200, result.text
    if not already_queued:
        async with SessionFactory.begin() as session:
            job = await xml_recovery.create_job(session, _context(), period_id=uuid.UUID(period_id))
            assert job.total_count == 0
            assert job.status == "COMPLETED"
            return

    class NoSriCalls:
        async def check_authorization(self, key):
            pytest.fail("La compra cancelada no debe consultar al SRI")

    await run_recovery_job(job_id, sri_client=NoSriCalls())
    async with SessionFactory() as session:
        job = await session.get(TaxXmlRecoveryJob, job_id)
        assert job.status == "COMPLETED"
        assert job.processed_count == 1
        assert job.recovered_count == 0
        assert (await session.get(FiscalDocument, document_id)).is_preliminary
        item = await session.scalar(
            select(TaxXmlRecoveryItem).where(TaxXmlRecoveryItem.job_id == job_id)
        )
        assert item.status == "UNAVAILABLE"


async def test_cancellation_cancels_schedule_and_all_operational_writes_stay_closed(
    client, private_storage
):
    token, doc_id, _, payable, payload = await _case(client)
    scheduled = await client.post(
        f"/api/v1/payables/{payable['id']}/schedule",
        headers=auth(token, "cancellation-existing-schedule"),
        json={"scheduledDate": "2026-08-20", "amount": "115.00"},
    )
    assert scheduled.status_code == 201, scheduled.text
    assert (await _cancel(client, token, doc_id, payload)).status_code == 200
    requests = [
        ("post", "payments", {"amount": "1.00", "paymentDate": "2026-08-02", "method": "TRANSFER"}),
        (
            "post",
            "adjustments",
            {
                "amount": "1.00",
                "effectiveDate": "2026-08-02",
                "movementType": "RETENTION",
                "reference": "proof",
            },
        ),
        ("post", "schedule", {"scheduledDate": "2026-08-20", "amount": "1.00"}),
        (
            "post",
            f"movements/{uuid.uuid4()}/reversal",
            {"effectiveDate": "2026-08-02", "reason": "reverso"},
        ),
        (
            "put",
            "classification",
            {"taxClassification": "DEDUCTIBLE_CONFIRMED", "reason": "cambio"},
        ),
    ]
    for index, (method, path, data) in enumerate(requests):
        response = await client.request(
            method,
            f"/api/v1/payables/{payable['id']}/{path}",
            headers=auth(token, f"cancellation-closed-write-{index}"),
            json=data,
        )
        assert response.status_code in (409, 422), response.text
    reviewed = await client.post(
        "/api/v1/payables/from-document/review",
        headers=auth(token, "cancellation-review-blocked"),
        json={
            "documentId": doc_id,
            "taxClassification": "DEDUCTIBLE_CONFIRMED",
            "paymentState": "KEEP_EXISTING",
        },
    )
    assert reviewed.status_code == 409, reviewed.text
    async with SessionFactory() as session:
        schedule = await session.get(SupplierPaymentSchedule, uuid.UUID(scheduled.json()["id"]))
        assert schedule.status == "CANCELLED"
        assert await session.scalar(select(func.count()).select_from(PayableMovement)) == 0
        assert (await session.get(Payable, uuid.UUID(payable["id"]))).status == "VOID"


@pytest.mark.parametrize("first", ["cancellation", "payment", "declaration"])
async def test_concurrent_writes_serialize_without_payment_or_fiscal_race(
    client, private_storage, monkeypatch, first
):
    import asyncio

    from app.db.session import engine
    from app.services import payables
    from app.services.tax import periods

    if engine.dialect.name != "postgresql":
        pytest.skip("Esta regresión de bloqueo necesita PostgreSQL")
    token, doc_id, period_id, payable, payload = await _case(client)
    entered = asyncio.Event()
    release = asyncio.Event()

    async def pay():
        return await client.post(
            f"/api/v1/payables/{payable['id']}/payments",
            headers=auth(token, "cancellation-concurrent-payment"),
            json={"amount": "5.00", "paymentDate": "2026-08-01", "method": "TRANSFER"},
        )

    if first == "cancellation":
        original = purchase_cancellations.storage.object_exists

        async def hold(**kwargs):
            result = await original(**kwargs)
            entered.set()
            await release.wait()
            return result

        monkeypatch.setattr(purchase_cancellations.storage, "object_exists", hold)
        first_task = asyncio.create_task(_cancel(client, token, doc_id, payload))
        next_operation = pay
    elif first == "payment":
        original = payables.record_payment

        async def hold(*args, **kwargs):
            result = await original(*args, **kwargs)
            entered.set()
            await release.wait()
            return result

        monkeypatch.setattr(payables, "record_payment", hold)
        first_task = asyncio.create_task(pay())

        async def next_operation():
            return await _cancel(client, token, doc_id, payload)
    else:
        async with SessionFactory.begin() as session:
            (await session.get(TaxPeriod, uuid.UUID(period_id))).status = "LISTO_DECLARAR"
        original = periods.set_manual_status

        async def hold(*args, **kwargs):
            result = await original(*args, **kwargs)
            entered.set()
            await release.wait()
            return result

        monkeypatch.setattr(periods, "set_manual_status", hold)
        first_task = asyncio.create_task(
            client.post(
                f"/api/v1/tax/periods/{period_id}/status",
                headers=auth(token, "cancellation-concurrent-declaration"),
                json={"targetStatus": "DECLARADO", "confirmed": True},
            )
        )

        async def next_operation():
            return await _cancel(client, token, doc_id, payload)

    try:
        await asyncio.wait_for(entered.wait(), 5)
        second_task = asyncio.create_task(next_operation())
        await asyncio.sleep(0.05)
        assert not second_task.done(), "La segunda escritura debe esperar la transacción"
    finally:
        release.set()
    first_result, second_result = await asyncio.wait_for(
        asyncio.gather(first_task, second_task), 10
    )
    assert first_result.status_code in (200, 201), first_result.text
    assert second_result.status_code in (409, 422), second_result.text
    async with SessionFactory() as session:
        document = await session.get(FiscalDocument, uuid.UUID(doc_id))
        movements = await session.scalar(select(func.count()).select_from(PayableMovement))
        assert (document.cancelled_at is not None) == (first == "cancellation")
        assert movements == (1 if first == "payment" else 0)


@pytest.mark.parametrize("outcome", [None, "PURCHASE_CONTINUES", "INVOICE_REPLACED"])
async def test_fiscal_annulment_alone_cannot_extinguish_purchase(client, private_storage, outcome):
    token, doc_id, period_id, payable, payload = await _case(client)
    if outcome is None:
        payload.pop("economicOutcome")
    else:
        payload["economicOutcome"] = outcome
    result = await _cancel(client, token, doc_id, payload)
    assert result.status_code == 422, result.text
    async with SessionFactory() as session:
        document = await session.get(FiscalDocument, uuid.UUID(doc_id))
        item = await session.get(Payable, uuid.UUID(payable["id"]))
        assert document.cancelled_at is None
        assert item.status == "OPEN"
        period = await session.get(TaxPeriod, uuid.UUID(period_id))
        summary = await iva.compute_iva(session, _context(), period=period)
        assert summary.value("iva_credito_tributario") == Decimal("15.00")
        assert (
            await session.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.action == "tax.purchase.cancelled_locally")
            )
            == 0
        )
