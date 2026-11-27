"""Reportes de lectura del tenant activo con proyecciones y filtros fijos."""

from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import DateTime, case, cast, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthContext
from app.core.timezones import FISCAL_TIMEZONE
from app.models.billing import DocumentRelation, SalesDocument
from app.models.masters import EmissionPoint, Establishment, Party, Product
from app.models.payables import BankTransaction, BankTransactionAllocation, Payable, PayableMovement
from app.models.platform import Tenant
from app.models.receivables import Movement, Receivable
from app.schemas.erp_reports import ERPReportPage, ReportName
from app.schemas.tax_monthly_summary import TaxMonthlySummary
from app.services import erp_reports_operations, payables, receivables
from app.services.erp_report_query import ReportQuery

_CATALOG_DESCRIPTION = "Reportes habilitados, sus herramientas y el criterio temporal de cada uno."
_INBOX_DESCRIPTION = (
    "Cantidad de elementos sugeridos por grupo en la bandeja actual (hasta 200 por grupo). "
)


def _sales_report(tenant_id: UUID, *, credit_notes: bool) -> ReportQuery:
    d = SalesDocument
    statement = (
        select(
            d.id.label("documentId"),
            d.party_id.label("customerId"),
            (Establishment.code + "-" + EmissionPoint.code + "-" + d.sequential).label(
                "documentNumber"
            ),
            d.document_type.label("documentType"),
            d.issue_date.label("issueDate"),
            d.status.label("status"),
            d.subtotal.label("subtotal"),
            d.tax_total.label("tax"),
            d.total.label("total"),
            d.currency.label("currency"),
        )
        .select_from(d)
        .join(
            Establishment,
            (Establishment.id == d.establishment_id) & (Establishment.tenant_id == tenant_id),
        )
        .join(
            EmissionPoint,
            (EmissionPoint.id == d.emission_point_id) & (EmissionPoint.tenant_id == tenant_id),
        )
        .where(d.tenant_id == tenant_id)
    )
    if credit_notes:
        statement = (
            statement.outerjoin(
                DocumentRelation,
                (DocumentRelation.credit_note_id == d.id)
                & (DocumentRelation.tenant_id == tenant_id),
            )
            .where(d.document_type == "CREDIT_NOTE")
            .add_columns(DocumentRelation.related_invoice_id.label("relatedInvoiceId"))
        )
    return ReportQuery(
        statement.order_by(d.issue_date.desc(), d.id),
        "Documentos de venta por emisión y estado. Las notas de crédito se presentan con el "
        "importe del documento y deben restarse para calcular ventas netas.",
        "Emisión del documento",
        d.issue_date,
    )


def _payables_report(tenant_id: UUID) -> ReportQuery:
    p, m = Payable, PayableMovement
    applied = (
        select(m.payable_id.label("id"), func.sum(m.amount).label("amount"))
        .where(
            m.tenant_id == tenant_id,
            m.movement_type != "REVERSAL",
            m.id.not_in(payables._reversed_movement_ids(tenant_id)),
        )
        .group_by(m.payable_id)
        .subquery()
    )
    remaining = p.total - func.coalesce(applied.c.amount, Decimal("0.00"))
    open_amount = case(((p.status == "VOID") | (remaining < 0), Decimal("0.00")), else_=remaining)
    return ReportQuery(
        select(
            p.id.label("purchaseId"),
            p.supplier_id.label("supplierId"),
            p.supplier_name.label("supplier"),
            p.fiscal_document_id.label("fiscalDocumentId"),
            p.document_number.label("documentNumber"),
            p.document_type.label("documentType"),
            p.issue_date.label("issueDate"),
            case((p.due_date_known, p.due_date)).label("dueDate"),
            p.status.label("status"),
            p.tax_classification.label("taxClassification"),
            p.total.label("total"),
            open_amount.label("openAmount"),
            p.currency.label("currency"),
        )
        .outerjoin(applied, applied.c.id == p.id)
        .where(p.tenant_id == tenant_id)
        .order_by(p.issue_date.desc(), p.id),
        "Compras y cuentas por pagar con saldo vigente según los movimientos activos.",
        "Emisión de la compra",
        p.issue_date,
    )


def _receivables_report(tenant_id: UUID) -> ReportQuery:
    r, d = Receivable, SalesDocument
    balances = receivables.open_balances_by_receivable(tenant_id)
    return ReportQuery(
        select(
            r.id.label("receivableId"),
            r.party_id.label("customerId"),
            r.sales_document_id.label("documentId"),
            d.issue_date.label("issueDate"),
            balances.c.earliest_open_due.label("dueDate"),
            r.original_amount.label("originalAmount"),
            balances.c.balance.label("openAmount"),
            r.currency.label("currency"),
        )
        .join(d, (d.id == r.sales_document_id) & (d.tenant_id == tenant_id))
        .join(balances, balances.c.receivable_id == r.id)
        .where(
            r.tenant_id == tenant_id,
            r.status.in_(("OPEN", "PARTIALLY_PAID")),
            d.status != "VOIDED",
            balances.c.balance > 0,
        )
        .order_by(d.issue_date.desc(), r.id),
        "Cartera vigente con saldo positivo y primer vencimiento abierto.",
        "Emisión de la factura",
        d.issue_date,
    )


def _core_query(report: ReportName, tenant_id: UUID, dialect: str) -> ReportQuery:
    if report in (ReportName.SALES, ReportName.CREDIT_NOTES):
        return _sales_report(tenant_id, credit_notes=report == ReportName.CREDIT_NOTES)
    if report == ReportName.PURCHASES:
        return _payables_report(tenant_id)
    if report == ReportName.RECEIVABLES:
        return _receivables_report(tenant_id)
    if report == ReportName.COLLECTIONS:
        m, r = Movement, Receivable
        return ReportQuery(
            select(
                m.id.label("movementId"),
                m.receivable_id.label("receivableId"),
                r.party_id.label("customerId"),
                m.effective_date.label("effectiveDate"),
                m.movement_type.label("type"),
                m.amount.label("amount"),
                r.currency.label("currency"),
            )
            .join(r, (r.id == m.receivable_id) & (r.tenant_id == tenant_id))
            .where(
                m.tenant_id == tenant_id,
                m.movement_type.in_(("PAYMENT", "RETENTION")),
                m.reversed_movement_id.is_(None),
                m.id.not_in(receivables._reversed_movement_ids(tenant_id)),
            )
            .order_by(m.effective_date.desc().nulls_last(), m.id),
            "Cobros y retenciones aplicados. Solo los movimientos PAYMENT representan efectivo.",
            "Fecha efectiva del movimiento",
            m.effective_date,
        )
    if report == ReportName.PAYMENTS:
        pm, p = PayableMovement, Payable
        return ReportQuery(
            select(
                pm.id.label("movementId"),
                pm.payable_id.label("purchaseId"),
                p.supplier_id.label("supplierId"),
                pm.effective_date.label("effectiveDate"),
                pm.method.label("method"),
                pm.amount.label("amount"),
                p.currency.label("currency"),
            )
            .join(p, (p.id == pm.payable_id) & (p.tenant_id == tenant_id))
            .where(
                pm.tenant_id == tenant_id,
                pm.movement_type == "PAYMENT",
                pm.id.not_in(payables._reversed_movement_ids(tenant_id)),
            )
            .order_by(pm.effective_date.desc(), pm.id),
            "Pagos vigentes a proveedores con sus compras asociadas.",
            "Fecha efectiva del pago",
            pm.effective_date,
        )
    if report == ReportName.BANK_TRANSACTIONS:
        t, a = BankTransaction, BankTransactionAllocation
        allocated = (
            select(a.bank_transaction_id, func.sum(a.amount).label("amount"))
            .where(a.tenant_id == tenant_id)
            .group_by(a.bank_transaction_id)
            .subquery()
        )
        return ReportQuery(
            select(
                t.id.label("bankMovementId"),
                t.statement_import_id.label("importId"),
                t.occurred_at.label("occurredAt"),
                t.direction.label("direction"),
                t.amount.label("amount"),
                func.coalesce(allocated.c.amount, Decimal("0.00")).label("allocatedAmount"),
            )
            .outerjoin(allocated, allocated.c.bank_transaction_id == t.id)
            .where(t.tenant_id == tenant_id)
            .order_by(t.occurred_at.desc(), t.id),
            "Movimientos bancarios importados y monto conciliado por asignaciones.",
            "Fecha de la transacción en Ecuador",
            t.occurred_at,
        )
    if report in (ReportName.CUSTOMERS, ReportName.SUPPLIERS):
        party_role = "CUSTOMER" if report == ReportName.CUSTOMERS else "SUPPLIER"
        if dialect == "postgresql":
            has_role = cast(Party.roles, JSONB).contains([party_role])
        else:
            members = func.json_each(Party.roles).table_valued("value")
            has_role = select(1).select_from(members).where(members.c.value == party_role).exists()
        return ReportQuery(
            select(
                Party.id.label("partyId"),
                Party.name.label("name"),
                Party.active.label("active"),
                Party.payment_terms_days.label("paymentTermsDays"),
            )
            .where(Party.tenant_id == tenant_id, has_role)
            .order_by(Party.name, Party.id),
            "Maestro de terceros por rol, incluidos los registros inactivos.",
        )
    if report == ReportName.PRODUCTS:
        return ReportQuery(
            select(
                Product.id.label("productId"),
                Product.code.label("code"),
                Product.name.label("name"),
                Product.unit_price.label("unitPrice"),
                Product.tax_category_id.label("taxCategoryId"),
                Product.active.label("active"),
            )
            .where(Product.tenant_id == tenant_id)
            .order_by(Product.name, Product.id),
            "Catálogo de productos y servicios con precio unitario y categoría tributaria.",
        )
    query = erp_reports_operations.operations_query(report, tenant_id)
    if query is None:
        raise ValueError("Reporte no disponible.")
    return query


def _cell(value: object) -> str | int | bool | None:
    if value is None or isinstance(value, (str, int)):
        return value
    if isinstance(value, datetime):
        utc_time = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return utc_time.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, UUID):
        return str(value)
    raise TypeError("Tipo de columna no admitido en el reporte.")


async def read_report(
    session: AsyncSession,
    context: AuthContext,
    *,
    report: ReportName,
    start_date: date | None = None,
    end_date: date | None = None,
    limit: int = 50,
    offset: int = 0,
) -> ERPReportPage:
    if not 1 <= limit <= 100 or offset < 0:
        raise ValueError(
            "El límite debe estar entre 1 y 100 y el desplazamiento ser positivo o cero."
        )
    if start_date and end_date and start_date > end_date:
        raise ValueError("La fecha inicial debe ser anterior o igual a la final.")
    company = (
        await session.execute(
            select(Tenant.name, Tenant.organization_id).where(
                Tenant.id == context.tenant_id, Tenant.active.is_(True)
            )
        )
    ).one_or_none()
    if company is None:
        raise ValueError("Empresa activa no disponible.")
    dialect = session.get_bind().dialect.name
    date_basis = None
    rows: list[list[str | int | bool | None]]
    if report in (ReportName.CATALOG, ReportName.INBOX):
        if start_date or end_date:
            raise ValueError("Este reporte muestra el estado actual y no admite filtros de fecha.")
        if report == ReportName.CATALOG:
            columns = ["report", "tool", "description", "dateBasis", "columns", "filters"]
            description = _CATALOG_DESCRIPTION
            rows = []
            for name in ReportName:
                if name == ReportName.CATALOG:
                    title, basis, fields = _CATALOG_DESCRIPTION, None, columns
                elif name == ReportName.INBOX:
                    title, basis, fields = _INBOX_DESCRIPTION, None, ["group", "count"]
                else:
                    catalog_query = _core_query(name, context.tenant_id, dialect)
                    title, basis = catalog_query.description, catalog_query.date_basis
                    fields = list(catalog_query.statement.selected_columns.keys())
                filters = "startDate,endDate,limit,offset" if basis else "limit,offset"
                rows.append(
                    [name.value, "erp.read_report", title, basis, ",".join(fields), filters]
                )
            if "tax:read" in context.scopes:
                rows.append(
                    [
                        "tax",
                        "tax.get_period_summary",
                        "Compras, ventas y retenciones fiscales.",
                        "Año y meses del período fiscal",
                        ",".join(
                            field.alias or key
                            for key, field in TaxMonthlySummary.model_fields.items()
                        ),
                        "year,startMonth,endMonth",
                    ]
                )
        else:
            columns = ["group", "count"]
            description = _INBOX_DESCRIPTION
            items = await erp_reports_operations.operations_inbox_rows(session, context)
            rows = [list(item) for item in items]
        rows = rows[offset : offset + limit + 1]
    else:
        query = _core_query(report, context.tenant_id, dialect)
        description, date_basis = query.description, query.date_basis
        columns = list(query.statement.selected_columns.keys())
        stmt = query.statement
        col = query.date_column
        if col is None and (start_date or end_date):
            raise ValueError("Este reporte de datos maestros no admite filtros de fecha.")
        if col is not None:
            timestamps = isinstance(col.type, DateTime)
            if start_date:
                lower = datetime.combine(start_date, time.min, FISCAL_TIMEZONE).astimezone(UTC)
                stmt = stmt.where(col >= (lower if timestamps else start_date))
            if end_date and timestamps and end_date < date.max:
                upper = datetime.combine(end_date + timedelta(days=1), time.min, FISCAL_TIMEZONE)
                stmt = stmt.where(col < upper.astimezone(UTC))
            elif end_date and not timestamps:
                stmt = stmt.where(col <= end_date)
        result = await session.execute(stmt.offset(offset).limit(limit + 1))
        rows = [[_cell(value) for value in row] for row in result]
    return ERPReportPage(
        report=report,
        organization_alias=company.organization_id,
        company_name=company.name,
        description=description,
        date_basis=date_basis,
        start_date=start_date,
        end_date=end_date,
        columns=columns,
        rows=rows[:limit],
        offset=offset,
        limit=limit,
        next_offset=offset + limit if len(rows) > limit else None,
    )
