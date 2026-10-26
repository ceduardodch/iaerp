"""Declaraciones ATS por cliente y tenant, guardadas en la UOW del anexo."""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthContext
from app.models.tax import AtsCustomerDeclaration, FiscalDocument, TaxPeriod
from app.services.tax.ats_identification import (
    ats_identification_type,
    normalize_ats_identification,
)


async def list_customer_types(session: AsyncSession, context: AuthContext) -> dict[str, str]:
    rows = await session.scalars(
        select(AtsCustomerDeclaration).where(AtsCustomerDeclaration.tenant_id == context.tenant_id)
    )
    return {row.identification: row.customer_type for row in rows}


async def remember_customer_types(
    session: AsyncSession,
    context: AuthContext,
    *,
    period: TaxPeriod,
    documents: list[FiscalDocument],
    declarations: dict[str, str],
) -> dict[str, str]:
    """Solo admite clientes extranjeros emitidos en el período autenticado."""
    if period.tenant_id != context.tenant_id:
        raise HTTPException(status_code=404, detail="Tax period not found")
    valid_ids = {
        normalize_ats_identification(document.counterparty_identification)
        for document in documents
        if document.tenant_id == context.tenant_id
        and document.tax_period_id == period.id
        and document.direction == "EMITIDO"
        and document.doc_type in {"FACTURA", "NOTA_CREDITO", "NOTA_DEBITO"}
        and ats_identification_type(document.counterparty_identification, sale=True) == "06"
    }
    if len(declarations) > 100 or any(
        key not in valid_ids
        or value not in {"01", "02"}
        or normalize_ats_identification(key) != key
        for key, value in declarations.items()
    ):
        raise HTTPException(
            status_code=422, detail="Clasificación ATS no válida para clientes del período."
        )
    rows = list(
        await session.scalars(
            select(AtsCustomerDeclaration).where(
                AtsCustomerDeclaration.tenant_id == context.tenant_id
            )
        )
    )
    existing = {row.identification: row for row in rows}
    for identification, customer_type in declarations.items():
        row = existing.get(identification)
        if row is None:
            row = AtsCustomerDeclaration(
                tenant_id=context.tenant_id,
                identification=identification,
                customer_type=customer_type,
            )
            session.add(row)
            existing[identification] = row
        else:
            row.customer_type = customer_type
    if declarations:
        await session.flush()
    return {key: row.customer_type for key, row in existing.items()}
