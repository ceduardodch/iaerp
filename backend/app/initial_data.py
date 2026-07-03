import asyncio
import hashlib
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.session import SessionFactory
from app.models.masters import (
    EmissionPoint,
    Establishment,
    Party,
    Product,
    Tag,
    TaxCategory,
)
from app.models.platform import (
    AutomationSettings,
    Membership,
    ServiceAccount,
    Tenant,
    User,
)

SEED_VERSION = "sprint-01-v1"

DEMO_TENANT_ID = uuid.UUID("11111111-1111-4111-8111-111111111111")
SECOND_TENANT_ID = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")

DEMO_USER_ID = uuid.UUID("22222222-2222-4222-8222-222222222222")
TENANT_A_USER_ID = uuid.UUID("44444444-4444-4444-8444-444444444444")
TENANT_B_USER_ID = uuid.UUID("55555555-5555-4555-8555-555555555555")
NO_MEMBERSHIP_USER_ID = uuid.UUID("66666666-6666-4666-8666-666666666666")

TENANT_A_SERVICE_ACCOUNT_ID = uuid.UUID("77777777-7777-4777-8777-777777777777")
TENANT_B_SERVICE_ACCOUNT_ID = uuid.UUID("88888888-8888-4888-8888-888888888888")

TENANT_A_TAX_ID = uuid.UUID("99999999-9999-4999-8999-999999999999")
TENANT_B_TAX_ID = uuid.UUID("dddddddd-dddd-4ddd-8ddd-dddddddddddd")
TENANT_A_ESTABLISHMENT_ID = uuid.UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee")
TENANT_B_ESTABLISHMENT_ID = uuid.UUID("ffffffff-ffff-4fff-8fff-ffffffffffff")
TENANT_A_EMISSION_POINT_ID = uuid.UUID("12121212-1212-4212-8212-121212121212")
TENANT_B_EMISSION_POINT_ID = uuid.UUID("13131313-1313-4313-8313-131313131313")
TENANT_A_PARTY_ID = uuid.UUID("14141414-1414-4414-8414-141414141414")
TENANT_B_PARTY_ID = uuid.UUID("15151515-1515-4515-8515-151515151515")
TENANT_A_PRODUCT_ID = uuid.UUID("16161616-1616-4616-8616-161616161616")
TENANT_B_PRODUCT_ID = uuid.UUID("17171717-1717-4717-8717-171717171717")
TENANT_A_TAG_ID = uuid.UUID("18181818-1818-4818-8818-181818181818")
TENANT_B_TAG_ID = uuid.UUID("19191919-1919-4919-8919-191919191919")


def _seed_secret_hash(secret: str, salt_byte: int) -> str:
    """Create reproducible local hashes without storing a usable plaintext secret."""
    salt = bytes([salt_byte]) * 16
    digest = hashlib.scrypt(secret.encode(), salt=salt, n=2**14, r=8, p=1)
    return f"{salt.hex()}:{digest.hex()}"


async def _upsert_tenant(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    ruc: str,
    name: str,
    organization_id: str,
) -> Tenant:
    tenant = await session.get(Tenant, tenant_id)
    if tenant is None:
        tenant = Tenant(id=tenant_id)
        session.add(tenant)
    tenant.ruc = ruc
    tenant.name = name
    tenant.organization_id = organization_id
    tenant.active = True
    return tenant


async def _upsert_user(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    subject: str,
    email: str,
    display_name: str,
) -> User:
    user = await session.get(User, user_id)
    if user is None:
        user = User(id=user_id)
        session.add(user)
    user.external_subject = subject
    user.email = email
    user.display_name = display_name
    user.active = True
    return user


async def _upsert_membership(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    roles: list[str],
) -> None:
    membership = await session.scalar(
        select(Membership).where(
            Membership.tenant_id == tenant_id,
            Membership.user_id == user_id,
        )
    )
    if membership is None:
        membership = Membership(tenant_id=tenant_id, user_id=user_id)
        session.add(membership)
    membership.roles = roles
    membership.active = True


async def _upsert_service_account(
    session: AsyncSession,
    *,
    account_id: uuid.UUID,
    tenant_id: uuid.UUID,
    client_id: str,
    name: str,
    scopes: list[str],
    salt_byte: int,
) -> None:
    account = await session.get(ServiceAccount, account_id)
    if account is None:
        account = ServiceAccount(
            id=account_id,
            tenant_id=tenant_id,
            client_id=client_id,
            secret_hash=_seed_secret_hash(f"{client_id}-local-only", salt_byte),
        )
        session.add(account)
    account.name = name
    account.scopes = scopes
    account.active = True
    account.expires_at = datetime(2035, 1, 1, tzinfo=UTC)


async def _seed_platform(session: AsyncSession) -> None:
    await _upsert_tenant(
        session,
        tenant_id=DEMO_TENANT_ID,
        ruc="1791234502001",
        name="IAERP Demo Norte",
        organization_id="33333333-3333-4333-8333-333333333333",
    )
    await _upsert_tenant(
        session,
        tenant_id=SECOND_TENANT_ID,
        ruc="1795432104001",
        name="IAERP Demo Sur",
        organization_id="abababab-abab-4bab-8bab-abababababab",
    )

    await _upsert_user(
        session,
        user_id=DEMO_USER_ID,
        subject=str(DEMO_USER_ID),
        email="owner@iaerp.local",
        display_name="IAERP Owner",
    )
    await _upsert_user(
        session,
        user_id=TENANT_A_USER_ID,
        subject=str(TENANT_A_USER_ID),
        email="operator.norte@iaerp.local",
        display_name="Operador Norte",
    )
    await _upsert_user(
        session,
        user_id=TENANT_B_USER_ID,
        subject=str(TENANT_B_USER_ID),
        email="accountant.sur@iaerp.local",
        display_name="Contabilidad Sur",
    )
    await _upsert_user(
        session,
        user_id=NO_MEMBERSHIP_USER_ID,
        subject=str(NO_MEMBERSHIP_USER_ID),
        email="without.membership@iaerp.local",
        display_name="Sin Membresia",
    )
    await session.flush()

    await _upsert_membership(
        session,
        tenant_id=DEMO_TENANT_ID,
        user_id=DEMO_USER_ID,
        roles=["owner", "admin"],
    )
    await _upsert_membership(
        session,
        tenant_id=SECOND_TENANT_ID,
        user_id=DEMO_USER_ID,
        roles=["viewer"],
    )
    await _upsert_membership(
        session,
        tenant_id=DEMO_TENANT_ID,
        user_id=TENANT_A_USER_ID,
        roles=["operator"],
    )
    await _upsert_membership(
        session,
        tenant_id=SECOND_TENANT_ID,
        user_id=TENANT_B_USER_ID,
        roles=["accountant"],
    )

    for tenant_id in (DEMO_TENANT_ID, SECOND_TENANT_ID):
        automation = await session.get(AutomationSettings, tenant_id)
        if automation is None:
            automation = AutomationSettings(tenant_id=tenant_id)
            session.add(automation)
        automation.writes_enabled = False
        automation.daily_amount_limit = Decimal("0.00")

    await _upsert_service_account(
        session,
        account_id=TENANT_A_SERVICE_ACCOUNT_ID,
        tenant_id=DEMO_TENANT_ID,
        client_id="iaerp-agent-norte",
        name="Agente Norte",
        scopes=["context:read", "parties:read", "products:read"],
        salt_byte=0x11,
    )
    await _upsert_service_account(
        session,
        account_id=TENANT_B_SERVICE_ACCOUNT_ID,
        tenant_id=SECOND_TENANT_ID,
        client_id="iaerp-agent-sur",
        name="Agente Sur",
        scopes=["context:read", "parties:read"],
        salt_byte=0x22,
    )


async def _seed_masters(session: AsyncSession) -> None:
    tax_ids: dict[uuid.UUID, uuid.UUID] = {}
    for tenant_id, tax_id in (
        (DEMO_TENANT_ID, TENANT_A_TAX_ID),
        (SECOND_TENANT_ID, TENANT_B_TAX_ID),
    ):
        tax = await session.get(TaxCategory, tax_id)
        if tax is None:
            tax = await session.scalar(
                select(TaxCategory).where(
                    TaxCategory.tenant_id == tenant_id,
                    TaxCategory.sri_code == "4",
                    TaxCategory.valid_from == date(2024, 4, 1),
                )
            )
            if tax is None:
                tax = TaxCategory(id=tax_id, tenant_id=tenant_id)
                session.add(tax)
        tax.sri_code = "4"
        tax.name = "IVA 15%"
        tax.rate = Decimal("15.000000")
        tax.valid_from = date(2024, 4, 1)
        tax.active = True
        tax_ids[tenant_id] = tax.id

    for tenant_id, establishment_id, name, address in (
        (
            DEMO_TENANT_ID,
            TENANT_A_ESTABLISHMENT_ID,
            "Matriz Norte",
            "Direccion sintetica norte",
        ),
        (
            SECOND_TENANT_ID,
            TENANT_B_ESTABLISHMENT_ID,
            "Matriz Sur",
            "Direccion sintetica sur",
        ),
    ):
        establishment = await session.get(Establishment, establishment_id)
        if establishment is None:
            establishment = Establishment(id=establishment_id, tenant_id=tenant_id)
            session.add(establishment)
        establishment.code = "001"
        establishment.name = name
        establishment.address = address
        establishment.active = True

    await session.flush()

    for tenant_id, point_id, establishment_id in (
        (DEMO_TENANT_ID, TENANT_A_EMISSION_POINT_ID, TENANT_A_ESTABLISHMENT_ID),
        (SECOND_TENANT_ID, TENANT_B_EMISSION_POINT_ID, TENANT_B_ESTABLISHMENT_ID),
    ):
        point = await session.get(EmissionPoint, point_id)
        if point is None:
            point = EmissionPoint(id=point_id, tenant_id=tenant_id)
            session.add(point)
        point.establishment_id = establishment_id
        point.code = "001"
        point.active = True

    for tenant_id, tag_id, name, color in (
        (DEMO_TENANT_ID, TENANT_A_TAG_ID, "Norte", "#0F766E"),
        (SECOND_TENANT_ID, TENANT_B_TAG_ID, "Sur", "#C2410C"),
    ):
        tag = await session.get(Tag, tag_id)
        if tag is None:
            tag = Tag(id=tag_id, tenant_id=tenant_id)
            session.add(tag)
        tag.name = name
        tag.color = color
        tag.active = True

    for tenant_id, party_id, name, identification in (
        (DEMO_TENANT_ID, TENANT_A_PARTY_ID, "Cliente Sintetico Norte", "1712345678"),
        (SECOND_TENANT_ID, TENANT_B_PARTY_ID, "Proveedor Sintetico Sur", "1798765432"),
    ):
        party = await session.get(Party, party_id)
        if party is None:
            party = Party(id=party_id, tenant_id=tenant_id)
            session.add(party)
        party.name = name
        party.identification_type = "CEDULA"
        party.identification_number = identification
        party.roles = ["CUSTOMER"] if tenant_id == DEMO_TENANT_ID else ["SUPPLIER"]
        party.email = None
        party.phone = None
        party.address = "Dato sintetico"
        party.active = True

    for tenant_id, product_id, name, code, price in (
        (
            DEMO_TENANT_ID,
            TENANT_A_PRODUCT_ID,
            "Servicio Norte",
            "NORTE-001",
            Decimal("10.250000"),
        ),
        (
            SECOND_TENANT_ID,
            TENANT_B_PRODUCT_ID,
            "Servicio Sur",
            "SUR-001",
            Decimal("20.500000"),
        ),
    ):
        product = await session.get(Product, product_id)
        if product is None:
            product = Product(id=product_id, tenant_id=tenant_id)
            session.add(product)
        product.tax_category_id = tax_ids[tenant_id]
        product.name = name
        product.code = code
        product.unit_price = price
        product.active = True


async def seed() -> None:
    settings = get_settings()
    if settings.APP_ENV not in {"development", "test"}:
        raise RuntimeError("Synthetic seed is disabled outside development/test")

    async with SessionFactory() as session, session.begin():
        await _seed_platform(session)
        await session.flush()
        await _seed_masters(session)


if __name__ == "__main__":
    asyncio.run(seed())
