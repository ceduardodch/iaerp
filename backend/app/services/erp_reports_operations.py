"""Proyecciones analíticas acotadas de operaciones del tenant autenticado."""

from typing import Any
from uuid import UUID

from sqlalchemy import Date, Select, String, and_, case, cast, func, select, type_coerce
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthContext
from app.models.analytics import AnalyticClassification, AnalyticClassificationValue
from app.models.crm import Lead, SocialCampaign
from app.models.legal_commercial import (
    AwsConsumptionCut,
    BillingProposal,
    CommercialContract,
    ContractVersion,
)
from app.models.masters import EmissionPoint, Establishment
from app.models.notifications import NotificationEvent
from app.models.payroll import PayrollEntry, PayrollPeriod
from app.models.platform import Tenant
from app.schemas.erp_reports import ReportName
from app.services import action_queue
from app.services.erp_report_query import ReportQuery


def operations_query(report: ReportName, tenant_id: UUID) -> ReportQuery | None:
    stmt: Select[Any]
    if report == "contracts":
        c, v = CommercialContract, ContractVersion
        stmt = (
            select(
                c.id.label("contractId"),
                c.party_id.label("partyId"),
                c.contract_number.label("number"),
                c.title.label("title"),
                c.service_type.label("serviceType"),
                c.status.label("status"),
                v.version_number.label("currentVersion"),
                v.valid_from.label("validFrom"),
                v.valid_to.label("validTo"),
                v.payment_terms_days.label("paymentTermsDays"),
            )
            .outerjoin(
                v,
                and_(v.tenant_id == tenant_id, v.id == c.current_version_id, v.contract_id == c.id),
            )
            .where(c.tenant_id == tenant_id)
            .order_by(c.contract_number, c.id)
        )
        return ReportQuery(
            stmt,
            "Contratos y condiciones de su versión vigente asignada.",
            "Fecha de alta del contrato.",
            c.created_at,
        )
    if report == "proposals":
        proposal = BillingProposal
        stmt = (
            select(
                proposal.id.label("proposalId"),
                proposal.party_id.label("partyId"),
                proposal.issue_date.label("issueDate"),
                proposal.status.label("status"),
                proposal.billing_type.label("billingType"),
                proposal.currency.label("currency"),
                proposal.total_amount.label("amount"),
                proposal.sales_document_id.label("salesDocumentId"),
                proposal.period_start.label("periodStart"),
                proposal.period_end.label("periodEnd"),
            )
            .where(proposal.tenant_id == tenant_id)
            .order_by(proposal.issue_date, proposal.id)
        )
        return ReportQuery(
            stmt,
            "Propuestas de facturación, importe y moneda por propuesta.",
            "Fecha de emisión de la propuesta.",
            proposal.issue_date,
        )
    if report == "aws_cuts":
        cut = AwsConsumptionCut
        stmt = (
            select(
                cut.id.label("cutId"),
                cut.party_id.label("partyId"),
                cut.period_start.label("periodStart"),
                cut.period_end.label("periodEnd"),
                cut.status.label("status"),
                cut.currency.label("currency"),
                cut.total_cost.label("cost"),
            )
            .where(cut.tenant_id == tenant_id)
            .order_by(cut.period_end, cut.id)
        )
        return ReportQuery(
            stmt,
            "Cortes de consumo AWS y costo registrado por cliente.",
            "Último día del corte.",
            cut.period_end,
        )
    if report == "crm":
        stmt = (
            select(
                Lead.id.label("leadId"),
                Lead.party_id.label("partyId"),
                Lead.status.label("stage"),
                Lead.qualification_status.label("qualification"),
                Lead.hotness.label("hotness"),
                Lead.score.label("score"),
                Lead.estimated_value.label("estimatedValue"),
                Lead.expected_close_date.label("expectedCloseDate"),
                Lead.created_at.label("createdAt"),
            )
            .where(Lead.tenant_id == tenant_id)
            .order_by(Lead.created_at, Lead.id)
        )
        return ReportQuery(
            stmt,
            "Oportunidades, etapa actual y valor comercial estimado.",
            "Fecha de creación de la oportunidad.",
            Lead.created_at,
        )
    if report == "campaigns":
        campaign = SocialCampaign
        stmt = (
            select(
                campaign.id.label("campaignId"),
                campaign.name.label("name"),
                campaign.provider.label("provider"),
                campaign.status.label("status"),
                campaign.daily_budget.label("dailyBudget"),
                campaign.currency.label("currency"),
                campaign.created_at.label("createdAt"),
            )
            .where(campaign.tenant_id == tenant_id)
            .order_by(campaign.created_at, campaign.id)
        )
        return ReportQuery(
            stmt,
            "Campañas del CRM y presupuesto diario configurado.",
            "Fecha de creación de la campaña.",
            campaign.created_at,
        )
    if report == "notifications":
        event = NotificationEvent
        stmt = (
            select(
                event.rule_type.label("ruleType"),
                event.status.label("status"),
                func.count(event.id).label("eventCount"),
            )
            .where(event.tenant_id == tenant_id)
            .group_by(event.rule_type, event.status)
            .order_by(event.rule_type, event.status)
        )
        return ReportQuery(
            stmt,
            "Número de avisos por tipo y estado actual.",
            "Fecha programada del aviso.",
            event.scheduled_at,
        )
    if report == "payroll":
        period, entry = PayrollPeriod, PayrollEntry
        # Construir una fecha SQL funciona en SQLite y PostgreSQL y conserva
        # períodos de nómina creados sin asientos (sus importes son NULL).
        yyyy_mm_dd = (
            cast(period.anio, String)
            + "-"
            + case((period.mes < 10, "0"), else_="")
            + cast(period.mes, String)
            + "-01"
        )
        period_date = type_coerce(func.date(yyyy_mm_dd), Date)
        stmt = (
            select(
                period.anio.label("year"),
                period.mes.label("month"),
                period.status.label("status"),
                func.count(entry.id).label("entryCount"),
                func.sum(entry.total_ingresos).label("grossPay"),
                func.sum(entry.total_descuentos).label("deductions"),
                func.sum(entry.aporte_iess).label("employeeIess"),
                func.sum(entry.liquido).label("netPay"),
            )
            .outerjoin(entry, and_(entry.tenant_id == tenant_id, entry.period_id == period.id))
            .where(period.tenant_id == tenant_id)
            .group_by(period.anio, period.mes, period.status)
            .order_by(period.anio, period.mes)
        )
        return ReportQuery(
            stmt,
            "Nómina en USD por período y estado. Sin filas individuales.",
            "Primer día del mes de nómina.",
            period_date,
        )
    if report == "company":
        establishments = (
            select(func.count(Establishment.id))
            .where(Establishment.tenant_id == tenant_id, Establishment.active.is_(True))
            .scalar_subquery()
        )
        points = (
            select(func.count(EmissionPoint.id))
            .where(EmissionPoint.tenant_id == tenant_id, EmissionPoint.active.is_(True))
            .scalar_subquery()
        )
        stmt = (
            select(
                Tenant.name.label("companyName"),
                Tenant.organization_id.label("organization"),
                Tenant.active.label("active"),
                Tenant.default_payment_terms_days.label("termsDays"),
                establishments.label("activeEstablishments"),
                points.label("activeEmissionPoints"),
            )
            .where(Tenant.id == tenant_id)
            .order_by(Tenant.id)
        )
        return ReportQuery(stmt, "Empresa autenticada y estructura operativa actual.")
    if report == "establishments":
        stmt = (
            select(
                Establishment.id.label("establishmentId"),
                Establishment.code.label("code"),
                Establishment.name.label("name"),
                Establishment.active.label("active"),
                EmissionPoint.code.label("emissionPoint"),
                EmissionPoint.active.label("emissionPointActive"),
            )
            .outerjoin(
                EmissionPoint,
                and_(
                    EmissionPoint.tenant_id == tenant_id,
                    EmissionPoint.establishment_id == Establishment.id,
                ),
            )
            .where(Establishment.tenant_id == tenant_id)
            .order_by(Establishment.code, Establishment.id, EmissionPoint.code, EmissionPoint.id)
        )
        return ReportQuery(stmt, "Establecimientos y puntos de emisión configurados.")
    if report == "classifications":
        category, value = AnalyticClassification, AnalyticClassificationValue
        stmt = (
            select(
                category.id.label("classificationId"),
                category.code.label("code"),
                category.name.label("name"),
                category.active.label("active"),
                value.id.label("valueId"),
                value.name.label("valueName"),
                value.parent_id.label("parentValueId"),
                value.active.label("valueActive"),
            )
            .outerjoin(
                value, and_(value.tenant_id == tenant_id, value.classification_id == category.id)
            )
            .where(category.tenant_id == tenant_id)
            .order_by(category.code, category.id, value.name, value.id)
        )
        return ReportQuery(stmt, "Catálogos de clasificación y sus valores controlados.")
    return None


async def operations_inbox_rows(
    session: AsyncSession, context: AuthContext
) -> list[tuple[str, int]]:
    queue = await action_queue.build_action_queue(session, context, limit=action_queue.MAX_LIMIT)
    return [
        ("collections", len(queue.collections)),
        ("prospecting", len(queue.prospecting)),
    ]
