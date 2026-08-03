"""Pendientes tributarios creados por el programador, sin acciones fiscales."""

from __future__ import annotations

import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import SessionFactory
from app.models.tax import FiscalDocument, TaxPeriod, TaxTask

_OPEN = ("PENDIENTE", "EN_PROCESO")


async def _ensure_task(
    session: AsyncSession,
    *,
    period: TaxPeriod,
    task_type: str,
    title: str,
    detail: str,
) -> bool:
    existing = await session.scalar(
        select(TaxTask.id).where(
            TaxTask.tenant_id == period.tenant_id,
            TaxTask.tax_period_id == period.id,
            TaxTask.task_type == task_type,
            TaxTask.status.in_(_OPEN),
        )
    )
    if existing is not None:
        return False
    session.add(
        TaxTask(
            tenant_id=period.tenant_id,
            tax_period_id=period.id,
            task_type=task_type,
            title=title,
            detail=detail,
            due_date=period.due_date,
            requires_approval=True,
        )
    )
    return True


async def generate_tax_tasks_once() -> int:
    """Crea pendientes repetibles; nunca declara, entrega un anexo ni paga."""
    created = 0
    async with SessionFactory() as session, session.begin():
        periods = list(
            await session.scalars(
                select(TaxPeriod).where(
                    TaxPeriod.obligation_type == "IVA",
                    TaxPeriod.status != "DECLARADO",
                )
            )
        )
        for period in periods:
            documents = list(
                await session.scalars(
                    select(FiscalDocument).where(
                        FiscalDocument.tenant_id == period.tenant_id,
                        FiscalDocument.tax_period_id == period.id,
                    )
                )
            )
            label = f"{period.month:02d}/{period.year}"
            if not documents:
                created += await _ensure_task(
                    session,
                    period=period,
                    task_type="BAJAR_COMPROBANTES",
                    title=f"Bajar comprobantes SRI {label}",
                    detail=(
                        "Carga manualmente los XML o el TXT del portal; "
                        "no se automatiza el portal SRI."
                    ),
                )
                continue
            if any(document.is_preliminary for document in documents):
                created += await _ensure_task(
                    session,
                    period=period,
                    task_type="COMPLETAR_EVIDENCIA",
                    title=f"Completar evidencia tributaria {label}",
                    detail=(
                        "Hay comprobantes preliminares. Carga el XML autorizado "
                        "antes de declarar o generar ATS."
                    ),
                )
            else:
                created += await _ensure_task(
                    session,
                    period=period,
                    task_type="REVISAR_IVA",
                    title=f"Revisar IVA {label}",
                    detail="Revisa los valores y su trazabilidad antes de una declaración humana.",
                )
                created += await _ensure_task(
                    session,
                    period=period,
                    task_type="PREPARAR_ATS",
                    title=f"Preparar ATS {label}",
                    detail="Genera y valida el anexo; su entrega al SRI exige aprobación humana.",
                )
    return created


async def run_tax_scheduler() -> None:
    while True:
        await generate_tax_tasks_once()
        await asyncio.sleep(60)


__all__ = ["generate_tax_tasks_once", "run_tax_scheduler"]
