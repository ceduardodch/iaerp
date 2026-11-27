"""Real domain rows, tenant boundaries and read-only behavior of operations reports."""

from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import event
from sqlalchemy.dialects import postgresql

from app.db.session import SessionFactory, engine
from app.models.analytics import AnalyticClassification, AnalyticClassificationValue
from app.models.crm import Lead, SocialCampaign
from app.models.legal_commercial import AwsConsumptionCut, BillingProposal, CommercialContract
from app.models.masters import EmissionPoint, Establishment, Party
from app.models.notifications import RULE_TYPES, NotificationEvent
from app.models.payroll import PayrollEmployee, PayrollEntry, PayrollPeriod
from app.schemas.erp_reports import ReportName
from app.services.erp_reports_operations import operations_inbox_rows, operations_query
from tests.conftest import TENANT_A, TENANT_B
from tests.test_tax_due_dates import context_for


async def test_operations_only_project_selected_business_data_from_the_current_tenant():
    day = date(2026, 1, 1)
    sensitive = "PRIVATE-FIXTURE"
    async with SessionFactory() as session, session.begin():
        party = Party(
            tenant_id=TENANT_A,
            name=sensitive,
            identification_type="RUC",
            identification_number="1799999999003",
            roles=["CUSTOMER"],
            phone="0999900000",
        )
        establishment = Establishment(
            tenant_id=TENANT_A, code="001", name="Principal", address=sensitive
        )
        category = AnalyticClassification(tenant_id=TENANT_A, code="C", name="Centro")
        period = PayrollPeriod(tenant_id=TENANT_A, anio=2026, mes=1, status="APPROVED")
        employee = PayrollEmployee(
            tenant_id=TENANT_A,
            full_name=sensitive,
            identification_number="0000000000",
            sueldo_mensual=100,
            fecha_ingreso=day,
        )
        session.add_all([party, establishment, category, period, employee])
        await session.flush()
        session.add_all(
            [
                EmissionPoint(tenant_id=TENANT_A, establishment_id=establishment.id, code="002"),
                AnalyticClassificationValue(
                    tenant_id=TENANT_A, classification_id=category.id, code="N", name="Norte"
                ),
                CommercialContract(
                    tenant_id=TENANT_A, party_id=party.id, contract_number="C-1", title="Servicio"
                ),
                AwsConsumptionCut(
                    tenant_id=TENANT_A,
                    party_id=party.id,
                    period_start=day,
                    period_end=day,
                    total_cost=Decimal("19.15"),
                    source="MANUAL",
                    evidence_object_key=sensitive,
                ),
                BillingProposal(
                    tenant_id=TENANT_A,
                    party_id=party.id,
                    issue_date=day,
                    total_amount=Decimal("22.10"),
                    commercial_snapshot={"internal": sensitive},
                ),
                Lead(
                    tenant_id=TENANT_A,
                    party_id=party.id,
                    title=sensitive,
                    estimated_value=Decimal("77.30"),
                ),
                SocialCampaign(
                    tenant_id=TENANT_A,
                    name="Campaña",
                    daily_budget=10,
                    currency="USD",
                    primary_text=sensitive,
                    headline=sensitive,
                ),
                NotificationEvent(
                    tenant_id=TENANT_A,
                    rule_type=RULE_TYPES[0],
                    dedupe_key=sensitive,
                    scheduled_at=datetime(2026, 1, 1, tzinfo=UTC),
                    payload={"body": sensitive},
                ),
                PayrollEntry(
                    tenant_id=TENANT_A,
                    period_id=period.id,
                    employee_id=employee.id,
                    dias_trabajados=30,
                    imponible=100,
                    decimo_tercero=0,
                    decimo_cuarto=0,
                    fondos_reserva=0,
                    total_ingresos=100,
                    aporte_iess=Decimal("9.45"),
                    total_descuentos=Decimal("9.45"),
                    liquido=Decimal("90.55"),
                    sbu_aplicado=100,
                    tasa_iess_aplicada=Decimal("0.0945"),
                    tasa_fondos_aplicada=0,
                ),
            ]
        )

    fields = {
        "contracts": ("number", "C-1"),
        "classifications": ("valueName", "Norte"),
        "aws_cuts": ("cost", Decimal("19.15")),
        "proposals": ("amount", Decimal("22.10")),
        "crm": ("estimatedValue", Decimal("77.30")),
        "campaigns": ("currency", "USD"),
        "notifications": ("eventCount", 1),
        "payroll": ("netPay", Decimal("90.55")),
        "establishments": ("emissionPoint", "002"),
        "company": ("activeEstablishments", 1),
    }

    def only_select(connection, cursor, statement, parameters, context, executemany):
        assert statement.lstrip().upper().startswith("SELECT")

    event.listen(engine.sync_engine, "before_cursor_execute", only_select)
    try:
        async with SessionFactory() as session:
            for name, (column, expected) in fields.items():
                for tenant in (TENANT_A, TENANT_B):
                    query = operations_query(ReportName(name), tenant)
                    assert query is not None
                    stmt = query.statement
                    if name == "payroll":
                        stmt = stmt.where(query.date_column.between(day, day))
                    stmt.compile(dialect=postgresql.dialect())
                    rows = (await session.execute(stmt)).mappings().all()
                    if tenant == TENANT_B and name != "company":
                        assert not rows, name
                    else:
                        assert len(rows) == 1, name
                        assert rows[0][column] == (expected if tenant == TENANT_A else 0)
                        assert sensitive not in str(rows)
            assert await operations_inbox_rows(session, context_for(TENANT_A)) == [
                ("collections", 0),
                ("prospecting", 1),
            ]
            assert await operations_inbox_rows(session, context_for(TENANT_B)) == [
                ("collections", 0),
                ("prospecting", 0),
            ]
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", only_select)
