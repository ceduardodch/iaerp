"""Tenant-scoped invoice months and compact, keyset-paginated rows."""

import re
import uuid
from calendar import monthrange
from datetime import date

from fastapi import HTTPException
from sqlalchemy import and_, extract, func, or_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.selectable import Subquery

from app.models.billing import SalesDocument
from app.models.masters import EmissionPoint, Establishment, Party
from app.models.receivables import Receivable
from app.schemas.billing import InvoiceMonthPageRead, InvoiceMonthRead, InvoiceMonthRowRead
from app.services.billing import _collection_status_from_receivable


def _filtered_invoices(
    tenant_id: uuid.UUID, query: str | None, status: str | None, party_id: uuid.UUID | None
) -> Subquery:
    statement = (
        select(
            SalesDocument.id,
            SalesDocument.issue_date,
            SalesDocument.status,
            SalesDocument.total,
            SalesDocument.currency,
            SalesDocument.sequential,
            Establishment.code.label("establishment"),
            EmissionPoint.code.label("point"),
            Party.name.label("customer"),
        )
        .join(Establishment, SalesDocument.establishment_id == Establishment.id)
        .join(EmissionPoint, SalesDocument.emission_point_id == EmissionPoint.id)
        .join(Party, SalesDocument.party_id == Party.id)
        .where(
            SalesDocument.tenant_id == tenant_id,
            Establishment.tenant_id == tenant_id,
            EmissionPoint.tenant_id == tenant_id,
            Party.tenant_id == tenant_id,
            SalesDocument.document_type == "INVOICE",
            SalesDocument.archived_at.is_(None),
        )
    )
    if party_id is not None:
        statement = statement.where(SalesDocument.party_id == party_id)
    if status:
        statement = statement.where(SalesDocument.status == status)
    if query and (term := query.strip()):
        number = re.fullmatch(r"([0-9]{3})-([0-9]{3})-([0-9]{9})", term)
        if number:
            statement = statement.where(
                Establishment.code == number[1],
                EmissionPoint.code == number[2],
                SalesDocument.sequential == number[3],
            )
        else:
            statement = statement.where(
                or_(
                    SalesDocument.sequential.contains(term, autoescape=True),
                    SalesDocument.access_key.contains(term, autoescape=True),
                )
            )
    return statement.subquery()


async def list_months(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    query: str | None,
    status: str | None,
    party_id: uuid.UUID | None,
) -> list[InvoiceMonthRead]:
    rows = _filtered_invoices(tenant_id, query, status, party_id).c
    year = extract("year", rows.issue_date)
    month = extract("month", rows.issue_date)
    groups = await session.execute(
        select(year, month, rows.currency, func.count(), func.sum(rows.total))
        .group_by(year, month, rows.currency)
        .order_by(year.desc(), month.desc(), rows.currency)
    )
    return [
        InvoiceMonthRead(month=f"{int(y):04}-{int(m):02}", currency=currency, count=n, total=total)
        for y, m, currency, n, total in groups
    ]


async def list_month_page(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    month: str,
    *,
    query: str | None,
    status: str | None,
    party_id: uuid.UUID | None,
    currency: str | None,
    cursor: str | None,
    limit: int,
) -> InvoiceMonthPageRead:
    try:
        start = date.fromisoformat(month + "-01")
    except ValueError as exc:
        raise HTTPException(422, "Invalid invoice month") from exc
    end = start.replace(day=monthrange(start.year, start.month)[1])
    invoices = _filtered_invoices(tenant_id, query, status, party_id)
    rows = invoices.c
    statement = (
        select(invoices, Receivable.status.label("receivable_status"))
        .outerjoin(
            Receivable,
            and_(Receivable.tenant_id == tenant_id, Receivable.sales_document_id == rows.id),
        )
        .where(rows.issue_date.between(start, end))
    )
    if currency is not None:
        statement = statement.where(rows.currency == currency)
    if cursor is not None:
        try:
            date_part, id_part = cursor.split(":")
            last_date = date.fromisoformat(date_part)
            last_id = uuid.UUID(id_part)
            if not start <= last_date <= end:
                raise ValueError
        except ValueError as exc:
            raise HTTPException(422, "Invalid invoice cursor") from exc
        statement = statement.where(tuple_(rows.issue_date, rows.id) < (last_date, last_id))
    result = (
        await session.execute(
            statement.order_by(rows.issue_date.desc(), rows.id.desc()).limit(limit + 1)
        )
    ).all()
    items = [
        InvoiceMonthRowRead(
            id=row.id,
            number=f"{row.establishment}-{row.point}-{row.sequential}",
            customer_name=row.customer,
            issue_date=row.issue_date,
            status=row.status,
            collection_status=_collection_status_from_receivable(row.receivable_status),
            total=row.total,
            currency=row.currency,
        )
        for row in result[:limit]
    ]
    next_cursor = f"{items[-1].issue_date}:{items[-1].id}" if len(result) > limit else None
    return InvoiceMonthPageRead(items=items, next_cursor=next_cursor)
