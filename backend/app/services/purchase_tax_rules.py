import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthContext
from app.models.payables import Payable, PurchaseTaxRule
from app.models.platform import AutomationSettings
from app.models.tax import FiscalDocument, TaxPeriod
from app.schemas.payables import PurchaseTaxRuleUpdate
from app.services.unit_of_work import append_audit


async def list_rules(session: AsyncSession, context: AuthContext) -> list[PurchaseTaxRule]:
    return list(
        await session.scalars(
            select(PurchaseTaxRule)
            .where(PurchaseTaxRule.tenant_id == context.tenant_id)
            .order_by(PurchaseTaxRule.supplier_ruc)
        )
    )


async def save_rule(
    session: AsyncSession,
    context: AuthContext,
    supplier_ruc: str,
    data: PurchaseTaxRuleUpdate,
) -> PurchaseTaxRule:
    rule = await session.scalar(
        select(PurchaseTaxRule).where(
            PurchaseTaxRule.tenant_id == context.tenant_id,
            PurchaseTaxRule.supplier_ruc == supplier_ruc,
        )
    )
    if rule is None:
        rule = PurchaseTaxRule(tenant_id=context.tenant_id, supplier_ruc=supplier_ruc)
        session.add(rule)
    rule.tax_classification = data.tax_classification
    rule.active = data.active
    await session.flush()
    return rule


async def apply_recovered_invoice_rule(
    session: AsyncSession,
    context: AuthContext,
    *,
    document: FiscalDocument,
    period: TaxPeriod,
    job_id: uuid.UUID,
) -> None:
    """El worker llama aquí tras validar el XML y con el tenant bloqueado."""
    if (
        document.direction != "RECIBIDO"
        or document.doc_type != "FACTURA"
        or document.is_preliminary
        or period.status == "DECLARADO"
        or document.tax_period_id != period.id
        or document.tenant_id != context.tenant_id
        or period.tenant_id != context.tenant_id
        or not document.counterparty_identification
        or "tax:write" not in context.scopes
    ):
        return

    automation = await session.get(AutomationSettings, context.tenant_id)
    if automation is None or not automation.writes_enabled:
        return
    rule = await session.scalar(
        select(PurchaseTaxRule).where(
            PurchaseTaxRule.tenant_id == context.tenant_id,
            PurchaseTaxRule.supplier_ruc == document.counterparty_identification,
            PurchaseTaxRule.active.is_(True),
        )
    )
    if rule is None:
        return
    if document.access_key:
        declared_credit_note = await session.scalar(
            select(FiscalDocument.id)
            .join(
                TaxPeriod,
                (TaxPeriod.id == FiscalDocument.tax_period_id)
                & (TaxPeriod.tenant_id == FiscalDocument.tenant_id),
            )
            .where(
                FiscalDocument.tenant_id == context.tenant_id,
                FiscalDocument.direction == "RECIBIDO",
                FiscalDocument.doc_type == "NOTA_CREDITO",
                FiscalDocument.related_access_key == document.access_key,
                TaxPeriod.status == "DECLARADO",
            )
            .limit(1)
        )
        if declared_credit_note is not None:
            return
    payable = await session.scalar(
        select(Payable)
        .where(
            Payable.tenant_id == context.tenant_id,
            Payable.fiscal_document_id == document.id,
        )
        .with_for_update()
    )
    if (
        payable is None
        or payable.status == "VOID"
        or payable.tax_classification != "DEDUCTIBLE_PENDING_REVIEW"
    ):
        return
    payable.tax_classification = rule.tax_classification
    await append_audit(
        session,
        context=context,
        action="payable.purchase_tax_rule_applied",
        entity_type="payable",
        entity_id=str(payable.id),
        correlation_id=str(job_id),
        idempotency_key=f"purchase-tax-rule:{document.id}",
        details={
            "rule_id": str(rule.id),
            "tax_classification": rule.tax_classification,
            "fiscal_document_id": str(document.id),
        },
    )
    await session.flush()
