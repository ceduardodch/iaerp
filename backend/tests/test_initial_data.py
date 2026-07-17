from decimal import Decimal

from sqlalchemy import func, select

from app.db.base import Base
from app.db.session import SessionFactory, engine
from app.initial_data import (
    DEMO_TENANT_ID,
    DEMO_USER_ID,
    NO_MEMBERSHIP_USER_ID,
    SECOND_TENANT_ID,
    SEED_VERSION,
    TENANT_A_CREDIT_NOTE_AUTHORIZED_ID,
    TENANT_A_EMISSION_POINT_ID,
    TENANT_A_ESTABLISHMENT_ID,
    TENANT_A_INVOICE_AUTHORIZED_ID,
    TENANT_A_INVOICE_PENDING_ID,
    TENANT_A_INVOICE_REJECTED_ID,
    TENANT_A_SERVICE_ACCOUNT_ID,
    TENANT_B_CREDIT_NOTE_AUTHORIZED_ID,
    TENANT_B_INVOICE_AUTHORIZED_ID,
    TENANT_B_SERVICE_ACCOUNT_ID,
    seed,
)
from app.models.billing import (
    DocumentRelation,
    SalesDocument,
    SalesDocumentLine,
    Sequence,
    SRITransmission,
)
from app.models.masters import Establishment, Party, Product, Tag, TaxCategory
from app.models.platform import Membership, ServiceAccount, Tenant, User
from app.services import access_key as access_key_service
from app.services.fiscal_policy import FISCAL_POLICY_V1, LineInput


async def _reset_schema() -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)


async def test_seed_is_repeatable_and_preserves_foreign_keys():
    await _reset_schema()

    await seed()
    await seed()

    async with SessionFactory() as session:
        assert SEED_VERSION == "sprint-02-v1"
        assert await session.scalar(select(func.count()).select_from(Tenant)) == 2
        assert await session.scalar(select(func.count()).select_from(User)) == 4
        assert await session.scalar(select(func.count()).select_from(Membership)) == 4
        assert await session.scalar(select(func.count()).select_from(ServiceAccount)) == 2
        assert await session.scalar(select(func.count()).select_from(TaxCategory)) == 4
        assert await session.scalar(select(func.count()).select_from(Establishment)) == 2
        assert await session.scalar(select(func.count()).select_from(Tag)) == 2
        assert await session.scalar(select(func.count()).select_from(Party)) == 2
        assert await session.scalar(select(func.count()).select_from(Product)) == 4
        assert await session.scalar(select(func.count()).select_from(SalesDocument)) == 8
        assert await session.scalar(select(func.count()).select_from(SalesDocumentLine)) == 10
        assert await session.scalar(select(func.count()).select_from(SRITransmission)) == 8
        assert await session.scalar(select(func.count()).select_from(DocumentRelation)) == 2
        assert await session.scalar(select(func.count()).select_from(Sequence)) == 4

        owner_memberships = (
            await session.scalars(select(Membership).where(Membership.user_id == DEMO_USER_ID))
        ).all()
        assert {row.tenant_id for row in owner_memberships} == {
            DEMO_TENANT_ID,
            SECOND_TENANT_ID,
        }
        assert (
            await session.scalar(
                select(func.count())
                .select_from(Membership)
                .where(Membership.user_id == NO_MEMBERSHIP_USER_ID)
            )
            == 0
        )

        account_a = await session.get(ServiceAccount, TENANT_A_SERVICE_ACCOUNT_ID)
        account_b = await session.get(ServiceAccount, TENANT_B_SERVICE_ACCOUNT_ID)
        assert account_a is not None and account_a.client_id == "iaerp-agent-norte"
        assert account_b is not None and account_b.client_id == "iaerp-agent-sur"

        products = (await session.scalars(select(Product).order_by(Product.code))).all()
        assert [product.code for product in products] == [
            "NORTE-001",
            "NORTE-002",
            "SUR-001",
            "SUR-002",
        ]


async def test_seed_adopts_existing_rows_by_business_key():
    await _reset_schema()
    await seed()

    async with SessionFactory() as session:
        original_tax_ids = set(await session.scalars(select(TaxCategory.id)))
        original_document_ids = set(await session.scalars(select(SalesDocument.id)))

    await seed()
    await seed()

    async with SessionFactory() as session:
        tax_ids = set(await session.scalars(select(TaxCategory.id)))
        document_ids = set(await session.scalars(select(SalesDocument.id)))
        assert tax_ids == original_tax_ids
        assert document_ids == original_document_ids
        assert await session.scalar(select(func.count()).select_from(Tenant)) == 2
        assert await session.scalar(select(func.count()).select_from(Product)) == 4
        assert await session.scalar(select(func.count()).select_from(SalesDocument)) == 8


async def test_seed_authorized_invoice_totals_match_fiscal_policy():
    """La factura AUTHORIZED sembrada debe cuadrar exactamente con fiscal_policy.

    Recalcula desde cero las mismas dos lineas (gravada 15% con cantidad
    decimal + descuento, y tarifa 0%) y compara contra lo persistido: el seed
    nunca debe escribir un monto a mano que fiscal_policy no reproduzca.
    """

    await _reset_schema()
    await seed()

    async with SessionFactory() as session:
        invoice = await session.get(SalesDocument, TENANT_A_INVOICE_AUTHORIZED_ID)
        assert invoice is not None
        assert invoice.status == "AUTHORIZED"
        assert invoice.fiscal_policy_version == FISCAL_POLICY_V1.version

        lines = (
            await session.scalars(
                select(SalesDocumentLine)
                .where(SalesDocumentLine.sales_document_id == invoice.id)
                .order_by(SalesDocumentLine.line_number)
            )
        ).all()
        assert len(lines) == 2

        recalculated = FISCAL_POLICY_V1.calculate_document(
            [
                LineInput(
                    quantity=line.quantity,
                    unit_price=line.unit_price,
                    discount=line.discount,
                    tax_rate=line.tax_rate,
                    tax_sri_code=line.tax_sri_code,
                )
                for line in lines
            ]
        )

        assert recalculated.subtotal == invoice.subtotal
        assert recalculated.tax_total == invoice.tax_total
        assert recalculated.total == invoice.total
        for calculated_line, persisted_line in zip(recalculated.lines, lines, strict=True):
            assert calculated_line.base_amount == persisted_line.base_amount
            assert calculated_line.tax_amount == persisted_line.tax_amount

        # La linea gravada usa cantidad decimal y descuento por linea, tal
        # como exige el plan de pruebas del sprint.
        assert lines[0].quantity == Decimal("3.500000")
        assert lines[0].discount == Decimal("2.50")
        assert lines[0].tax_sri_code == "4"
        # La linea de tarifa 0% no aporta impuesto.
        assert lines[1].tax_sri_code == "0"
        assert lines[1].tax_amount == Decimal("0.00")


async def test_seed_access_keys_pass_modulus_11():
    await _reset_schema()
    await seed()

    async with SessionFactory() as session:
        documents = (
            await session.scalars(
                select(SalesDocument).where(SalesDocument.access_key.is_not(None))
            )
        ).all()

    assert documents, "seed should have created at least one document with an access key"
    for document in documents:
        assert document.access_key is not None
        assert len(document.access_key) == 49
        assert access_key_service.verify_access_key(document.access_key) is True


async def test_seed_credit_note_never_exceeds_creditable_balance():
    await _reset_schema()
    await seed()

    async with SessionFactory() as session:
        for invoice_id, credit_note_id in (
            (TENANT_A_INVOICE_AUTHORIZED_ID, TENANT_A_CREDIT_NOTE_AUTHORIZED_ID),
            (TENANT_B_INVOICE_AUTHORIZED_ID, TENANT_B_CREDIT_NOTE_AUTHORIZED_ID),
        ):
            invoice = await session.get(SalesDocument, invoice_id)
            credit_note = await session.get(SalesDocument, credit_note_id)
            assert invoice is not None and credit_note is not None
            assert credit_note.status == "AUTHORIZED"
            assert credit_note.total < invoice.total

            relation = await session.scalar(
                select(DocumentRelation).where(
                    DocumentRelation.credit_note_id == credit_note_id
                )
            )
            assert relation is not None
            assert relation.related_invoice_id == invoice_id


async def test_seed_invoice_statuses_cover_the_full_lifecycle():
    await _reset_schema()
    await seed()

    async with SessionFactory() as session:
        for invoice_id, expected_status, transmission_status in (
            (TENANT_A_INVOICE_AUTHORIZED_ID, "AUTHORIZED", "AUTHORIZED"),
            (TENANT_A_INVOICE_PENDING_ID, "PENDING_AUTHORIZATION", "RECEIVED"),
            (TENANT_A_INVOICE_REJECTED_ID, "REJECTED", "REJECTED"),
        ):
            invoice = await session.get(SalesDocument, invoice_id)
            assert invoice is not None
            assert invoice.status == expected_status

            transmission = await session.scalar(
                select(SRITransmission).where(
                    SRITransmission.sales_document_id == invoice_id
                )
            )
            assert transmission is not None
            assert transmission.status == transmission_status
            assert transmission.messages, "fixture transmission should carry a message"

        rejected_transmission = await session.scalar(
            select(SRITransmission).where(
                SRITransmission.sales_document_id == TENANT_A_INVOICE_REJECTED_ID
            )
        )
        assert rejected_transmission is not None
        assert any("message" in entry for entry in rejected_transmission.messages)


async def test_seed_sequences_stay_ahead_of_seeded_sequentials():
    """Emitir un borrador nuevo tras el seed no debe chocar con los secuenciales sembrados."""

    from datetime import date

    from app.core.auth import AuthContext
    from app.schemas.billing import InstallmentInput, InvoiceInput, InvoiceLineInput
    from app.services.billing import create_invoice_draft

    await _reset_schema()
    await seed()

    async with SessionFactory() as session:
        max_seeded_sequential = await session.scalar(
            select(func.max(SalesDocument.sequential)).where(
                SalesDocument.tenant_id == DEMO_TENANT_ID,
                SalesDocument.document_type == "INVOICE",
            )
        )
        assert max_seeded_sequential is not None

        customer_id = await session.scalar(
            select(Party.id).where(Party.tenant_id == DEMO_TENANT_ID)
        )
        context = AuthContext(
            actor_id=str(DEMO_USER_ID),
            actor_type="USER",
            tenant_id=DEMO_TENANT_ID,
            roles=frozenset({"owner"}),
            scopes=frozenset(),
            token_id="test-token",
        )
        draft = await create_invoice_draft(
            session,
            context,
            InvoiceInput(
                customer_id=customer_id,
                establishment_id=TENANT_A_ESTABLISHMENT_ID,
                emission_point_id=TENANT_A_EMISSION_POINT_ID,
                issue_date=date(2026, 1, 20),
                installments=[
                    InstallmentInput(due_date=date(2026, 2, 20), amount=Decimal("1.00"))
                ],
                lines=[
                    InvoiceLineInput(
                        product_id=None,
                        description="Linea post-seed",
                        quantity=Decimal("1.000000"),
                        unit_price=Decimal("1.000000"),
                        discount=Decimal("0.00"),
                        tax_code="0",
                    )
                ],
            ),
        )
        await session.commit()

        assert int(draft.sequential) > int(max_seeded_sequential)

        sequence_row = await session.scalar(
            select(Sequence).where(
                Sequence.tenant_id == DEMO_TENANT_ID,
                Sequence.document_type == "INVOICE",
                Sequence.establishment_id == TENANT_A_ESTABLISHMENT_ID,
                Sequence.emission_point_id == TENANT_A_EMISSION_POINT_ID,
            )
        )
        assert sequence_row is not None
        assert sequence_row.next_value > int(max_seeded_sequential)
