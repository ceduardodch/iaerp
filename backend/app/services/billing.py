"""Casos de uso del contexto Billing (Sprint 2).

Este modulo cubre borrador de factura/nota de credito con calculo fiscal
recalculado siempre en backend (el cliente nunca aporta totales, solo lineas
crudas), la reserva atomica de secuencial, y la emision completa: clave de
acceso, firma XAdES-BES, XML, RIDE, subida a MinIO y el evento outbox que
dispara la transmision SRI (``workers/sri_transmission.py``).
"""

from __future__ import annotations

import uuid
from decimal import ROUND_HALF_UP, Decimal

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthContext
from app.core.config import get_settings
from app.core.timezones import today_in_fiscal_timezone
from app.models.billing import (
    DocumentArtifact,
    DocumentRelation,
    SalesDocument,
    SalesDocumentInstallment,
    SalesDocumentLine,
    Sequence,
    SRITransmission,
)
from app.models.masters import EmissionPoint, Establishment, Party, Product, TaxCategory
from app.schemas.billing import (
    ArtifactDownloadRead,
    CreditNoteInput,
    DocumentArtifactRead,
    InvoiceInput,
    SalesDocumentLineRead,
    SalesDocumentRead,
    SRITransmissionRead,
)
from app.services import access_key as access_key_service
from app.services import fiscal_settings, masters, ride, signing, sri_xml, storage
from app.services.fiscal_policy import FiscalCalculationPolicy, LineInput, resolve_fiscal_policy
from app.services.unit_of_work import append_audit

# Tipos de documento y su prefijo de operacion de secuencial, segun
# docs/03-domain-model.md (Billing: SalesDocument, Sequence).
_INVOICE_DOCUMENT_TYPE = "INVOICE"
_CREDIT_NOTE_DOCUMENT_TYPE = "CREDIT_NOTE"

# Estados de un SalesDocument que cuentan como "en curso o autorizado" para el
# control de saldo acreditable de una nota de credito (E4-07, ADR 0008 seccion
# 5): cualquier NC que todavia puede terminar AUTHORIZED debe reservar su
# monto contra el saldo, no solo las ya AUTHORIZED, para no permitir crear
# varias NC en paralelo que en conjunto excedan el saldo mientras estan en
# transito por el pipeline de firma/transmision SRI. Excluye los estados
# terminales negativos (NOT_AUTHORIZED, REJECTED, VOIDED, FAILED): esos nunca
# van a compensar la factura y no deben bloquear saldo.
_CREDIT_NOTE_STATUSES_RESERVING_BALANCE = frozenset(
    {
        "DRAFT",
        "READY",
        "SIGNED",
        "RECEIVED",
        "PENDING_AUTHORIZATION",
        "AUTHORIZED",
    }
)

# Evento outbox que dispara el worker de transmision SRI (workers/tasks.py
# rutea por event_type; workers/sri_transmission.py es el handler).
INVOICE_SIGNED_EVENT = "invoice.signed"

async def _get_tenant_scoped_establishment(
    session: AsyncSession,
    context: AuthContext,
    establishment_id: uuid.UUID,
) -> Establishment:
    establishment = await session.scalar(
        select(Establishment).where(
            Establishment.id == establishment_id,
            Establishment.tenant_id == context.tenant_id,
            Establishment.active.is_(True),
        )
    )
    if establishment is None:
        raise HTTPException(status_code=404, detail="Establishment not found")
    return establishment


async def _get_tenant_scoped_emission_point(
    session: AsyncSession,
    context: AuthContext,
    emission_point_id: uuid.UUID,
    establishment_id: uuid.UUID,
) -> EmissionPoint:
    emission_point = await session.scalar(
        select(EmissionPoint).where(
            EmissionPoint.id == emission_point_id,
            EmissionPoint.tenant_id == context.tenant_id,
            EmissionPoint.establishment_id == establishment_id,
            EmissionPoint.active.is_(True),
        )
    )
    if emission_point is None:
        raise HTTPException(status_code=404, detail="Emission point not found")
    return emission_point


async def _get_tenant_scoped_party(
    session: AsyncSession,
    context: AuthContext,
    party_id: uuid.UUID,
) -> Party:
    party = await session.scalar(
        select(Party).where(
            Party.id == party_id,
            Party.tenant_id == context.tenant_id,
            Party.active.is_(True),
        )
    )
    if party is None:
        raise HTTPException(status_code=404, detail="Party not found")
    return party


async def _get_tenant_scoped_tax_category_by_code(
    session: AsyncSession,
    context: AuthContext,
    tax_code: str,
) -> TaxCategory:
    tax_category = await session.scalar(
        select(TaxCategory)
        .where(
            TaxCategory.tenant_id == context.tenant_id,
            TaxCategory.sri_code == tax_code,
            TaxCategory.active.is_(True),
        )
        .order_by(TaxCategory.valid_from.desc())
        .limit(1)
    )
    if tax_category is None:
        raise HTTPException(status_code=404, detail=f"Tax category '{tax_code}' not found")
    return tax_category


async def _get_tenant_scoped_product(
    session: AsyncSession,
    context: AuthContext,
    product_id: uuid.UUID,
) -> Product:
    product = await session.scalar(
        select(Product).where(
            Product.id == product_id,
            Product.tenant_id == context.tenant_id,
            Product.active.is_(True),
        )
    )
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    return product


async def _reserve_sequential(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    document_type: str,
    establishment_id: uuid.UUID,
    emission_point_id: uuid.UUID,
) -> str:
    """Reserva atomicamente el proximo secuencial para esta combinacion.

    ``SELECT ... FOR UPDATE`` bloquea la fila de ``Sequence`` (creandola si no
    existe) dentro de la transaccion abierta por el llamador, siguiendo el
    mismo patron que ``execute_idempotent`` usa sobre ``Tenant``. El
    ``UniqueConstraint`` de ``SalesDocument`` es la defensa adicional si el
    lock se perdiera por algun motivo. En SQLite (pruebas unitarias) el mismo
    codigo funciona porque SQLite serializa escritores; la prueba de
    concurrencia real solo se ejecuta contra PostgreSQL.
    """

    sequence_row = await session.scalar(
        select(Sequence)
        .where(
            Sequence.tenant_id == tenant_id,
            Sequence.document_type == document_type,
            Sequence.establishment_id == establishment_id,
            Sequence.emission_point_id == emission_point_id,
        )
        .with_for_update()
    )
    if sequence_row is None:
        sequence_row = Sequence(
            tenant_id=tenant_id,
            document_type=document_type,
            establishment_id=establishment_id,
            emission_point_id=emission_point_id,
            next_value=1,
        )
        session.add(sequence_row)
        await session.flush()
        # Re-select with the lock now that the row exists, closing the race
        # window between the initial lookup and the insert.
        sequence_row = await session.scalar(
            select(Sequence)
            .where(Sequence.id == sequence_row.id)
            .with_for_update()
        )
        assert sequence_row is not None  # noqa: S101 - guaranteed by the flush above

    reserved_value = sequence_row.next_value
    sequence_row.next_value = reserved_value + 1
    await session.flush()
    return f"{reserved_value:09d}"


async def create_invoice_draft(
    session: AsyncSession,
    context: AuthContext,
    data: InvoiceInput,
) -> SalesDocument:
    """Crea un borrador de factura recalculando TODOS los totales en backend.

    El cliente solo envia lineas crudas (cantidad, precio, descuento, codigo
    de tarifa); el backend resuelve la tarifa vigente por ``tax_code``,
    calcula base/impuesto por linea con ``FiscalCalculationPolicy`` y persiste
    exactamente ese resultado. Ningun monto enviado por el cliente se
    persiste sin recalcular.
    """

    if data.issue_date > today_in_fiscal_timezone():
        raise HTTPException(
            status_code=422,
            detail="issueDate cannot be in the future (America/Guayaquil)",
        )

    establishment = await _get_tenant_scoped_establishment(
        session, context, data.establishment_id
    )
    emission_point = await _get_tenant_scoped_emission_point(
        session, context, data.emission_point_id, establishment.id
    )
    party = await _get_tenant_scoped_party(session, context, data.customer_id)

    policy = resolve_fiscal_policy(data.issue_date)

    line_inputs: list[LineInput] = []
    line_products: list[uuid.UUID | None] = []
    line_descriptions: list[str] = []
    for line in data.lines:
        tax_category = await _get_tenant_scoped_tax_category_by_code(
            session, context, line.tax_code
        )
        if line.product_id is not None:
            await _get_tenant_scoped_product(session, context, line.product_id)
        line_inputs.append(
            LineInput(
                quantity=line.quantity,
                unit_price=line.unit_price,
                discount=line.discount,
                tax_rate=tax_category.rate,
                tax_sri_code=tax_category.sri_code,
            )
        )
        line_products.append(line.product_id)
        line_descriptions.append(line.description)

    calculation = policy.calculate_document(line_inputs)

    # Plan de pago: si el cliente declara cuotas, deben sumar exactamente el
    # total recalculado por el backend. Si no declara ninguna, se asume una
    # sola cuota al contado por el total con vencimiento en la fecha de emision
    # (el cliente no necesita conocer el total de antemano).
    if data.installments:
        installment_total = sum(
            (installment.amount for installment in data.installments), Decimal("0.00")
        )
        if installment_total != calculation.total:
            raise HTTPException(
                status_code=422,
                detail=(
                    "installments must sum exactly to the invoice total: "
                    f"expected {calculation.total}, got {installment_total}"
                ),
            )
        installments_to_persist = [
            (installment.due_date, installment.amount) for installment in data.installments
        ]
    else:
        installments_to_persist = [(data.issue_date, calculation.total)]

    sequential = await _reserve_sequential(
        session,
        tenant_id=context.tenant_id,
        document_type=_INVOICE_DOCUMENT_TYPE,
        establishment_id=establishment.id,
        emission_point_id=emission_point.id,
    )

    document = SalesDocument(
        tenant_id=context.tenant_id,
        document_type=_INVOICE_DOCUMENT_TYPE,
        establishment_id=establishment.id,
        emission_point_id=emission_point.id,
        sequential=sequential,
        access_key=None,
        party_id=party.id,
        issue_date=data.issue_date,
        status="DRAFT",
        currency="USD",
        subtotal=calculation.subtotal,
        tax_total=calculation.tax_total,
        total=calculation.total,
        fiscal_policy_version=policy.version,
    )
    session.add(document)
    await session.flush()

    for index, (calculated_line, product_id, description) in enumerate(
        zip(calculation.lines, line_products, line_descriptions, strict=True),
        start=1,
    ):
        session.add(
            SalesDocumentLine(
                tenant_id=context.tenant_id,
                sales_document_id=document.id,
                line_number=index,
                product_id=product_id,
                description=description,
                quantity=calculated_line.quantity,
                unit_price=calculated_line.unit_price,
                discount=calculated_line.discount,
                base_amount=calculated_line.base_amount,
                tax_sri_code=calculated_line.tax_sri_code,
                tax_rate=calculated_line.tax_rate,
                tax_amount=calculated_line.tax_amount,
            )
        )

    for sequence, (due_date, amount) in enumerate(installments_to_persist, start=1):
        session.add(
            SalesDocumentInstallment(
                tenant_id=context.tenant_id,
                sales_document_id=document.id,
                sequence=sequence,
                due_date=due_date,
                amount=amount,
            )
        )

    await session.flush()
    return document


async def list_sales_document_installments(
    session: AsyncSession,
    context: AuthContext,
    document_id: uuid.UUID,
) -> list[SalesDocumentInstallment]:
    """Cuotas persistidas del borrador de factura, en orden de secuencia.

    Usado por ``workers/receivables.py::handle_invoice_authorized`` para
    materializar ``ReceivableInstallment`` reales a partir del plan de pago
    declarado en ``InvoiceInput.installments``.
    """

    return list(
        (
            await session.scalars(
                select(SalesDocumentInstallment)
                .where(
                    SalesDocumentInstallment.tenant_id == context.tenant_id,
                    SalesDocumentInstallment.sales_document_id == document_id,
                )
                .order_by(SalesDocumentInstallment.sequence)
            )
        ).all()
    )


async def _get_tenant_scoped_authorized_invoice(
    session: AsyncSession,
    context: AuthContext,
    invoice_id: uuid.UUID,
) -> SalesDocument:
    """Resuelve la factura de sustento de una nota de credito.

    Debe existir, pertenecer al tenant activo y ser una ``INVOICE`` -- nunca
    otra ``CREDIT_NOTE`` (404 si cualquiera de estas condiciones falla, para
    no filtrar informacion sobre documentos de otro tenant) -- y estar en
    estado ``AUTHORIZED`` (422: una factura que aun no fue autorizada por el
    SRI no tiene un total firme que acreditar, y una ``REJECTED``/``VOIDED``
    no puede compensarse).
    """

    invoice = await session.scalar(
        select(SalesDocument).where(
            SalesDocument.id == invoice_id,
            SalesDocument.tenant_id == context.tenant_id,
            SalesDocument.document_type == _INVOICE_DOCUMENT_TYPE,
        )
    )
    if invoice is None:
        raise HTTPException(status_code=404, detail="Invoice not found")
    if invoice.status != "AUTHORIZED":
        raise HTTPException(
            status_code=422,
            detail=(
                "Credit notes can only be issued against an AUTHORIZED invoice, "
                f"current status is {invoice.status}"
            ),
        )
    return invoice


async def _creditable_balance_reserved(
    session: AsyncSession,
    context: AuthContext,
    invoice_id: uuid.UUID,
) -> Decimal:
    """Suma el ``total`` de las notas de credito que ya reservan saldo de esta factura.

    Incluye toda NC relacionada que no este en un estado terminal negativo
    (ver ``_CREDIT_NOTE_STATUSES_RESERVING_BALANCE``): esto evita que dos NC
    creadas en paralelo, ambas todavia sin autorizar, sumadas excedan el
    ``importeTotal`` de la factura antes de que el worker SRI resuelva su
    estado final (ADR 0008, seccion 5, "control de saldo").
    """

    rows = await session.execute(
        select(SalesDocument.total)
        .join(
            DocumentRelation,
            (DocumentRelation.credit_note_id == SalesDocument.id)
            & (DocumentRelation.tenant_id == SalesDocument.tenant_id),
        )
        .where(
            DocumentRelation.tenant_id == context.tenant_id,
            DocumentRelation.related_invoice_id == invoice_id,
            SalesDocument.status.in_(_CREDIT_NOTE_STATUSES_RESERVING_BALANCE),
        )
    )
    return sum((row[0] for row in rows.all()), Decimal("0.00"))


def _credit_note_line_inputs(
    credit_note_data: CreditNoteInput,
    invoice_lines: list[SalesDocumentLine],
) -> tuple[list[LineInput], list[uuid.UUID | None], list[str]]:
    """Valida y construye las lineas de la NC contra las lineas de la factura.

    Cada linea de la NC debe referenciar un ``product_id`` presente en la
    factura de sustento (422 si no); la cantidad y el importe bruto
    (``cantidad * precioUnitario``) de la NC nunca pueden superar los de la
    linea original (422 si exceden). El ``unit_price``/tarifa/``codigoPorcentaje``
    de la linea de sustento SIEMPRE se usan en la NC -- nunca lo que envie el
    cliente -- para cumplir la regla textual del ADR 0008: "la tarifa de IVA
    correspondera a la fecha de emision del documento de sustento". El
    descuento se prorratea por cantidad devuelta si el cliente no envia uno
    explicito distinto de cero, siguiendo la formula del ADR (seccion 5):
    ``descuento_nc = descuento_original * cantidad_devuelta / cantidad_original``.
    """

    lines_by_product: dict[uuid.UUID, SalesDocumentLine] = {
        line.product_id: line for line in invoice_lines if line.product_id is not None
    }

    line_inputs: list[LineInput] = []
    line_products: list[uuid.UUID | None] = []
    line_descriptions: list[str] = []

    for credit_line in credit_note_data.lines:
        if credit_line.product_id is None or credit_line.product_id not in lines_by_product:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Credit note line must reference a product billed on the "
                    "supporting invoice"
                ),
            )
        source_line = lines_by_product[credit_line.product_id]

        if credit_line.quantity > source_line.quantity:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Credit note line quantity cannot exceed the quantity billed "
                    "on the supporting invoice line"
                ),
            )

        # Prorratea el descuento original por la cantidad devuelta (ADR 0008
        # #5); si el cliente envio un descuento explicito mayor a ese
        # prorrateo, se rechaza: la NC nunca puede acreditar mas descuento que
        # el proporcional a lo devuelto.
        prorated_discount = (
            source_line.discount * credit_line.quantity / source_line.quantity
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        effective_discount = (
            credit_line.discount if credit_line.discount > Decimal("0.00") else prorated_discount
        )
        if effective_discount > prorated_discount:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Credit note line discount cannot exceed the prorated discount "
                    "of the supporting invoice line"
                ),
            )

        gross_amount = credit_line.quantity * source_line.unit_price
        if effective_discount > gross_amount:
            raise HTTPException(
                status_code=422,
                detail="Credit note line discount cannot exceed its gross amount",
            )

        line_inputs.append(
            LineInput(
                quantity=credit_line.quantity,
                unit_price=source_line.unit_price,
                discount=effective_discount,
                tax_rate=source_line.tax_rate,
                tax_sri_code=source_line.tax_sri_code,
            )
        )
        line_products.append(credit_line.product_id)
        line_descriptions.append(credit_line.description)

    return line_inputs, line_products, line_descriptions


async def create_credit_note(
    session: AsyncSession,
    context: AuthContext,
    data: CreditNoteInput,
) -> SalesDocument:
    """Crea un borrador de nota de credito referenciando una factura AUTHORIZED.

    Reglas aplicadas (E4-07, ADR 0008 seccion 5, ``docs/sprints/sprint-02.md``
    decision 6):

    1. La factura de sustento debe ser del mismo tenant, tipo ``INVOICE`` y
       estado ``AUTHORIZED`` (ver ``_get_tenant_scoped_authorized_invoice``).
    2. Cada linea de la NC referencia una linea/producto de la factura con
       cantidad/descuento nunca mayor al original (ver
       ``_credit_note_line_inputs``).
    3. La politica fiscal usada es la vigente A LA FECHA DE EMISION DE LA
       FACTURA DE SUSTENTO (``resolve_fiscal_policy(invoice.issue_date)``),
       nunca la fecha de la NC: una NC 2026 sobre un sustento de 2024-03-15
       usa ``ec-iva-v0`` (12% historico), no ``ec-iva-v1`` (vector 7 del ADR).
       La tarifa efectiva de cada linea es igual de todas formas la snapshot
       ya persistida en la linea de la factura (ver punto 2), asi que esta
       resolucion solo fija ``fiscal_policy_version`` en el documento --
       nunca se usa una tarifa distinta a la ya congelada en la factura.
    4. Control de saldo acreditable: la suma de ``total`` de esta NC mas las
       NC ya en curso/autorizadas de la misma factura nunca puede superar el
       ``total`` de la factura (422 si excede; el limite exacto SI se
       permite).
    5. Persiste ``SalesDocument`` (``CREDIT_NOTE``) + ``DocumentRelation``
       hacia la factura, con secuencial propio (mismo ``Sequence`` por
       ``document_type``) reservado atomicamente igual que una factura.
    """

    invoice = await _get_tenant_scoped_authorized_invoice(session, context, data.invoice_id)
    establishment = await _get_tenant_scoped_establishment(
        session, context, invoice.establishment_id
    )
    emission_point = await _get_tenant_scoped_emission_point(
        session, context, invoice.emission_point_id, establishment.id
    )
    party = await _get_tenant_scoped_party(session, context, invoice.party_id)

    invoice_lines = await list_sales_document_lines(session, context, invoice.id)
    line_inputs, line_products, line_descriptions = _credit_note_line_inputs(
        data, invoice_lines
    )

    # Punto 3 del docstring: version vigente a la fecha del SUSTENTO, nunca a
    # la fecha de emision de la NC (ADR 0008 #5, vectores 6/7).
    policy: FiscalCalculationPolicy = resolve_fiscal_policy(invoice.issue_date)
    calculation = policy.calculate_document(line_inputs)

    already_reserved = await _creditable_balance_reserved(session, context, invoice.id)
    if already_reserved + calculation.total > invoice.total:
        available = invoice.total - already_reserved
        raise HTTPException(
            status_code=422,
            detail=(
                "Credit note total exceeds the creditable balance of the supporting "
                f"invoice: available {available}, requested {calculation.total}"
            ),
        )

    sequential = await _reserve_sequential(
        session,
        tenant_id=context.tenant_id,
        document_type=_CREDIT_NOTE_DOCUMENT_TYPE,
        establishment_id=establishment.id,
        emission_point_id=emission_point.id,
    )

    if invoice.issue_date > today_in_fiscal_timezone():
        # Guardia defensiva: nunca deberia ocurrir porque create_invoice_draft
        # ya rechaza fechas futuras, pero protege contra datos migrados.
        raise HTTPException(status_code=422, detail="Supporting invoice has a future issue date")

    document = SalesDocument(
        tenant_id=context.tenant_id,
        document_type=_CREDIT_NOTE_DOCUMENT_TYPE,
        establishment_id=establishment.id,
        emission_point_id=emission_point.id,
        sequential=sequential,
        access_key=None,
        party_id=party.id,
        issue_date=today_in_fiscal_timezone(),
        status="DRAFT",
        currency=invoice.currency,
        subtotal=calculation.subtotal,
        tax_total=calculation.tax_total,
        total=calculation.total,
        fiscal_policy_version=policy.version,
        reason=data.reason,
    )
    session.add(document)
    await session.flush()

    session.add(
        DocumentRelation(
            tenant_id=context.tenant_id,
            credit_note_id=document.id,
            related_invoice_id=invoice.id,
        )
    )

    for index, (calculated_line, product_id, description) in enumerate(
        zip(calculation.lines, line_products, line_descriptions, strict=True),
        start=1,
    ):
        session.add(
            SalesDocumentLine(
                tenant_id=context.tenant_id,
                sales_document_id=document.id,
                line_number=index,
                product_id=product_id,
                description=description,
                quantity=calculated_line.quantity,
                unit_price=calculated_line.unit_price,
                discount=calculated_line.discount,
                base_amount=calculated_line.base_amount,
                tax_sri_code=calculated_line.tax_sri_code,
                tax_rate=calculated_line.tax_rate,
                tax_amount=calculated_line.tax_amount,
            )
        )
    await session.flush()
    return document


async def create_and_issue_credit_note(
    session: AsyncSession,
    context: AuthContext,
    data: CreditNoteInput,
    *,
    idempotency_key: str,
    correlation_id: str,
) -> SalesDocument:
    """Crea y emite una nota de credito en una sola operacion (``POST /credit-notes``).

    ``contracts/openapi.yaml`` declara ``createAndIssueCreditNote`` como un
    unico endpoint que devuelve ``Operation`` (202): a diferencia de facturas
    (borrador y emision separados en dos endpoints), una nota de credito se
    crea y se encola para firma/transmision en la misma llamada. Internamente
    reutiliza exactamente ``create_credit_note`` + ``issue_document`` (mismas
    validaciones, mismo pipeline de firma/XML/RIDE/MinIO), sin duplicar
    logica.
    """

    document = await create_credit_note(session, context, data)
    return await issue_document(
        session,
        context,
        document.id,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
    )


async def get_sales_document(
    session: AsyncSession,
    context: AuthContext,
    document_id: uuid.UUID,
) -> SalesDocument:
    document = await session.scalar(
        select(SalesDocument).where(
            SalesDocument.id == document_id,
            SalesDocument.tenant_id == context.tenant_id,
        )
    )
    if document is None:
        raise HTTPException(status_code=404, detail="Sales document not found")
    return document


async def list_sales_document_lines(
    session: AsyncSession,
    context: AuthContext,
    document_id: uuid.UUID,
) -> list[SalesDocumentLine]:
    return list(
        (
            await session.scalars(
                select(SalesDocumentLine)
                .where(
                    SalesDocumentLine.tenant_id == context.tenant_id,
                    SalesDocumentLine.sales_document_id == document_id,
                )
                .order_by(SalesDocumentLine.line_number)
            )
        ).all()
    )


_LIST_SALES_DOCUMENTS_MAX_LIMIT = 100


async def list_sales_documents(
    session: AsyncSession,
    context: AuthContext,
    document_type: str | None = None,
    *,
    query: str | None = None,
    status: str | None = None,
    limit: int = _LIST_SALES_DOCUMENTS_MAX_LIMIT,
) -> list[SalesDocument]:
    """Lista documentos del tenant activo (``GET /invoices``, Fase 5).

    ``query`` filtra por coincidencia parcial de ``sequential`` o
    ``access_key`` (busqueda operativa tipica: "encontrar la factura con
    secuencial/clave X"), ``status`` filtra por estado exacto. Tenant-scoped
    siempre; nunca se filtra por un ``tenant_id`` recibido del cliente. El
    limite maximo es ``_LIST_SALES_DOCUMENTS_MAX_LIMIT`` (100), igual que el
    resto de listados de este modulo (``masters.search_parties``/
    ``search_products``), y se aplica siempre aunque el llamador pida mas.
    """

    statement = select(SalesDocument).where(SalesDocument.tenant_id == context.tenant_id)
    if document_type is not None:
        statement = statement.where(SalesDocument.document_type == document_type)
    if status is not None:
        statement = statement.where(SalesDocument.status == status)
    if query:
        pattern = f"%{query}%"
        statement = statement.where(
            (SalesDocument.sequential.ilike(pattern))
            | (SalesDocument.access_key.ilike(pattern))
        )
    effective_limit = min(limit, _LIST_SALES_DOCUMENTS_MAX_LIMIT)
    return list(
        (
            await session.scalars(
                statement.order_by(SalesDocument.issue_date.desc()).limit(effective_limit)
            )
        ).all()
    )


async def _get_latest_sri_transmission(
    session: AsyncSession,
    context: AuthContext,
    document_id: uuid.UUID,
) -> SRITransmission | None:
    transmission: SRITransmission | None = await session.scalar(
        select(SRITransmission)
        .where(
            SRITransmission.tenant_id == context.tenant_id,
            SRITransmission.sales_document_id == document_id,
        )
        .order_by(SRITransmission.updated_at.desc(), SRITransmission.created_at.desc())
        .limit(1)
    )
    return transmission


def _latest_message(transmission: SRITransmission) -> str | None:
    if not transmission.messages:
        return None
    last = transmission.messages[-1]
    message = last.get("message") if isinstance(last, dict) else None
    return message if isinstance(message, str) else None


async def to_sales_document_read(
    session: AsyncSession,
    context: AuthContext,
    document: SalesDocument,
) -> SalesDocumentRead:
    lines = await list_sales_document_lines(session, context, document.id)
    transmission = await _get_latest_sri_transmission(session, context, document.id)
    sri_transmission = (
        SRITransmissionRead(
            status=transmission.status,
            message=_latest_message(transmission),
            last_attempt_at=transmission.updated_at,
            authorization_number=transmission.authorization_number,
        )
        if transmission is not None
        else None
    )
    return SalesDocumentRead(
        id=document.id,
        type=document.document_type,
        status=document.status,
        sequential=document.sequential,
        issue_date=document.issue_date,
        access_key=document.access_key,
        subtotal=document.subtotal,
        tax=document.tax_total,
        total=document.total,
        currency=document.currency,
        party_id=document.party_id,
        establishment_id=document.establishment_id,
        emission_point_id=document.emission_point_id,
        fiscal_policy_version=document.fiscal_policy_version,
        reason=document.reason,
        authorization_number=document.authorization_number,
        authorized_at=document.authorized_at,
        sri_transmission=sri_transmission,
        lines=[
            SalesDocumentLineRead(
                id=line.id,
                line_number=line.line_number,
                product_id=line.product_id,
                description=line.description,
                quantity=line.quantity,
                unit_price=line.unit_price,
                discount=line.discount,
                base_amount=line.base_amount,
                tax_code=line.tax_sri_code,
                tax_rate=line.tax_rate,
                tax_amount=line.tax_amount,
            )
            for line in lines
        ],
    )


async def _load_issue_context(
    session: AsyncSession,
    context: AuthContext,
    document: SalesDocument,
) -> tuple[Establishment, EmissionPoint, Party]:
    establishment = await _get_tenant_scoped_establishment(
        session, context, document.establishment_id
    )
    emission_point = await _get_tenant_scoped_emission_point(
        session, context, document.emission_point_id, establishment.id
    )
    party = await _get_tenant_scoped_party(session, context, document.party_id)
    return establishment, emission_point, party


async def _load_credit_note_supporting_invoice(
    session: AsyncSession,
    context: AuthContext,
    credit_note_id: uuid.UUID,
) -> tuple[SalesDocument, Establishment, EmissionPoint]:
    """Resuelve la factura de sustento de una NC ya persistida via ``DocumentRelation``.

    Usado solo durante la emision (``issue_document``): en ese punto la
    relacion ya fue creada por ``create_credit_note`` en la misma transaccion
    logica que el ``SalesDocument`` de la NC, asi que su ausencia indica un
    estado inconsistente (documento CREDIT_NOTE sin relacion), no un caso de
    negocio valido.
    """

    relation = await session.scalar(
        select(DocumentRelation).where(
            DocumentRelation.tenant_id == context.tenant_id,
            DocumentRelation.credit_note_id == credit_note_id,
        )
    )
    if relation is None:
        raise HTTPException(
            status_code=500,
            detail="Credit note is missing its DocumentRelation to a supporting invoice",
        )
    related_invoice = await get_sales_document(session, context, relation.related_invoice_id)
    related_establishment = await _get_tenant_scoped_establishment(
        session, context, related_invoice.establishment_id
    )
    related_emission_point = await _get_tenant_scoped_emission_point(
        session, context, related_invoice.emission_point_id, related_establishment.id
    )
    return related_invoice, related_establishment, related_emission_point


async def issue_document(
    session: AsyncSession,
    context: AuthContext,
    document_id: uuid.UUID,
    *,
    idempotency_key: str,
    correlation_id: str,
) -> SalesDocument:
    """Emite un ``SalesDocument`` (factura o nota de credito) en ``DRAFT``.

    Flujo (E4-04/E4-08/E4-07, ``docs/sprints/sprint-02.md`` decisiones 6 y 8):
    identico para ambos tipos de documento -- una nota de credito reutiliza
    exactamente este mismo pipeline, solo cambia que construye
    ``infoNotaCredito`` (``sri_xml.build_credit_note_xml``) en vez de
    ``infoFactura``, resolviendo su factura de sustento via
    ``DocumentRelation`` (ver ``_load_credit_note_supporting_invoice``).

    1. Valida que el documento este en ``DRAFT`` (un documento ya ``SIGNED``
       o posterior es inmutable ante un reintento de emision).
    2. Calcula la clave de acceso SRI (modulo 11) y la persiste; el
       ``document_code`` es ``01`` para factura y ``04`` para nota de
       credito (``access_key.py``).
    3. Construye el XML SRI desde los mismos datos ya persistidos (nunca
       recalcula montos, ver ``sri_xml.py``).
    4. Firma el XML (XAdES-BES/``signxml``) y audita el fingerprint SHA-256
       del certificado usado en un ``AuditEvent`` propio.
    5. Genera el RIDE PDF desde los mismos datos que el XML.
    6. Sube ambos artefactos a MinIO con checksum verificado y los registra
       como ``DocumentArtifact``.
    7. Transiciona el documento a ``SIGNED``.

    El evento outbox ``invoice.signed`` que dispara la transmision SRI lo
    agrega ``execute_idempotent`` (llamador de esta funcion) en la MISMA
    transaccion, vía el parametro ``event_type``; esta funcion no escribe el
    outbox directamente para no duplicar esa responsabilidad. El mismo
    ``event_type`` se reutiliza para notas de credito: ``workers/tasks.py``
    rutea por ``event_type`` (no por ``aggregate_type``), asi que
    ``workers/sri_transmission.handle_invoice_signed`` procesa ambos tipos de
    documento sin cambios.
    """

    document = await get_sales_document(session, context, document_id)
    if document.status != "DRAFT":
        raise HTTPException(
            status_code=409,
            detail=f"Sales document must be DRAFT to issue, current status is {document.status}",
        )

    establishment, emission_point, party = await _load_issue_context(session, context, document)
    lines = await list_sales_document_lines(session, context, document.id)
    tenant = await masters.get_active_tenant(session, context.tenant_id)
    fiscal = await fiscal_settings.get_or_create(session, context.tenant_id)
    runtime_settings = get_settings()
    if fiscal.sri_environment == "2" and runtime_settings.APP_ENV not in {
        "release",
        "production",
    }:
        raise HTTPException(
            status_code=409,
            detail="Production SRI emission is blocked outside release/production",
        )

    p12_bytes: bytes | None = None
    certificate_password: bytes | None = None
    if fiscal.certificate_object_key and fiscal.certificate_password_encrypted:
        p12_bytes, certificate_password, _fiscal = (
            await fiscal_settings.load_tenant_signing_credentials(session, context.tenant_id)
        )
    elif runtime_settings.APP_ENV not in {"development", "test"}:
        raise HTTPException(status_code=409, detail="Signing certificate is not configured")

    document_code = (
        access_key_service.INVOICE_DOCUMENT_CODE
        if document.document_type == _INVOICE_DOCUMENT_TYPE
        else access_key_service.CREDIT_NOTE_DOCUMENT_CODE
    )
    access_key = access_key_service.build_access_key(
        access_key_service.AccessKeyInput(
            issue_date=document.issue_date,
            document_code=document_code,
            ruc=tenant.ruc,
            environment=fiscal.sri_environment,
            establishment_code=establishment.code,
            emission_point_code=emission_point.code,
            sequential=document.sequential,
            numeric_code=access_key_service.generate_numeric_code(),
        )
    )
    document.access_key = access_key
    await session.flush()

    if document.document_type == _INVOICE_DOCUMENT_TYPE:
        xml_result = sri_xml.build_invoice_xml(
            document=document,
            lines=lines,
            establishment=establishment,
            emission_point=emission_point,
            tenant_ruc=tenant.ruc,
            tenant_legal_name=tenant.name,
            tenant_commercial_address=establishment.address,
            buyer=party,
        )
    else:
        related_invoice, related_establishment, related_emission_point = (
            await _load_credit_note_supporting_invoice(session, context, document.id)
        )
        xml_result = sri_xml.build_credit_note_xml(
            document=document,
            lines=lines,
            establishment=establishment,
            emission_point=emission_point,
            tenant_ruc=tenant.ruc,
            tenant_legal_name=tenant.name,
            tenant_commercial_address=establishment.address,
            buyer=party,
            related_invoice_sequential_full=(
                f"{related_establishment.code}-{related_emission_point.code}-"
                f"{related_invoice.sequential}"
            ),
            related_invoice_issue_date=related_invoice.issue_date,
            related_invoice_access_key=related_invoice.access_key or "",
            reason=document.reason or "",
        )

    signing_result = signing.sign_xml(
        xml_result.xml_bytes,
        p12_bytes=p12_bytes,
        password=certificate_password,
    )

    await append_audit(
        session,
        context=context,
        action="invoice.signed_with_certificate",
        entity_type="sales_document",
        entity_id=str(document.id),
        correlation_id=correlation_id,
        idempotency_key=idempotency_key,
        details={
            "certificate_fingerprint_sha256": signing_result.certificate_fingerprint_sha256,
            "access_key": access_key,
        },
    )

    ride_pdf_bytes = ride.build_ride_pdf(
        document=document,
        lines=lines,
        establishment=establishment,
        emission_point=emission_point,
        tenant_ruc=tenant.ruc,
        tenant_legal_name=tenant.name,
        buyer=party,
    )

    xml_upload = await storage.upload_artifact(
        tenant_id=str(context.tenant_id),
        document_id=str(document.id),
        artifact_type="xml-signed",
        version=1,
        data=signing_result.signed_xml,
    )
    session.add(
        DocumentArtifact(
            tenant_id=context.tenant_id,
            sales_document_id=document.id,
            artifact_type="xml-signed",
            object_key=xml_upload.object_key,
            sha256=xml_upload.sha256,
            version=1,
        )
    )

    ride_upload = await storage.upload_artifact(
        tenant_id=str(context.tenant_id),
        document_id=str(document.id),
        artifact_type="ride-pdf",
        version=1,
        data=ride_pdf_bytes,
    )
    session.add(
        DocumentArtifact(
            tenant_id=context.tenant_id,
            sales_document_id=document.id,
            artifact_type="ride-pdf",
            object_key=ride_upload.object_key,
            sha256=ride_upload.sha256,
            version=1,
        )
    )

    document.status = "SIGNED"
    await session.flush()
    return document


async def list_document_artifacts(
    session: AsyncSession,
    context: AuthContext,
    document_id: uuid.UUID,
) -> list[DocumentArtifactRead]:
    """Lista los artefactos (XML firmado, RIDE PDF) de un documento del tenant.

    Confirma primero que el documento pertenece al tenant activo (404 si no)
    antes de listar sus artefactos, igual que el resto de los accesos
    tenant-scoped de este modulo.
    """

    await get_sales_document(session, context, document_id)
    rows = await session.scalars(
        select(DocumentArtifact)
        .where(
            DocumentArtifact.tenant_id == context.tenant_id,
            DocumentArtifact.sales_document_id == document_id,
        )
        .order_by(DocumentArtifact.artifact_type, DocumentArtifact.version.desc())
    )
    return [
        DocumentArtifactRead(
            id=artifact.id,
            artifact_type=artifact.artifact_type,
            sha256=artifact.sha256,
            version=artifact.version,
            created_at=artifact.created_at,
        )
        for artifact in rows.all()
    ]


async def get_document_artifact(
    session: AsyncSession,
    context: AuthContext,
    document_id: uuid.UUID,
    artifact_id: uuid.UUID,
) -> DocumentArtifact:
    await get_sales_document(session, context, document_id)
    artifact = await session.scalar(
        select(DocumentArtifact).where(
            DocumentArtifact.id == artifact_id,
            DocumentArtifact.tenant_id == context.tenant_id,
            DocumentArtifact.sales_document_id == document_id,
        )
    )
    if artifact is None:
        raise HTTPException(status_code=404, detail="Document artifact not found")
    return artifact


async def create_artifact_download(
    session: AsyncSession,
    context: AuthContext,
    document_id: uuid.UUID,
    artifact_id: uuid.UUID,
) -> ArtifactDownloadRead:
    """Emite una URL prefirmada de corta duracion para descargar un artefacto.

    La autorizacion (scope ``invoices:read`` + tenant ownership) ya la valido
    el endpoint/``get_document_artifact`` antes de llegar aqui; esta funcion
    solo pide a MinIO la URL firmada, nunca expone una ruta publica ni
    permanente (ADR 0005).
    """

    document = await get_sales_document(session, context, document_id)
    artifact = await get_document_artifact(session, context, document_id, artifact_id)
    extension = "xml" if artifact.artifact_type == "xml-signed" else "pdf"
    prefix = "FACTURA" if document.document_type == "INVOICE" else "NOTA-CREDITO"
    file_name = f"{prefix}-{document.sequential}.{extension}"
    content_type = "application/xml" if extension == "xml" else "application/pdf"
    download_url = await storage.generate_presigned_download_url(
        object_key=artifact.object_key,
        file_name=file_name,
        content_type=content_type,
    )
    return ArtifactDownloadRead(
        download_url=download_url,
        expires_in_seconds=int(storage.PRESIGNED_URL_EXPIRY.total_seconds()),
        file_name=file_name,
    )
