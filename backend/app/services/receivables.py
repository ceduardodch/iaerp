"""Servicios del contexto Receivables (Sprint 3).

Este módulo contiene la lógica de negocio de cartera de clientes:

**Fase 1 (E5-01/E5-02)**: Cálculo de saldo on-demand sin columnas persistidas.
- ``compute_installment_balance``: saldo de una cuota sumando movimientos activos
- ``compute_receivable_balance``: saldo completo sumando todas las cuotas
- ``get_receivable``/``list_receivables``: consultas con filtros y aging

**Fase 2 (E5-03/E5-04/E5-08)**: Escritura de movimientos con validación de saldo.
- ``lock_receivable``: SELECT FOR UPDATE para serializar aplicaciones
- ``record_payment``: cobro con retenciones/descuentos, oldest-first
- ``apply_credit_note``: aplicar NC, crear CustomerCredit si excede

**Fase 3 (E5-05/E5-09)**: Aging y reverso.
- ``classify_aging_bucket``: función pura de bucket por días de mora
- ``installment_agings_for_receivable``/``compute_aging_summary``: agregados
- ``reverse_movement``: reverso auditado sin editar el original

Todas las operaciones de escritura usan ``lock_receivable`` para garantizar
que el saldo nunca sea negativo bajo concurrencia (misma transacción que
inserta los ``Movement``). El saldo es siempre derivado: ``amount - sum(movs)``,
nunca una columna que pueda desincronizarse (docs/sprints/sprint-03.md decisión 2).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal
from xml.etree.ElementTree import Element

from defusedxml.ElementTree import fromstring as safe_fromstring  # type: ignore[import-untyped]
from fastapi import HTTPException
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthContext
from app.core.timezones import today_in_fiscal_timezone
from app.integrations.notifications.protocol import Notifier, ReminderRequest
from app.models.billing import SalesDocument, SalesDocumentInstallment
from app.models.masters import EmissionPoint, Establishment, Party
from app.models.platform import Tenant
from app.models.receivables import (
    CollectionPolicy,
    CollectionReminder,
    CustomerCredit,
    Movement,
    Receivable,
    ReceivableInstallment,
)
from app.schemas.receivables import (
    AccountItemRead,
    AgingBucket,
    AgingBucketTotalRead,
    AgingRead,
    AgingSummaryRead,
    CollectionsBreakdownRead,
    PartyAgingBucketTotalRead,
    PaymentInput,
    ReminderInput,
    RetentionBatchItemRead,
    RetentionBatchRead,
    RetentionXmlPreviewItem,
    RetentionXmlPreviewRead,
)
from app.services.collection_email import render_collection_email
from app.services.unit_of_work import append_audit

MAX_RETENTION_XML_BYTES = 2 * 1024 * 1024

# Estados de AccountItem (contrato) -> filtros sobre Receivable.status persistido
_ACCOUNT_STATUS_TO_RECEIVABLE_STATUSES: dict[str, tuple[str, ...]] = {
    "OPEN": ("OPEN",),
    "PARTIAL": ("PARTIALLY_PAID",),
    "SETTLED": ("PAID",),
    "VOIDED": ("VOID",),
}

# --- Clases auxiliares para aging -------------------------------------------


@dataclass(frozen=True)
class InstallmentAging:
    """Aging de UNA cuota abierta, para el detalle de un receivable."""

    installment_id: uuid.UUID
    due_date: date
    open_amount: Decimal
    bucket: str
    days_overdue: int


@dataclass(frozen=True)
class AgingBucketTotal:
    """Total agregado de un bucket dentro de un ``AgingSummary``."""

    bucket: str
    total: Decimal
    installment_count: int


@dataclass(frozen=True)
class PartyAgingBucketTotal:
    """Total agregado de un bucket para un cliente especifico."""

    party_id: uuid.UUID
    bucket: str
    total: Decimal
    installment_count: int


@dataclass(frozen=True)
class AgingSummary:
    """Resumen de aging por tenant (``GET /receivables/aging``, E5-05)."""

    as_of: date
    buckets: list[AgingBucketTotal]
    by_party: list[PartyAgingBucketTotal]


@dataclass(frozen=True)
class ReceivableSummary:
    """Vista agregada de un ``Receivable`` para ``GET /receivables`` (``AccountItem``)."""

    id: uuid.UUID
    party_id: uuid.UUID
    invoice_sequential: str | None
    status: str
    original_amount: Decimal
    open_amount: Decimal
    currency: str
    due_date: date | None = None
    aging_bucket: str | None = None
    aging_days_overdue: int | None = None


def _xml_text(parent: Element, path: str) -> str | None:
    """Devuelve texto XML limpio sin registrar el documento no confiable."""
    element = parent.find(path)
    if element is None or element.text is None:
        return None
    value = element.text.strip()
    return value or None


def _decimal_xml(value: str | None, *, field: str) -> Decimal:
    try:
        parsed = Decimal(value or "")
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Invalid retention XML {field}") from exc
    if not parsed.is_finite():
        raise HTTPException(status_code=422, detail=f"Invalid retention XML {field}")
    return parsed


def _parse_authorized_retention_xml(
    xml_bytes: bytes,
) -> tuple[str, str, list[RetentionXmlPreviewItem], str]:
    """Lee el sobre SRI y su comprobante interno sin ejecutar contenido XML.

    Solo admite comprobantes de retención autorizados. El archivo se procesa
    en memoria, no se persiste ni se envía a un proveedor externo.
    """
    if not xml_bytes or len(xml_bytes) > MAX_RETENTION_XML_BYTES:
        raise HTTPException(status_code=422, detail="Retention XML must be between 1 byte and 2 MB")
    try:
        envelope = safe_fromstring(xml_bytes)
    except Exception as exc:
        raise HTTPException(status_code=422, detail="Invalid retention XML") from exc
    if envelope.tag.rsplit("}", 1)[-1] != "autorizacion":
        raise HTTPException(
            status_code=422, detail="Retention XML must use the SRI authorization envelope"
        )
    if _xml_text(envelope, "estado") != "AUTORIZADO":
        raise HTTPException(status_code=422, detail="Retention XML is not authorized by SRI")
    authorization_number = _xml_text(envelope, "numeroAutorizacion")
    comprobante = _xml_text(envelope, "comprobante")
    if not authorization_number or not authorization_number.isdigit() or not comprobante:
        raise HTTPException(
            status_code=422, detail="Retention XML lacks SRI authorization evidence"
        )
    try:
        retention_xml = safe_fromstring(comprobante.encode("utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=422, detail="Invalid embedded retention receipt") from exc
    if retention_xml.tag.rsplit("}", 1)[-1] != "comprobanteRetencion":
        raise HTTPException(status_code=422, detail="XML is not a retention receipt")
    access_key = _xml_text(retention_xml, "infoTributaria/claveAcceso")
    issuer_ruc = _xml_text(retention_xml, "infoTributaria/ruc")
    retained_ruc = _xml_text(retention_xml, "infoCompRetencion/identificacionSujetoRetenido")
    if access_key != authorization_number or not issuer_ruc or not retained_ruc:
        raise HTTPException(
            status_code=422, detail="Retention XML authorization evidence is inconsistent"
        )

    entries: list[tuple[Element, str | None]] = []
    for support in retention_xml.findall("docsSustento/docSustento"):
        supporting_document = _xml_text(support, "numDocSustento")
        entries.extend(
            (item, supporting_document) for item in support.findall("retenciones/retencion")
        )
    entries.extend(
        (item, _xml_text(item, "numDocSustento"))
        for item in retention_xml.findall("impuestos/impuesto")
    )
    if not entries:
        raise HTTPException(
            status_code=422, detail="Retention XML has no supported retention items"
        )

    items: list[RetentionXmlPreviewItem] = []
    supporting_documents: set[str] = set()
    for item, supporting_document in entries:
        tax_kind = _xml_text(item, "codigo")
        if tax_kind not in {"1", "2"}:
            continue
        if not supporting_document:
            raise HTTPException(status_code=422, detail="Retention XML lacks supporting document")
        amount = _decimal_xml(_xml_text(item, "valorRetenido"), field="withheld amount")
        base_amount = _decimal_xml(_xml_text(item, "baseImponible"), field="tax base")
        rate = _decimal_xml(_xml_text(item, "porcentajeRetener"), field="withholding rate")
        if amount <= 0 or base_amount < 0 or rate < 0:
            raise HTTPException(status_code=422, detail="Retention XML has invalid amounts")
        code = _xml_text(item, "codigoRetencion")
        if not code:
            raise HTTPException(status_code=422, detail="Retention XML lacks SRI retention code")
        supporting_documents.add(
            "".join(character for character in supporting_document if character.isdigit())
        )
        items.append(
            RetentionXmlPreviewItem(
                kind="RETENTION_RENTA" if tax_kind == "1" else "RETENTION_IVA",
                amount=amount.quantize(Decimal("0.01")),
                base_amount=base_amount.quantize(Decimal("0.01")),
                rate=rate,
                sri_retention_code=code,
            )
        )
    if not items or len(supporting_documents) != 1:
        raise HTTPException(
            status_code=422, detail="Retention XML has unsupported or inconsistent retentions"
        )
    return (
        authorization_number,
        next(iter(supporting_documents)),
        items,
        f"{issuer_ruc}|{retained_ruc}",
    )


async def preview_retention_xml(
    session: AsyncSession,
    *,
    context: AuthContext,
    receivable_id: uuid.UUID,
    xml_bytes: bytes,
) -> RetentionXmlPreviewRead:
    """Valida que un XML SRI autorizado respalda retenciones de esta factura."""
    authorization_number, supporting_document, items, parties = _parse_authorized_retention_xml(
        xml_bytes
    )
    issuer_ruc, retained_ruc = parties.split("|", maxsplit=1)
    receivable = await get_receivable(
        session, tenant_id=context.tenant_id, receivable_id=receivable_id
    )
    document = await session.scalar(
        select(SalesDocument).where(
            SalesDocument.tenant_id == context.tenant_id,
            SalesDocument.id == receivable.sales_document_id,
        )
    )
    party = await session.scalar(
        select(Party).where(Party.tenant_id == context.tenant_id, Party.id == receivable.party_id)
    )
    tenant = await session.scalar(select(Tenant).where(Tenant.id == context.tenant_id))
    if document is None or party is None or tenant is None:
        raise HTTPException(status_code=422, detail="Receivable fiscal context is incomplete")
    establishment = await session.scalar(
        select(Establishment).where(
            Establishment.tenant_id == context.tenant_id,
            Establishment.id == document.establishment_id,
        )
    )
    emission_point = await session.scalar(
        select(EmissionPoint).where(
            EmissionPoint.tenant_id == context.tenant_id,
            EmissionPoint.id == document.emission_point_id,
        )
    )
    expected_support = (
        f"{establishment.code}{emission_point.code}{document.sequential}"
        if establishment is not None and emission_point is not None
        else None
    )
    if issuer_ruc != party.identification_number:
        raise HTTPException(status_code=422, detail="Retention issuer does not match this customer")
    if retained_ruc != tenant.ruc:
        raise HTTPException(status_code=422, detail="Retention subject does not match this company")
    if supporting_document != expected_support:
        raise HTTPException(
            status_code=422, detail="Retention supporting document does not match this invoice"
        )
    total = sum((item.amount for item in items), Decimal("0.00"))
    open_balance = await compute_receivable_balance(
        session, tenant_id=context.tenant_id, receivable=receivable
    )
    if total > open_balance:
        raise HTTPException(
            status_code=422, detail="Retention total exceeds this invoice open balance"
        )
    return RetentionXmlPreviewRead(
        authorization_number=authorization_number,
        supporting_document=supporting_document,
        retentions=items,
    )


async def import_retention_xml_batch(
    session: AsyncSession,
    *,
    context: AuthContext,
    files: list[tuple[str, bytes]],
    apply: bool,
    correlation_id: str,
    idempotency_key: str,
) -> RetentionBatchRead:
    """Relaciona XML SRI con factura y opcionalmente registra retenciones exactas."""
    results: list[RetentionBatchItemRead] = []
    for file_name, xml_bytes in files:
        try:
            _, support, _, _ = _parse_authorized_retention_xml(xml_bytes)
            document = await session.scalar(
                select(SalesDocument)
                .join(
                    Establishment,
                    (Establishment.tenant_id == SalesDocument.tenant_id)
                    & (Establishment.id == SalesDocument.establishment_id),
                )
                .join(
                    EmissionPoint,
                    (EmissionPoint.tenant_id == SalesDocument.tenant_id)
                    & (EmissionPoint.id == SalesDocument.emission_point_id),
                )
                .where(
                    SalesDocument.tenant_id == context.tenant_id,
                    SalesDocument.document_type == "INVOICE",
                    SalesDocument.sequential == support[-9:],
                    Establishment.code == support[:3],
                    EmissionPoint.code == support[3:6],
                )
            )
            if document is None:
                raise HTTPException(
                    status_code=422, detail="No invoice matches the supporting document"
                )
            receivable = await session.scalar(
                select(Receivable).where(
                    Receivable.tenant_id == context.tenant_id,
                    Receivable.sales_document_id == document.id,
                )
            )
            if receivable is None:
                raise HTTPException(status_code=422, detail="Invoice has no open receivable")
            preview = await preview_retention_xml(
                session, context=context, receivable_id=receivable.id, xml_bytes=xml_bytes
            )
            total = sum((item.amount for item in preview.retentions), Decimal("0.00"))
            if apply:
                duplicate = await session.scalar(
                    select(Movement.id).where(
                        Movement.tenant_id == context.tenant_id,
                        Movement.receivable_id == receivable.id,
                        Movement.movement_type == "RETENTION",
                        Movement.support_reference.like(f"{preview.authorization_number} |%"),
                    )
                )
                if duplicate is not None:
                    raise HTTPException(
                        status_code=422, detail="Retention authorization was already registered"
                    )
                await record_payment(
                    session,
                    context,
                    receivable.id,
                    PaymentInput(
                        cash_amount=Decimal("0.00"),
                        payment_date=today_in_fiscal_timezone(),
                        retentions=[
                            {
                                "kind": item.kind,
                                "amount": item.amount,
                                "reason": f"Código SRI {item.sri_retention_code}",
                                "document_reference": preview.authorization_number,
                            }
                            for item in preview.retentions
                        ],
                    ),
                    correlation_id=correlation_id,
                    idempotency_key=idempotency_key,
                )
            results.append(
                RetentionBatchItemRead(
                    file_name=file_name,
                    receivable_id=receivable.id,
                    authorization_number=preview.authorization_number,
                    supporting_document=preview.supporting_document,
                    invoice_sequential=document.sequential,
                    total=total,
                    status="MATCHED",
                    detail="Registrada" if apply else "Lista para registrar",
                )
            )
        except HTTPException as exc:
            results.append(
                RetentionBatchItemRead(
                    file_name=file_name, status="REVIEW_REQUIRED", detail=str(exc.detail)
                )
            )
    return RetentionBatchRead(items=results)


# --- Aging (E5-05): función pura y agregados ----------------------------------


def classify_aging_bucket(*, due_date: date, as_of: date) -> tuple[AgingBucket, int]:
    """Clasifica una cuota en su bucket de aging según días de mora.

    Función pura determinista: misma ``due_date`` + ``as_of`` = mismo bucket.
    Buckets fijos (docs/sprints/sprint-03.md decisión 4):
    - ``CURRENT``: no vencida (due_date > as_of) o exactamente hoy
    - ``1-15``: 1-15 días de mora
    - ``16-30``, ``31-60``, ``61-90``: rangos siguientes
    - ``90+``: más de 90 días

    Args:
        due_date: Fecha de vencimiento de la cuota
        as_of: Fecha de corte local (America/Guayaquil)

    Returns:
        Tupla ``(bucket, days_overdue)`` donde ``days_overdue`` es 0 si CURRENT
    """
    if due_date >= as_of:
        return "CURRENT", 0

    days_overdue = (as_of - due_date).days

    if days_overdue <= 15:
        return "1-15", days_overdue
    if days_overdue <= 30:
        return "16-30", days_overdue
    if days_overdue <= 60:
        return "31-60", days_overdue
    if days_overdue <= 90:
        return "61-90", days_overdue
    return "90+", days_overdue


def _reversed_movement_ids(tenant_id: uuid.UUID) -> Select[tuple[uuid.UUID | None]]:
    """Subconsulta de ids de movimientos que ya fueron revertidos por un REVERSAL.

    Un ``REVERSAL`` apunta al movimiento que deshace via
    ``reversed_movement_id``; el movimiento apuntado no debe contar hacia el
    saldo. Se excluye por separado de las propias filas REVERSAL.
    """
    return select(Movement.reversed_movement_id).where(
        Movement.tenant_id == tenant_id,
        Movement.reversed_movement_id.is_not(None),
    )


async def _compute_installment_open_balance(
    session: AsyncSession, *, tenant_id: uuid.UUID, installment_id: uuid.UUID
) -> Decimal:
    """Calcula el saldo abierto de una cuota sumando sus movimientos activos.

    Un movimiento cuenta hacia el saldo solo si (a) no es un ``REVERSAL``
    (``reversed_movement_id`` es NULL) y (b) no ha sido revertido por un
    ``REVERSAL`` posterior. Ambas exclusiones son necesarias: la fila REVERSAL
    no debe sumar, y el movimiento original revertido tampoco, porque el
    REVERSAL deshace su efecto. Usado internamente por
    ``compute_installment_balance`` y ``installment_agings_for_receivable``.
    """
    applied = await session.scalar(
        select(func.coalesce(func.sum(Movement.amount), Decimal("0.00"))).where(
            Movement.tenant_id == tenant_id,
            Movement.installment_id == installment_id,
            Movement.reversed_movement_id.is_(None),
            Movement.id.not_in(_reversed_movement_ids(tenant_id)),
        )
    ) or Decimal("0.00")

    installment = await session.get(ReceivableInstallment, installment_id)
    if installment is None:
        raise HTTPException(status_code=404, detail="Installment not found")

    return installment.amount - applied


async def compute_installment_balance(
    session: AsyncSession, *, tenant_id: uuid.UUID, installment: ReceivableInstallment
) -> Decimal:
    """Calcula el saldo de una cuota sumando sus movimientos activos.

    Cuenta solo movimientos activos: ni las filas ``REVERSAL`` ni los
    movimientos que ya fueron revertidos por un ``REVERSAL``. Usado por
    validaciones antes de insertar movimientos nuevos.
    """
    applied = await session.scalar(
        select(func.coalesce(func.sum(Movement.amount), Decimal("0.00"))).where(
            Movement.tenant_id == tenant_id,
            Movement.installment_id == installment.id,
            Movement.reversed_movement_id.is_(None),
            Movement.id.not_in(_reversed_movement_ids(tenant_id)),
        )
    ) or Decimal("0.00")
    return installment.amount - applied


async def compute_receivable_balance(
    session: AsyncSession, *, tenant_id: uuid.UUID, receivable: Receivable
) -> Decimal:
    """Calcula el saldo completo de un receivable sumando todas sus cuotas.

    ``sum(compute_installment_balance)`` para todos los ``ReceivableInstallment``
    del ``Receivable``. Usado por el endpoint ``GET /receivables/{id}`` para
    calcular ``open_amount`` on-demand.
    """
    stmt = select(ReceivableInstallment).where(
        ReceivableInstallment.tenant_id == tenant_id,
        ReceivableInstallment.receivable_id == receivable.id,
    )
    installments = await session.scalars(stmt)
    total = Decimal("0.00")
    for installment in installments:
        total += await compute_installment_balance(
            session, tenant_id=tenant_id, installment=installment
        )
    return total


async def installment_agings_for_receivable(
    session: AsyncSession, *, tenant_id: uuid.UUID, receivable_id: uuid.UUID, as_of: date
) -> list[InstallmentAging]:
    """Calcula el aging de cada cuota de un receivable para una fecha de corte.

    Solo incluye cuotas con saldo abierto > 0. Una cuota totalmente pagada no
    aparece. El bucket del receivable completo es el peor (más vencido) entre
    sus cuotas (usado por ``to_receivable_summary`` para llenar ``AccountItem.aging``).
    """
    stmt = select(ReceivableInstallment).where(
        ReceivableInstallment.tenant_id == tenant_id,
        ReceivableInstallment.receivable_id == receivable_id,
    )
    installments = await session.scalars(stmt)

    agings: list[InstallmentAging] = []
    for installment in installments:
        open_balance = await _compute_installment_open_balance(
            session, tenant_id=tenant_id, installment_id=installment.id
        )
        if open_balance <= 0:
            continue

        bucket, days_overdue = classify_aging_bucket(due_date=installment.due_date, as_of=as_of)
        agings.append(
            InstallmentAging(
                installment_id=installment.id,
                due_date=installment.due_date,
                bucket=bucket,
                days_overdue=days_overdue,
                open_amount=open_balance,
            )
        )
    return agings


async def compute_aging_summary(
    session: AsyncSession, context: AuthContext, *, as_of: date | None = None
) -> AgingSummaryRead:
    """Resumen de aging por tenant (``GET /receivables/aging``, E5-05).

    Calcula el aging de todas las cuotas abiertas del tenant, agrupa por bucket
    (``buckets``) y también por cliente dentro de cada bucket (``by_party``).
    ``as_of`` por defecto es hoy en ``America/Guayaquil``.
    """
    if as_of is None:
        as_of = today_in_fiscal_timezone()

    tenant_id = context.tenant_id

    # Obtener todas las cuotas abiertas del tenant
    stmt_installments = (
        select(ReceivableInstallment, Receivable.party_id)
        .join(Receivable, Receivable.id == ReceivableInstallment.receivable_id)
        .where(
            Receivable.tenant_id == tenant_id,
            Receivable.status.in_(["OPEN", "PARTIALLY_PAID"]),
        )
    )
    result = await session.execute(stmt_installments)

    # Diccionarios para acumular por bucket y por party
    bucket_totals: dict[AgingBucket, Decimal] = {
        "CURRENT": Decimal("0.00"),
        "1-15": Decimal("0.00"),
        "16-30": Decimal("0.00"),
        "31-60": Decimal("0.00"),
        "61-90": Decimal("0.00"),
        "90+": Decimal("0.00"),
    }
    bucket_counts: dict[AgingBucket, int] = {
        "CURRENT": 0,
        "1-15": 0,
        "16-30": 0,
        "31-60": 0,
        "61-90": 0,
        "90+": 0,
    }

    # (party_id, bucket) -> (total, count)
    party_keys: dict[tuple[uuid.UUID, AgingBucket], tuple[Decimal, int]] = {}

    for installment, party_id in result:
        open_balance = await _compute_installment_open_balance(
            session, tenant_id=tenant_id, installment_id=installment.id
        )
        if open_balance <= 0:
            continue

        bucket, days_overdue = classify_aging_bucket(due_date=installment.due_date, as_of=as_of)

        bucket_totals[bucket] += open_balance
        bucket_counts[bucket] += 1

        key = (party_id, bucket)
        if key not in party_keys:
            party_keys[key] = (Decimal("0.00"), 0)
        total, count = party_keys[key]
        party_keys[key] = (total + open_balance, count + 1)

    buckets_read = [
        AgingBucketTotalRead(
            bucket=bucket,
            total=bucket_totals[bucket],
            installment_count=bucket_counts[bucket],
        )
        for bucket in bucket_totals
    ]

    by_party_read = [
        PartyAgingBucketTotalRead(
            party_id=party_id, bucket=bucket, total=total, installment_count=count
        )
        for (party_id, bucket), (total, count) in party_keys.items()
    ]

    return AgingSummaryRead(as_of=as_of, buckets=buckets_read, by_party=by_party_read)


# Cómo se agrupan los tipos de movimiento en el desglose de cobro.
_CASH_MOVEMENTS = ("PAYMENT",)
_RETENTION_MOVEMENTS = ("RETENTION",)
_CREDIT_MOVEMENTS = ("CREDIT_NOTE", "DISCOUNT")


async def compute_collections_breakdown(
    session: AsyncSession,
    context: AuthContext,
    *,
    from_date: date | None = None,
    to_date: date | None = None,
) -> CollectionsBreakdownRead:
    """Desglosa el cobro en dinero recibido vs retenido (``GET /receivables/collections``).

    Una retención NO es caja: es valor que el cliente retuvo y que se recupera
    ante el SRI. Separarla del efectivo evita leer como liquidez algo que aún
    no lo es. ``CREDIT_NOTE``/``DISCOUNT`` van aparte porque bajan la deuda sin
    que entre dinero.

    Cuenta solo movimientos activos con la MISMA regla que
    ``compute_installment_balance`` (ni ``REVERSAL`` ni movimientos ya
    revertidos), para que este desglose y el saldo de la cartera nunca se
    contradigan.

    El filtro de fechas usa ``Movement.effective_date`` (fecha real del cobro).
    Los movimientos históricos sin ``effective_date`` caen fuera de cualquier
    rango acotado; sin rango se incluyen todos.
    """
    tenant_id = context.tenant_id

    stmt = (
        select(
            Movement.movement_type,
            func.coalesce(func.sum(Movement.amount), Decimal("0.00")),
            func.count(Movement.id),
        )
        .where(
            Movement.tenant_id == tenant_id,
            Movement.reversed_movement_id.is_(None),
            Movement.id.not_in(_reversed_movement_ids(tenant_id)),
        )
        .group_by(Movement.movement_type)
    )
    if from_date is not None:
        stmt = stmt.where(Movement.effective_date >= from_date)
    if to_date is not None:
        stmt = stmt.where(Movement.effective_date <= to_date)

    totals: dict[str, tuple[Decimal, int]] = {
        movement_type: (Decimal(str(amount)), int(count))
        for movement_type, amount, count in await session.execute(stmt)
    }

    def group(types: tuple[str, ...]) -> tuple[Decimal, int]:
        amount = Decimal("0.00")
        count = 0
        for movement_type in types:
            group_amount, group_count = totals.get(movement_type, (Decimal("0.00"), 0))
            amount += group_amount
            count += group_count
        return amount.quantize(Decimal("0.01")), count

    cash_amount, cash_count = group(_CASH_MOVEMENTS)
    retention_amount, retention_count = group(_RETENTION_MOVEMENTS)
    credit_amount, credit_count = group(_CREDIT_MOVEMENTS)

    settled_amount = cash_amount + retention_amount
    retention_share = (
        (retention_amount / settled_amount * 100).quantize(Decimal("0.01"))
        if settled_amount > 0
        else Decimal("0.00")
    )

    return CollectionsBreakdownRead(
        from_date=from_date,
        to_date=to_date,
        cash_amount=cash_amount,
        cash_count=cash_count,
        retention_amount=retention_amount,
        retention_count=retention_count,
        credit_amount=credit_amount,
        credit_count=credit_count,
        settled_amount=settled_amount,
        retention_share=retention_share,
    )


# --- Consultas: GET /receivables, GET /receivables/{id} ----------------------


async def get_receivable(
    session: AsyncSession, *, tenant_id: uuid.UUID, receivable_id: uuid.UUID
) -> Receivable:
    """Obtiene un receivable por ID, verificando tenant."""
    entity = await session.get(Receivable, receivable_id)
    if entity is None or entity.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Receivable not found")
    return entity


async def list_receivables(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    party_id: uuid.UUID | None = None,
    status: str | None = None,
    as_of: date | None = None,
) -> list[AccountItemRead]:
    """Lista receivables con filtros opcionales y aging calculado."""
    stmt = select(Receivable).where(Receivable.tenant_id == tenant_id)

    if party_id is not None:
        stmt = stmt.where(Receivable.party_id == party_id)
    if status is not None:
        stmt = stmt.where(Receivable.status == status)

    stmt = stmt.order_by(Receivable.created_at.desc())
    entities = await session.scalars(stmt)

    items: list[AccountItemRead] = []
    effective_as_of = as_of if as_of is not None else today_in_fiscal_timezone()
    for entity in entities:
        summary = await to_receivable_summary(
            session,
            tenant_id=tenant_id,
            receivable=entity,
            as_of=effective_as_of,
        )
        aging = (
            AgingRead(bucket=summary.aging_bucket, days_overdue=summary.aging_days_overdue)
            if summary.aging_bucket is not None and summary.aging_days_overdue is not None
            else None
        )

        items.append(
            AccountItemRead(
                id=entity.id,
                party_id=entity.party_id,
                invoice_sequential=summary.invoice_sequential,
                status=summary.status,
                original_amount=entity.original_amount,
                open_amount=summary.open_amount,
                currency=entity.currency,
                due_date=summary.due_date,
                aging=aging,
            )
        )
    return items


async def list_receivable_installments(
    session: AsyncSession, *, tenant_id: uuid.UUID, receivable_id: uuid.UUID
) -> list[ReceivableInstallment]:
    """Lista todas las cuotas de un receivable (uso interno del endpoint de movimientos)."""
    stmt = select(ReceivableInstallment).where(
        ReceivableInstallment.tenant_id == tenant_id,
        ReceivableInstallment.receivable_id == receivable_id,
    )
    return list(await session.scalars(stmt))


async def correct_receivable_due_date(
    session: AsyncSession,
    context: AuthContext,
    *,
    receivable_id: uuid.UUID,
    due_date: date,
    reason: str,
    correlation_id: str,
    idempotency_key: str,
) -> ReceivableSummary:
    """Corrige el vencimiento comercial de una cuenta de una sola cuota.

    No modifica el XML, autorización ni importes SRI. Ajusta en conjunto la
    cuota de cartera y el plan comercial mostrado en la factura, y conserva el
    antes/después en auditoría.
    """
    locked = await lock_receivable(
        session, tenant_id=context.tenant_id, receivable_id=receivable_id
    )
    installments = list(
        await session.scalars(
            select(ReceivableInstallment)
            .where(
                ReceivableInstallment.tenant_id == context.tenant_id,
                ReceivableInstallment.receivable_id == receivable_id,
            )
            .order_by(ReceivableInstallment.sequence)
        )
    )
    if len(installments) != 1:
        raise HTTPException(
            status_code=409,
            detail="This account has multiple installments and needs a payment plan adjustment",
        )
    document_installment = await session.scalar(
        select(SalesDocumentInstallment).where(
            SalesDocumentInstallment.tenant_id == context.tenant_id,
            SalesDocumentInstallment.sales_document_id == locked.sales_document_id,
            SalesDocumentInstallment.sequence == installments[0].sequence,
        )
    )
    previous_due_date = installments[0].due_date
    installments[0].due_date = due_date
    if document_installment is not None:
        document_installment.due_date = due_date
    await append_audit(
        session,
        context=context,
        action="receivable.due_date_corrected",
        entity_type="receivable",
        entity_id=str(receivable_id),
        correlation_id=correlation_id,
        idempotency_key=idempotency_key,
        details={
            "previous_due_date": previous_due_date.isoformat(),
            "due_date": due_date.isoformat(),
            "reason": reason.strip(),
        },
    )
    await session.flush()
    return await to_receivable_summary(
        session,
        tenant_id=context.tenant_id,
        receivable=locked,
        as_of=today_in_fiscal_timezone(),
    )


async def list_movements(
    session: AsyncSession, *, tenant_id: uuid.UUID, receivable_id: uuid.UUID
) -> list[Movement]:
    """Historial de movimientos de un receivable, mas recientes primero.

    Usado por ``GET /receivables/{id}/movements`` para el drawer de historial
    de la UI (``docs/sprints/sprint-03.md`` decision 10): cobros, retenciones,
    descuentos, notas de credito y reversos, todos como filas ``Movement``.
    Verifica tenant implicitamente via el filtro; no valida existencia del
    receivable (una lista vacia es una respuesta valida).
    """
    stmt = (
        select(Movement)
        .where(
            Movement.tenant_id == tenant_id,
            Movement.receivable_id == receivable_id,
        )
        .order_by(Movement.created_at.desc())
    )
    return list(await session.scalars(stmt))


async def to_receivable_summary(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    receivable: Receivable,
    as_of: date | None = None,
) -> ReceivableSummary:
    """Convierte un ``Receivable`` a ``ReceivableSummary`` con aging opcional."""
    open_amount = await compute_receivable_balance(
        session, tenant_id=tenant_id, receivable=receivable
    )
    status = _map_status(receivable.status, open_amount, receivable.original_amount)

    # El aging se calcula siempre (fecha de corte local por defecto) porque el
    # estado OVERDUE del AccountItem depende de si hay cuotas vencidas, no solo
    # del saldo. as_of explicito solo se usa para reproducibilidad en pruebas.
    effective_as_of = as_of if as_of is not None else today_in_fiscal_timezone()
    aging_bucket: str | None = None
    aging_days_overdue: int | None = None
    aging = await _compute_worst_aging(
        session, tenant_id=tenant_id, receivable_id=receivable.id, as_of=effective_as_of
    )
    if aging is not None:
        aging_bucket = aging.bucket
        aging_days_overdue = aging.days_overdue

    # OVERDUE tiene prioridad sobre OPEN/PARTIAL cuando hay mora real.
    if status in {"OPEN", "PARTIAL"} and aging_days_overdue and aging_days_overdue > 0:
        status = "OVERDUE"

    # dueDate del AccountItem: la cuota mas temprana del receivable (el
    # vencimiento mas proximo/antiguo), para que la UI pueda ordenar y mostrar
    # el compromiso de pago sin abrir el detalle.
    earliest_due_date = await session.scalar(
        select(func.min(ReceivableInstallment.due_date)).where(
            ReceivableInstallment.tenant_id == tenant_id,
            ReceivableInstallment.receivable_id == receivable.id,
        )
    )
    invoice_sequential = await session.scalar(
        select(SalesDocument.sequential).where(
            SalesDocument.tenant_id == tenant_id,
            SalesDocument.id == receivable.sales_document_id,
        )
    )

    return ReceivableSummary(
        id=receivable.id,
        party_id=receivable.party_id,
        invoice_sequential=invoice_sequential,
        status=status,
        original_amount=receivable.original_amount,
        open_amount=open_amount,
        currency=receivable.currency,
        due_date=earliest_due_date,
        aging_bucket=aging_bucket,
        aging_days_overdue=aging_days_overdue,
    )


def _map_status(
    persisted_status: str, open_amount: Decimal, original_amount: Decimal
) -> Literal["OPEN", "PARTIAL", "OVERDUE", "SETTLED", "VOIDED"]:
    """Mapea el status persistido + saldo al enum de ``AccountItem``."""
    if persisted_status == "VOID":
        return "VOIDED"
    if open_amount == Decimal("0.00"):
        return "SETTLED"
    if open_amount == original_amount:
        return "OPEN"
    return "PARTIAL"


async def _compute_worst_aging(
    session: AsyncSession, *, tenant_id: uuid.UUID, receivable_id: uuid.UUID, as_of: date
) -> AgingRead | None:
    """Calcula el peor aging entre las cuotas abiertas de un receivable."""
    agings = await installment_agings_for_receivable(
        session, tenant_id=tenant_id, receivable_id=receivable_id, as_of=as_of
    )
    if not agings:
        return None

    # El peor es el que tiene más días overdue (más vencido)
    worst = max(agings, key=lambda a: a.days_overdue)
    return AgingRead(bucket=worst.bucket, days_overdue=worst.days_overdue)


# --- Lock y concurrencia: SELECT FOR UPDATE ----------------------------------


async def lock_receivable(
    session: AsyncSession, *, tenant_id: uuid.UUID, receivable_id: uuid.UUID
) -> Receivable:
    """Lock exclusivo sobre un ``Receivable`` con ``SELECT ... FOR UPDATE``.

    Serializa todas las aplicaciones (cobros, NC, reversos) sobre el mismo
    receivable para garantizar que nunca se sobreaplique (docs/sprints/sprint-03.md
    decisión 2). El lock se libera al commitear la transacción.

    Raises:
        HTTPException 404 si el receivable no existe o pertenece a otro tenant.
    """
    stmt = (
        select(Receivable)
        .where(
            Receivable.tenant_id == tenant_id,
            Receivable.id == receivable_id,
        )
        .with_for_update()
    )
    entity = await session.scalar(stmt)
    if entity is None:
        raise HTTPException(status_code=404, detail="Receivable not found")
    return entity


# --- Escritura: cobros, NC, reverso ------------------------------------------


async def record_payment(
    session: AsyncSession,
    context: AuthContext,
    receivable_id: uuid.UUID,
    payment: PaymentInput,
    *,
    correlation_id: str,
    idempotency_key: str,
) -> ReceivableSummary:
    """Registra un cobro parcial o total con retenciones/descuentos (E5-03/E5-04).

    Aplica el cobro oldest-first (cuota más antigua primero) y valida que
    la suma total (cash + retenciones + descuentos) nunca exceda el saldo abierto.
    Crea múltiples ``Movement``: uno ``PAYMENT`` por cuota tocada, uno
    ``RETENTION`` y uno ``DISCOUNT`` por cada elemento de las listas anidadas.

    Args:
        session: Sesión DB con transacción activa
        context: Contexto de autenticación del actor
        receivable_id: ID del receivable a cobrar
        payment: Input con cash_amount, retenciones y descuentos
        correlation_id: ID de correlación para trazabilidad
        idempotency_key: Clave de idempotencia (repetir devuelve mismo resultado)

    Returns:
        ``AccountItem`` actualizado con el nuevo saldo

    Raises:
        HTTPException 422 si el total del cobro excede el saldo o es 0
        HTTPException 404 si el receivable no existe
    """
    tenant_id = context.tenant_id

    # Validar que el total sea > 0
    retentions_total = sum((r.amount for r in payment.retentions), Decimal("0.00"))
    discounts_total = sum((d.amount for d in payment.discounts), Decimal("0.00"))
    total_application = payment.cash_amount + retentions_total + discounts_total
    if total_application <= 0:
        raise HTTPException(status_code=422, detail="Payment total must be greater than zero")

    # Lock y validar saldo
    locked = await lock_receivable(session, tenant_id=tenant_id, receivable_id=receivable_id)
    open_balance = await compute_receivable_balance(session, tenant_id=tenant_id, receivable=locked)

    if total_application > open_balance:
        raise HTTPException(
            status_code=422,
            detail=f"Payment total {total_application} exceeds open balance {open_balance}",
        )

    # Obtener cuotas ordenadas por due_date (oldest-first)
    stmt = (
        select(ReceivableInstallment)
        .where(
            ReceivableInstallment.tenant_id == tenant_id,
            ReceivableInstallment.receivable_id == receivable_id,
        )
        .order_by(ReceivableInstallment.due_date.asc())
    )
    installments = list(await session.scalars(stmt))

    if not installments:
        raise HTTPException(status_code=422, detail="Receivable has no installments")

    # Cuota mas antigua: usada como ancla de retenciones/descuentos. Se
    # captura ANTES de consumir la lista en el loop de abajo (un ScalarResult
    # ya consumido no puede reconsultarse con `.first()`).
    first_installment = installments[0]

    # Aplicar el cash oldest-first. Retenciones y descuentos NO forman parte
    # de este monto: se aplican por separado mas abajo contra la primera
    # cuota. Sumarlos aqui (via total_application) duplicaria su efecto sobre
    # el saldo, porque cada uno ya se resta de nuevo como su propio Movement.
    remaining_to_apply = payment.cash_amount
    for installment in installments:
        if remaining_to_apply <= 0:
            break

        installment_balance = await compute_installment_balance(
            session, tenant_id=tenant_id, installment=installment
        )
        if installment_balance <= 0:
            continue

        apply_amount = min(remaining_to_apply, installment_balance)
        movement = Movement(
            tenant_id=tenant_id,
            receivable_id=receivable_id,
            installment_id=installment.id,
            movement_type="PAYMENT",
            amount=apply_amount,
            effective_date=payment.payment_date,
            support_reference=payment.reference,
            actor_id=context.actor_id,
        )
        session.add(movement)
        await session.flush()  # Asignar ID
        remaining_to_apply -= apply_amount

    # Agregar retenciones como movimientos separados (contra la primera cuota)
    if payment.retentions:
        for retention in payment.retentions:
            session.add(
                Movement(
                    tenant_id=tenant_id,
                    receivable_id=receivable_id,
                    installment_id=first_installment.id,
                    movement_type="RETENTION",
                    amount=retention.amount,
                    effective_date=payment.payment_date,
                    support_reference=(
                        f"{retention.document_reference} | {retention.kind}: {retention.reason}"
                    ),
                    actor_id=context.actor_id,
                )
            )

    # Agregar descuentos como movimientos separados
    if payment.discounts:
        for discount in payment.discounts:
            session.add(
                Movement(
                    tenant_id=tenant_id,
                    receivable_id=receivable_id,
                    installment_id=first_installment.id,
                    movement_type="DISCOUNT",
                    amount=discount.amount,
                    effective_date=payment.payment_date,
                    support_reference=discount.reason,
                    actor_id=context.actor_id,
                )
            )

    # Flush explicito: la sesion usa autoflush=False, y el resumen de abajo
    # consulta los movimientos por SQL. Sin este flush, los Movement de
    # retencion/descuento recien agregados no serian visibles y el saldo
    # quedaria sobrestimado.
    await session.flush()

    # Actualizar status del receivable
    new_balance = open_balance - total_application
    if new_balance == Decimal("0.00"):
        locked.status = "PAID"
    elif locked.status == "OPEN":
        locked.status = "PARTIALLY_PAID"

    return await to_receivable_summary(
        session, tenant_id=tenant_id, receivable=locked, as_of=today_in_fiscal_timezone()
    )


async def apply_credit_note(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    receivable: Receivable,
    credit_note_total: Decimal,
    credit_note_access_key: str,
    party_id: uuid.UUID,
    origin_credit_note_id: uuid.UUID,
    actor_id: str,
) -> Movement | None:
    """Aplica una nota de crédito contra un receivable (E5-08).

    Distribuye el total de la NC sobre las cuotas abiertas oldest-first. Si
    excede el saldo, crea un ``CustomerCredit`` con el excedente. Idempotente
    por ``access_key``: si ya existe un ``Movement`` ``CREDIT_NOTE`` con esa
    clave, no aplica nada.

    Args:
        session: Sesión DB con transacción activa
        tenant_id: Tenant del contexto
        receivable: Receivable bloqueado con ``lock_receivable``
        credit_note_total: Total de la NC a aplicar
        credit_note_access_key: access_key de la NC (idempotencia)
        party_id: Cliente del receivable (para CustomerCredit si excede)
        origin_credit_note_id: ID del SalesDocument de la NC
        actor_id: Actor que ejecuta (usualmente "system:worker")

    Returns:
        El primer ``Movement`` creado o ``None`` si ya existía (idempotencia)

    Raises:
        HTTPException 422 si la NC ya está aplicada (idempotencia)
    """
    # Verificar idempotencia: ya existe un CREDIT_NOTE con este access_key?
    stmt = select(Movement).where(
        Movement.tenant_id == tenant_id,
        Movement.receivable_id == receivable.id,
        Movement.movement_type == "CREDIT_NOTE",
        Movement.support_reference == credit_note_access_key,
    )
    existing = await session.scalar(stmt)
    if existing is not None:
        return None  # Idempotente: ya aplicada

    open_balance = await compute_receivable_balance(
        session, tenant_id=tenant_id, receivable=receivable
    )

    # Si excede, crear CustomerCredit primero
    surplus = max(Decimal("0.00"), credit_note_total - open_balance)
    if surplus > 0:
        credit = CustomerCredit(
            tenant_id=tenant_id,
            party_id=party_id,
            origin_credit_note_id=origin_credit_note_id,
            amount=surplus,
            remaining_amount=surplus,
        )
        session.add(credit)

    # Aplicar hasta el saldo abierto sobre cuotas oldest-first
    to_apply = min(credit_note_total, open_balance)
    stmt_installments = (
        select(ReceivableInstallment)
        .where(
            ReceivableInstallment.tenant_id == tenant_id,
            ReceivableInstallment.receivable_id == receivable.id,
        )
        .order_by(ReceivableInstallment.due_date.asc())
    )
    installments = await session.scalars(stmt_installments)

    remaining = to_apply
    first_movement: Movement | None = None
    for installment in installments:
        if remaining <= 0:
            break

        installment_balance = await compute_installment_balance(
            session, tenant_id=tenant_id, installment=installment
        )
        if installment_balance <= 0:
            continue

        apply_amount = min(remaining, installment_balance)
        movement = Movement(
            tenant_id=tenant_id,
            receivable_id=receivable.id,
            installment_id=installment.id,
            movement_type="CREDIT_NOTE",
            amount=apply_amount,
            support_reference=credit_note_access_key,
            actor_id=actor_id,
        )
        session.add(movement)
        await session.flush()
        if first_movement is None:
            first_movement = movement
        remaining -= apply_amount

    # Actualizar status del receivable
    new_balance = open_balance - to_apply
    if new_balance == Decimal("0.00"):
        receivable.status = "PAID"
    elif receivable.status == "OPEN":
        receivable.status = "PARTIALLY_PAID"

    return first_movement


async def reverse_movement(
    session: AsyncSession,
    context: AuthContext,
    *,
    receivable_id: uuid.UUID,
    movement_id: uuid.UUID,
    reason: str,
    correlation_id: str,
    idempotency_key: str,
) -> ReceivableSummary:
    """Revierte un movimiento creando un ``REVERSAL`` que lo deshace (E5-09).

    El movimiento original nunca se edita ni borra (invariante de dominio).
    No se puede revertir un ``REVERSAL`` ni un movimiento ya revertido.
    Si se revierte un ``CREDIT_NOTE`` que generó ``CustomerCredit``, reduce
    el excedente proporcionalmente.

    Args:
        session: Sesión DB con transacción activa
        context: Contexto de autenticación
        receivable_id: ID del receivable
        movement_id: ID del movimiento a revertir
        reason: Motivo obligatorio del reverso (auditoría)
        correlation_id: ID de correlación
        idempotency_key: Clave de idempotencia

    Returns:
        ``AccountItem`` con el saldo tras el reverso

    Raises:
        HTTPException 404 si el movimiento no existe
        HTTPException 422 si es un REVERSAL o ya está revertido
    """
    tenant_id = context.tenant_id

    # Buscar el movimiento original
    stmt = select(Movement).where(
        Movement.tenant_id == tenant_id,
        Movement.id == movement_id,
        Movement.receivable_id == receivable_id,
    )
    original = await session.scalar(stmt)
    if original is None:
        raise HTTPException(status_code=404, detail="Movement not found")

    # No se puede revertir un REVERSAL (evita cadenas)
    if original.movement_type == "REVERSAL":
        raise HTTPException(status_code=422, detail="Cannot reverse a REVERSAL")

    # Verificar que no está ya revertido (UniqueConstraint en reversed_movement_id)
    stmt_reversal = select(Movement).where(
        Movement.tenant_id == tenant_id,
        Movement.reversed_movement_id == movement_id,
    )
    existing_reversal = await session.scalar(stmt_reversal)
    if existing_reversal is not None:
        raise HTTPException(status_code=422, detail="Movement already reversed")

    # Lock del receivable
    locked = await lock_receivable(session, tenant_id=tenant_id, receivable_id=receivable_id)

    # Crear el REVERSAL
    reversal = Movement(
        tenant_id=tenant_id,
        receivable_id=receivable_id,
        installment_id=original.installment_id,
        movement_type="REVERSAL",
        amount=original.amount,
        support_reference=reason,
        reversed_movement_id=movement_id,
        actor_id=context.actor_id,
    )
    session.add(reversal)
    # ``autoflush`` está desactivado: el reverso debe llegar a la base antes de
    # recalcular el saldo o se conservaría el estado anterior del cobro.
    await session.flush()

    # Si el original era CREDIT_NOTE, reducir CustomerCredit si hubo excedente
    if original.movement_type == "CREDIT_NOTE" and original.support_reference:
        stmt_cn = select(SalesDocument).where(
            SalesDocument.tenant_id == tenant_id,
            SalesDocument.access_key == original.support_reference,
            SalesDocument.document_type == "CREDIT_NOTE",
        )
        credit_note = await session.scalar(stmt_cn)
        if credit_note:
            stmt_credit = select(CustomerCredit).where(
                CustomerCredit.tenant_id == tenant_id,
                CustomerCredit.origin_credit_note_id == credit_note.id,
            )
            customer_credit = await session.scalar(stmt_credit)
            if customer_credit and customer_credit.remaining_amount > 0:
                # Reducir proporcionalmente al monto revertido
                reduction = min(original.amount, customer_credit.remaining_amount)
                customer_credit.remaining_amount -= reduction
                customer_credit.amount -= reduction

    # Actualizar status del receivable
    new_balance = await compute_receivable_balance(session, tenant_id=tenant_id, receivable=locked)
    if new_balance == locked.original_amount:
        locked.status = "OPEN"
    elif new_balance > Decimal("0.00"):
        locked.status = "PARTIALLY_PAID"
    else:
        locked.status = "PAID"

    await session.flush()

    # Auditoria de dominio del reverso, con el vinculo al movimiento original.
    # Se escribe aqui (no solo en execute_idempotent) para que la operacion sea
    # auditable aunque se invoque el servicio directamente, y para dejar el
    # ``original_movement_id`` en los detalles. El flush intermedio garantiza
    # que la auditoria de operacion que agrega execute_idempotent tome el
    # siguiente ``sequence`` del hash-chain (mismo motivo que en record_payment).
    from app.services.unit_of_work import append_audit

    await append_audit(
        session,
        context=context,
        action="movement.reversed",
        entity_type="movement",
        entity_id=str(movement_id),
        correlation_id=correlation_id,
        idempotency_key=idempotency_key,
        details={"original_movement_id": str(movement_id), "reason": reason},
    )
    await session.flush()

    return await to_receivable_summary(
        session, tenant_id=tenant_id, receivable=locked, as_of=today_in_fiscal_timezone()
    )


# --- Recordatorios (E5-06/E5-07, P1) ----------------------------------------


async def send_reminder(
    session: AsyncSession,
    context: AuthContext,
    *,
    receivable_id: uuid.UUID,
    reminder: ReminderInput,
    notifier: Notifier,
) -> CollectionReminder:
    """Envía un recordatorio de cobranza usando el ``Notifier`` inyectado (P1).

    Valida ``consent_opt_out`` del cliente antes de enviar. El ``Notifier``
    (por defecto ``StubNotifier``) es quien crea el ``CollectionReminder`` con
    el estado del envío (``STUBBED``, ``SENT``, ``FAILED``); este servicio solo
    orquesta y devuelve ese mismo registro (nunca crea uno duplicado).

    Args:
        session: Sesión DB con transacción activa
        context: Contexto de autenticación
        receivable_id: ID del receivable (para obtener party_id)
        reminder: Input opcional con channel/template/message
        notifier: Implementación de ``Notifier`` (inyectado)

    Returns:
        ``CollectionReminder`` creado por el ``Notifier``

    Raises:
        HTTPException 404 si el receivable o el party no existen
        HTTPException 422 si el cliente tiene ``consent_opt_out=true`` o el
            ``Notifier`` rechaza el envío (``status == "FAILED"``)
    """
    tenant_id = context.tenant_id

    # Obtener el receivable y party
    stmt = select(Receivable).where(
        Receivable.tenant_id == tenant_id,
        Receivable.id == receivable_id,
    )
    receivable = await session.scalar(stmt)
    if receivable is None:
        raise HTTPException(status_code=404, detail="Receivable not found")

    # Buscar party para validar consent_opt_out y obtener el destinatario
    from app.models.masters import Party

    party = await session.get(Party, receivable.party_id)
    if party is None:
        raise HTTPException(status_code=404, detail="Party not found")

    if party.consent_opt_out:
        raise HTTPException(status_code=422, detail="Client has opted out of reminders")

    channel = reminder.channel or "email"
    recipient = party.email if channel == "email" else party.phone
    if not recipient:
        raise HTTPException(
            status_code=422, detail=f"Party has no contact info for channel '{channel}'"
        )

    # Delegar el envío (y la creación del CollectionReminder) al Notifier.
    request = ReminderRequest(
        channel=channel,
        template_id=reminder.template_id or "payment_reminder",
        recipient=recipient,
        party_id=str(party.id),
    )
    result = await notifier.send(request)

    if result.reminder_id is None:
        raise HTTPException(
            status_code=422,
            detail=result.error_message or "Reminder could not be sent",
        )

    reminder_record = await session.get(CollectionReminder, uuid.UUID(result.reminder_id))
    if reminder_record is None:
        raise HTTPException(status_code=404, detail="CollectionReminder not found after send")

    return reminder_record


async def _render_receivable_email(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    receivable: Receivable,
    party_name: str,
    body_override: str | None,
) -> tuple[str, str, str]:
    """Arma el correo de cobro de un receivable con la plantilla del tenant.

    El envío manual usa exactamente la misma plantilla que el recordatorio
    programado (``services/collection_email.py``), para que el cliente reciba
    siempre el mismo formato y los mismos datos de pago sin importar quién
    disparó el correo.

    El vencimiento que se comunica es el de la cuota abierta más antigua: es la
    que está en mora y la que el cliente debe atender primero. Si no queda
    ninguna cuota abierta se usa la más reciente, para no inventar una fecha.
    """
    policy = await session.get(CollectionPolicy, tenant_id)
    if policy is None:
        policy = CollectionPolicy(tenant_id=tenant_id)
        session.add(policy)
        await session.flush()

    tenant = await session.get(Tenant, tenant_id)
    company_name = tenant.name if tenant is not None else "Nuestra empresa"

    installments = list(
        await session.scalars(
            select(ReceivableInstallment)
            .where(
                ReceivableInstallment.tenant_id == tenant_id,
                ReceivableInstallment.receivable_id == receivable.id,
            )
            .order_by(ReceivableInstallment.due_date)
        )
    )
    open_installments = [
        installment
        for installment in installments
        if await compute_installment_balance(
            session, tenant_id=tenant_id, installment=installment
        )
        > 0
    ]
    reference = (
        open_installments[0]
        if open_installments
        else (installments[-1] if installments else None)
    )
    due_date = reference.due_date if reference is not None else today_in_fiscal_timezone()

    open_amount = await compute_receivable_balance(
        session, tenant_id=tenant_id, receivable=receivable
    )

    return render_collection_email(
        policy=policy,
        company_name=company_name,
        party_name=party_name,
        open_amount=open_amount,
        due_date=due_date,
        as_of=today_in_fiscal_timezone(),
        body_override=body_override,
    )


async def send_real_reminder(
    session: AsyncSession,
    context: AuthContext,
    *,
    receivable_id: uuid.UUID,
    reminder: ReminderInput,
) -> CollectionReminder:
    from datetime import UTC, datetime

    from app.services import crm_integrations

    receivable = await session.scalar(
        select(Receivable).where(
            Receivable.tenant_id == context.tenant_id,
            Receivable.id == receivable_id,
        )
    )
    if receivable is None:
        raise HTTPException(status_code=404, detail="Receivable not found")
    from app.models.masters import Party

    party = await session.scalar(
        select(Party).where(
            Party.tenant_id == context.tenant_id,
            Party.id == receivable.party_id,
        )
    )
    if party is None:
        raise HTTPException(status_code=404, detail="Party not found")
    if party.consent_opt_out:
        raise HTTPException(status_code=422, detail="Client has opted out of reminders")
    channel = (reminder.channel or "EMAIL").upper()
    recipient = party.email if channel == "EMAIL" else party.phone
    if not recipient:
        raise HTTPException(status_code=422, detail=f"Party has no contact for {channel}")
    scheduled_at = reminder.scheduled_at or datetime.now(UTC)
    record = CollectionReminder(
        tenant_id=context.tenant_id,
        party_id=party.id,
        receivable_id=receivable.id,
        channel=channel,
        template_id=reminder.template_id or "payment_reminder",
        recipient=recipient,
        status="PENDING",
        scheduled_at=scheduled_at,
    )
    session.add(record)
    await session.flush()
    if scheduled_at > datetime.now(UTC):
        return record
    try:
        message = reminder.message or (
            "Le recordamos que mantiene un saldo pendiente. "
            "Por favor contáctenos si ya realizó el pago."
        )
        if channel == "EMAIL":
            subject, message, html_message = await _render_receivable_email(
                session,
                tenant_id=context.tenant_id,
                receivable=receivable,
                party_name=party.name,
                body_override=reminder.message,
            )
            await crm_integrations.send_google_email(
                session,
                context,
                recipient=recipient,
                subject=subject,
                message=message,
                html_message=html_message,
            )
        elif channel == "WHATSAPP":
            await crm_integrations.send_whatsapp_message(
                session,
                context,
                recipient=recipient,
                message=message,
                template_id=reminder.template_id,
                purpose="COLLECTIONS",
            )
        else:
            raise HTTPException(status_code=422, detail="Unsupported reminder channel")
        record.status = "SENT"
        record.sent_at = datetime.now(UTC)
        record.attempts = 1
    except HTTPException as exc:
        record.status = "FAILED"
        record.attempts = 1
        record.error_message = str(exc.detail)
    await session.flush()
    return record


# --- Exportaciones públicas ---------------------------------------------------

__all__ = [
    # Aging
    "classify_aging_bucket",
    "compute_aging_summary",
    "installment_agings_for_receivable",
    # Balance
    "compute_installment_balance",
    "compute_receivable_balance",
    # Consultas
    "get_receivable",
    "list_receivables",
    "list_receivable_installments",
    "list_movements",
    "correct_receivable_due_date",
    "preview_retention_xml",
    "to_receivable_summary",
    # Lock
    "lock_receivable",
    # Escritura
    "record_payment",
    "apply_credit_note",
    "reverse_movement",
    # Recordatorios
    "send_reminder",
    "send_real_reminder",
]
