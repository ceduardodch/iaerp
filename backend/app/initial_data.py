import asyncio
import hashlib
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.session import SessionFactory
from app.models.billing import (
    DocumentRelation,
    SalesDocument,
    SalesDocumentLine,
    Sequence,
    SRITransmission,
)
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
from app.services import access_key as access_key_service
from app.services.fiscal_policy import FISCAL_POLICY_V1, LineCalculation, LineInput

SEED_VERSION = "sprint-02-v1"

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

# --- sprint-02-v1: productos, facturas, notas de credito y secuenciales ---
# Tarifa 0% (sri_code "0", ver ADR 0008 tabla 17), fija por tenant.
TENANT_A_ZERO_RATE_TAX_ID = uuid.UUID("1a1a1a1a-1a1a-4a1a-8a1a-1a1a1a1a1a1a")
TENANT_B_ZERO_RATE_TAX_ID = uuid.UUID("1b1b1b1b-1b1b-4b1b-8b1b-1b1b1b1b1b1b")

# Productos con tarifa 0%, adicionales a los productos gravados 15% de
# sprint-01-v1 (TENANT_A_PRODUCT_ID/TENANT_B_PRODUCT_ID).
TENANT_A_PRODUCT_ZERO_RATE_ID = uuid.UUID("20202020-2020-4202-8202-202020202020")
TENANT_B_PRODUCT_ZERO_RATE_ID = uuid.UUID("21212121-2121-4212-8212-212121212121")

# Facturas sintetico por tenant: AUTHORIZED completa, PENDING_AUTHORIZATION
# (recibida, sin autorizar) y REJECTED.
TENANT_A_INVOICE_AUTHORIZED_ID = uuid.UUID("30303030-3030-4303-8303-303030303030")
TENANT_B_INVOICE_AUTHORIZED_ID = uuid.UUID("31313131-3131-4313-8313-313131313131")
TENANT_A_INVOICE_PENDING_ID = uuid.UUID("32323232-3232-4323-8323-323232323232")
TENANT_B_INVOICE_PENDING_ID = uuid.UUID("33333333-3333-4333-8333-333333333233")
TENANT_A_INVOICE_REJECTED_ID = uuid.UUID("34343434-3434-4343-8343-343434343434")
TENANT_B_INVOICE_REJECTED_ID = uuid.UUID("35353535-3535-4353-8353-353535353535")

# Nota de credito AUTHORIZED relacionada con la factura AUTHORIZED del tenant.
TENANT_A_CREDIT_NOTE_AUTHORIZED_ID = uuid.UUID("36363636-3636-4363-8363-363636363636")
TENANT_B_CREDIT_NOTE_AUTHORIZED_ID = uuid.UUID("37373737-3737-4373-8373-373737373737")

# IDs fijos de SRITransmission (una fila por documento emitido en el seed).
TENANT_A_INVOICE_AUTHORIZED_TRANSMISSION_ID = uuid.UUID("38383838-3838-4383-8383-383838383838")
TENANT_B_INVOICE_AUTHORIZED_TRANSMISSION_ID = uuid.UUID("39393939-3939-4393-8393-393939393939")
TENANT_A_INVOICE_PENDING_TRANSMISSION_ID = uuid.UUID("40404040-4040-4404-8404-404040404040")
TENANT_B_INVOICE_PENDING_TRANSMISSION_ID = uuid.UUID("41414141-4141-4414-8414-414141414141")
TENANT_A_INVOICE_REJECTED_TRANSMISSION_ID = uuid.UUID("42424242-4242-4424-8424-424242424242")
TENANT_B_INVOICE_REJECTED_TRANSMISSION_ID = uuid.UUID("43434343-4343-4434-8434-434343434343")
TENANT_A_CREDIT_NOTE_TRANSMISSION_ID = uuid.UUID("44444444-4444-4444-8444-444444444344")
TENANT_B_CREDIT_NOTE_TRANSMISSION_ID = uuid.UUID("45454545-4545-4454-8454-454545454545")

# Ambiente SRI de pruebas (mismo valor que services/billing.py usa siempre en
# este entorno, sin credenciales de produccion).
_SRI_ENVIRONMENT_TEST = access_key_service.ENVIRONMENT_TEST

# Codigos numericos de control fijos (deterministas) para que la clave de
# acceso del seed sea reproducible entre corridas; en produccion
# services/billing.py usa access_key_service.generate_numeric_code() (aleatorio).
_SEED_NUMERIC_CODE_INVOICE_AUTHORIZED = "10000001"
_SEED_NUMERIC_CODE_INVOICE_PENDING = "10000002"
_SEED_NUMERIC_CODE_INVOICE_REJECTED = "10000003"
_SEED_NUMERIC_CODE_CREDIT_NOTE = "10000004"

# Secuenciales sinteticos ya "usados" por el seed, para dejar Sequence.next_value
# consistente (ver _seed_billing / _upsert_sequence_floor).
_SEED_INVOICE_SEQUENTIALS = ("000000001", "000000002", "000000003")
_SEED_CREDIT_NOTE_SEQUENTIALS = ("000000001",)


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


class MastersSeedResult:
    """Ids resueltos por ``_seed_masters`` que ``_seed_billing`` necesita.

    ``tax_category_ids``/``zero_rate_tax_category_ids`` mapean tenant -> id de
    ``TaxCategory`` (15% y 0% respectivamente); evita que ``_seed_billing``
    tenga que reconsultar por ``sri_code`` lo que este modulo ya resolvio.
    """

    def __init__(self) -> None:
        self.tax_category_ids: dict[uuid.UUID, uuid.UUID] = {}
        self.zero_rate_tax_category_ids: dict[uuid.UUID, uuid.UUID] = {}


async def _seed_masters(session: AsyncSession) -> MastersSeedResult:
    result = MastersSeedResult()
    tax_ids = result.tax_category_ids
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

    # sprint-02-v1: tarifa 0% (sri_code "0", ADR 0008 tabla 17), fija por
    # tenant con el mismo patron upsert idempotente que la tarifa 15%.
    zero_rate_tax_ids = result.zero_rate_tax_category_ids
    for tenant_id, tax_id in (
        (DEMO_TENANT_ID, TENANT_A_ZERO_RATE_TAX_ID),
        (SECOND_TENANT_ID, TENANT_B_ZERO_RATE_TAX_ID),
    ):
        tax = await session.get(TaxCategory, tax_id)
        if tax is None:
            tax = await session.scalar(
                select(TaxCategory).where(
                    TaxCategory.tenant_id == tenant_id,
                    TaxCategory.sri_code == "0",
                    TaxCategory.valid_from == date(2024, 4, 1),
                )
            )
            if tax is None:
                tax = TaxCategory(id=tax_id, tenant_id=tenant_id)
                session.add(tax)
        tax.sri_code = "0"
        tax.name = "IVA tarifa 0%"
        tax.rate = Decimal("0.000000")
        tax.valid_from = date(2024, 4, 1)
        tax.active = True
        zero_rate_tax_ids[tenant_id] = tax.id

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

    # sprint-02-v1: producto adicional con tarifa 0%, usado en la factura
    # AUTHORIZED sintetica para mezclar tarifas 15%/0% en el mismo documento.
    for tenant_id, product_id, name, code, price in (
        (
            DEMO_TENANT_ID,
            TENANT_A_PRODUCT_ZERO_RATE_ID,
            "Servicio Norte Tarifa 0",
            "NORTE-002",
            Decimal("5.000000"),
        ),
        (
            SECOND_TENANT_ID,
            TENANT_B_PRODUCT_ZERO_RATE_ID,
            "Servicio Sur Tarifa 0",
            "SUR-002",
            Decimal("8.000000"),
        ),
    ):
        product = await session.get(Product, product_id)
        if product is None:
            product = Product(id=product_id, tenant_id=tenant_id)
            session.add(product)
        product.tax_category_id = zero_rate_tax_ids[tenant_id]
        product.name = name
        product.code = code
        product.unit_price = price
        product.active = True

    return result


# --- sprint-02-v1: dataset de facturacion (E9-01) ---
#
# Deliberadamente NO se llama a services/billing.py::issue_document ni al
# worker workers/sri_transmission.py: ambos dependen de red (MinIO para subir
# artefactos, y el simulador SRI corre solo detras de un router HTTP). El
# seed debe ser determinista y funcionar sin red ni Redis/Celery (ver
# docs/sprints/sprint-02.md, "El dataset se recrea desde cero de forma
# idempotente"). En su lugar, este modulo reconstruye el MISMO resultado que
# esas funciones producirian usando las mismas piezas reales:
# fiscal_policy.calculate_document (nunca montos a mano) y
# access_key.build_access_key (nunca una clave inventada). Por eso
# DocumentArtifact se deja vacio para estos documentos: generar sus bytes
# reales requeriria signxml/reportlab + subida a MinIO, que es justamente lo
# que este seed evita para seguir funcionando sin red.

_INVOICE_DOCUMENT_TYPE = "INVOICE"
_CREDIT_NOTE_DOCUMENT_TYPE = "CREDIT_NOTE"

# Fecha de emision fija (determinista) para todos los documentos del seed;
# posterior a FISCAL_POLICY_V1.valid_from (2024-04-01) y siempre en el pasado
# respecto a "hoy" para no violar la regla de create_invoice_draft (issue_date
# nunca en el futuro).
_SEED_ISSUE_DATE = date(2026, 1, 15)


async def _upsert_sales_document(
    session: AsyncSession,
    *,
    document_id: uuid.UUID,
    tenant_id: uuid.UUID,
    document_type: str,
    establishment_id: uuid.UUID,
    emission_point_id: uuid.UUID,
    sequential: str,
    access_key: str,
    party_id: uuid.UUID,
    issue_date: date,
    status: str,
    subtotal: Decimal,
    tax_total: Decimal,
    total: Decimal,
    reason: str | None = None,
    authorization_number: str | None = None,
    authorized_at: datetime | None = None,
) -> SalesDocument:
    document = await session.get(SalesDocument, document_id)
    if document is None:
        # Defensa adicional: si una fila con la MISMA clave de negocio
        # (tenant, tipo, establecimiento, punto, secuencial) ya existe bajo
        # otro id -- por ejemplo, un borrador de prueba manual dejado en un
        # entorno de desarrollo compartido -- se adopta esa fila en vez de
        # intentar insertar un duplicado que violaria
        # ``uq_sales_documents_tenant_type_establishment_point_sequential``.
        # Mismo patron que ``_seed_masters`` ya usa para ``TaxCategory``.
        document = await session.scalar(
            select(SalesDocument).where(
                SalesDocument.tenant_id == tenant_id,
                SalesDocument.document_type == document_type,
                SalesDocument.establishment_id == establishment_id,
                SalesDocument.emission_point_id == emission_point_id,
                SalesDocument.sequential == sequential,
            )
        )
    if document is None:
        document = SalesDocument(id=document_id, tenant_id=tenant_id)
        session.add(document)
    document.document_type = document_type
    document.establishment_id = establishment_id
    document.emission_point_id = emission_point_id
    document.sequential = sequential
    document.access_key = access_key
    document.party_id = party_id
    document.issue_date = issue_date
    document.status = status
    document.currency = "USD"
    document.subtotal = subtotal
    document.tax_total = tax_total
    document.total = total
    document.fiscal_policy_version = FISCAL_POLICY_V1.version
    document.reason = reason
    document.authorization_number = authorization_number
    document.authorized_at = authorized_at
    await session.flush()
    return document


async def _upsert_sales_document_lines(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    document: SalesDocument,
    line_ids: list[uuid.UUID],
    product_ids: list[uuid.UUID | None],
    descriptions: list[str],
    calculation_lines: list[LineCalculation],
) -> None:
    """Reemplaza las lineas de ``document`` por las calculadas, por posicion.

    Los ids de linea son fijos (ver *_LINE_IDS mas abajo) para que el upsert
    sea idempotente por PK en vez de por (document, line_number): dos corridas
    seguidas actualizan las mismas filas en vez de duplicarlas.
    """

    for index, (line_id, product_id, description, calculated) in enumerate(
        zip(line_ids, product_ids, descriptions, calculation_lines, strict=True),
        start=1,
    ):
        line = await session.get(SalesDocumentLine, line_id)
        if line is None:
            line = SalesDocumentLine(id=line_id, tenant_id=tenant_id)
            session.add(line)
        line.sales_document_id = document.id
        line.line_number = index
        line.product_id = product_id
        line.description = description
        line.quantity = calculated.quantity
        line.unit_price = calculated.unit_price
        line.discount = calculated.discount
        line.base_amount = calculated.base_amount
        line.tax_sri_code = calculated.tax_sri_code
        line.tax_rate = calculated.tax_rate
        line.tax_amount = calculated.tax_amount
    await session.flush()


async def _upsert_sri_transmission(
    session: AsyncSession,
    *,
    transmission_id: uuid.UUID,
    tenant_id: uuid.UUID,
    sales_document_id: uuid.UUID,
    access_key: str,
    status: str,
    messages: list[dict[str, str]],
    attempts: int,
    authorization_number: str | None = None,
    authorized_at: datetime | None = None,
) -> None:
    transmission = await session.get(SRITransmission, transmission_id)
    if transmission is None:
        transmission = SRITransmission(id=transmission_id, tenant_id=tenant_id)
        session.add(transmission)
    transmission.sales_document_id = sales_document_id
    transmission.access_key = access_key
    transmission.status = status
    transmission.messages = messages
    transmission.attempts = attempts
    transmission.authorization_number = authorization_number
    transmission.authorized_at = authorized_at
    await session.flush()


async def _upsert_document_relation(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    credit_note_id: uuid.UUID,
    related_invoice_id: uuid.UUID,
) -> None:
    relation = await session.scalar(
        select(DocumentRelation).where(
            DocumentRelation.tenant_id == tenant_id,
            DocumentRelation.credit_note_id == credit_note_id,
        )
    )
    if relation is None:
        relation = DocumentRelation(tenant_id=tenant_id, credit_note_id=credit_note_id)
        session.add(relation)
    relation.related_invoice_id = related_invoice_id
    await session.flush()


async def _ensure_sequence_floor(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    document_type: str,
    establishment_id: uuid.UUID,
    emission_point_id: uuid.UUID,
    used_sequentials: tuple[str, ...],
) -> None:
    """Deja ``Sequence.next_value`` por encima de los secuenciales ya usados por el seed.

    El seed asigna secuenciales fijos (deterministas, no via
    ``services.billing._reserve_sequential``) para que los documentos sean
    reproducibles entre corridas; esta funcion sincroniza la fila
    ``Sequence`` real para que la PRIMERA emision real posterior al seed
    (``create_invoice_draft``/``create_credit_note``, que si usa
    ``_reserve_sequential`` con ``SELECT ... FOR UPDATE``) nunca choque con
    ellos. Solo sube el valor, nunca lo baja: si un despliegue ya emitio mas
    documentos reales que el techo sintetico del seed, no se retrocede su
    secuencial.
    """

    max_used = max(int(value) for value in used_sequentials)
    required_next_value = max_used + 1

    sequence_row = await session.scalar(
        select(Sequence).where(
            Sequence.tenant_id == tenant_id,
            Sequence.document_type == document_type,
            Sequence.establishment_id == establishment_id,
            Sequence.emission_point_id == emission_point_id,
        )
    )
    if sequence_row is None:
        session.add(
            Sequence(
                tenant_id=tenant_id,
                document_type=document_type,
                establishment_id=establishment_id,
                emission_point_id=emission_point_id,
                next_value=required_next_value,
            )
        )
    elif sequence_row.next_value < required_next_value:
        sequence_row.next_value = required_next_value
    await session.flush()


def _build_access_key(
    *,
    ruc: str,
    document_code: str,
    establishment_code: str,
    emission_point_code: str,
    sequential: str,
    numeric_code: str,
) -> str:
    return access_key_service.build_access_key(
        access_key_service.AccessKeyInput(
            issue_date=_SEED_ISSUE_DATE,
            document_code=document_code,
            ruc=ruc,
            environment=_SRI_ENVIRONMENT_TEST,
            establishment_code=establishment_code,
            emission_point_code=emission_point_code,
            sequential=sequential,
            numeric_code=numeric_code,
        )
    )


async def _seed_tenant_billing(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    tenant_ruc: str,
    establishment_id: uuid.UUID,
    establishment_code: str,
    emission_point_id: uuid.UUID,
    emission_point_code: str,
    party_id: uuid.UUID,
    gravado_tax_category_id: uuid.UUID,
    gravado_product_id: uuid.UUID,
    zero_rate_tax_category_id: uuid.UUID,
    zero_rate_product_id: uuid.UUID,
    invoice_authorized_id: uuid.UUID,
    invoice_pending_id: uuid.UUID,
    invoice_rejected_id: uuid.UUID,
    credit_note_authorized_id: uuid.UUID,
    invoice_authorized_transmission_id: uuid.UUID,
    invoice_pending_transmission_id: uuid.UUID,
    invoice_rejected_transmission_id: uuid.UUID,
    credit_note_transmission_id: uuid.UUID,
) -> None:
    """Crea, para un tenant, el set completo de documentos de sprint-02-v1.

    Reutiliza ``FISCAL_POLICY_V1.calculate_document`` (nunca montos a mano) y
    ``access_key_service.build_access_key`` (nunca una clave inventada) para
    que los totales/clave de acceso sean identicos a los que produciria el
    flujo real de emision.
    """

    gravado_tax = await session.get(TaxCategory, gravado_tax_category_id)
    zero_rate_tax = await session.get(TaxCategory, zero_rate_tax_category_id)
    assert gravado_tax is not None and zero_rate_tax is not None  # noqa: S101

    # --- Factura AUTHORIZED completa: linea gravada 15% con cantidad
    # decimal + descuento, y linea de tarifa 0% (mezcla de tarifas). ---
    authorized_line_inputs = [
        LineInput(
            quantity=Decimal("3.500000"),
            unit_price=Decimal("10.250000"),
            discount=Decimal("2.50"),
            tax_rate=gravado_tax.rate,
            tax_sri_code=gravado_tax.sri_code,
        ),
        LineInput(
            quantity=Decimal("2.000000"),
            unit_price=Decimal("5.000000"),
            discount=Decimal("0.00"),
            tax_rate=zero_rate_tax.rate,
            tax_sri_code=zero_rate_tax.sri_code,
        ),
    ]
    authorized_calculation = FISCAL_POLICY_V1.calculate_document(authorized_line_inputs)
    authorized_sequential = _SEED_INVOICE_SEQUENTIALS[0]
    authorized_access_key = _build_access_key(
        ruc=tenant_ruc,
        document_code=access_key_service.INVOICE_DOCUMENT_CODE,
        establishment_code=establishment_code,
        emission_point_code=emission_point_code,
        sequential=authorized_sequential,
        numeric_code=_SEED_NUMERIC_CODE_INVOICE_AUTHORIZED,
    )
    authorized_invoice = await _upsert_sales_document(
        session,
        document_id=invoice_authorized_id,
        tenant_id=tenant_id,
        document_type=_INVOICE_DOCUMENT_TYPE,
        establishment_id=establishment_id,
        emission_point_id=emission_point_id,
        sequential=authorized_sequential,
        access_key=authorized_access_key,
        party_id=party_id,
        issue_date=_SEED_ISSUE_DATE,
        status="AUTHORIZED",
        subtotal=authorized_calculation.subtotal,
        tax_total=authorized_calculation.tax_total,
        total=authorized_calculation.total,
        authorization_number=f"SEED-AUTH-{authorized_sequential}",
        authorized_at=datetime(2026, 1, 15, 12, 0, tzinfo=UTC),
    )
    await _upsert_sales_document_lines(
        session,
        tenant_id=tenant_id,
        document=authorized_invoice,
        line_ids=[
            uuid.uuid5(invoice_authorized_id, "line-1"),
            uuid.uuid5(invoice_authorized_id, "line-2"),
        ],
        product_ids=[gravado_product_id, zero_rate_product_id],
        descriptions=[
            "Servicio sintetico gravado 15% con descuento",
            "Servicio sintetico tarifa 0%",
        ],
        calculation_lines=authorized_calculation.lines,
    )
    await _upsert_sri_transmission(
        session,
        transmission_id=invoice_authorized_transmission_id,
        tenant_id=tenant_id,
        sales_document_id=authorized_invoice.id,
        access_key=authorized_access_key,
        status="AUTHORIZED",
        messages=[{"message": "Autorizado (fixture sprint-02-v1)"}],
        attempts=2,
        authorization_number=authorized_invoice.authorization_number,
        authorized_at=authorized_invoice.authorized_at,
    )

    # --- Factura PENDING_AUTHORIZATION: recibida por el SRI, sin autorizar,
    # para probar reconciliacion (E4-05). ---
    pending_line_inputs = [
        LineInput(
            quantity=Decimal("1.000000"),
            unit_price=Decimal("10.250000"),
            discount=Decimal("0.00"),
            tax_rate=gravado_tax.rate,
            tax_sri_code=gravado_tax.sri_code,
        ),
    ]
    pending_calculation = FISCAL_POLICY_V1.calculate_document(pending_line_inputs)
    pending_sequential = _SEED_INVOICE_SEQUENTIALS[1]
    pending_access_key = _build_access_key(
        ruc=tenant_ruc,
        document_code=access_key_service.INVOICE_DOCUMENT_CODE,
        establishment_code=establishment_code,
        emission_point_code=emission_point_code,
        sequential=pending_sequential,
        numeric_code=_SEED_NUMERIC_CODE_INVOICE_PENDING,
    )
    pending_invoice = await _upsert_sales_document(
        session,
        document_id=invoice_pending_id,
        tenant_id=tenant_id,
        document_type=_INVOICE_DOCUMENT_TYPE,
        establishment_id=establishment_id,
        emission_point_id=emission_point_id,
        sequential=pending_sequential,
        access_key=pending_access_key,
        party_id=party_id,
        issue_date=_SEED_ISSUE_DATE,
        status="PENDING_AUTHORIZATION",
        subtotal=pending_calculation.subtotal,
        tax_total=pending_calculation.tax_total,
        total=pending_calculation.total,
    )
    await _upsert_sales_document_lines(
        session,
        tenant_id=tenant_id,
        document=pending_invoice,
        line_ids=[uuid.uuid5(invoice_pending_id, "line-1")],
        product_ids=[gravado_product_id],
        descriptions=["Servicio sintetico gravado 15%"],
        calculation_lines=pending_calculation.lines,
    )
    await _upsert_sri_transmission(
        session,
        transmission_id=invoice_pending_transmission_id,
        tenant_id=tenant_id,
        sales_document_id=pending_invoice.id,
        access_key=pending_access_key,
        status="RECEIVED",
        messages=[{"message": "Recibida por el SRI, pendiente de autorizacion (fixture)"}],
        attempts=1,
    )

    # --- Factura REJECTED con mensaje de fixture. ---
    rejected_line_inputs = [
        LineInput(
            quantity=Decimal("1.000000"),
            unit_price=Decimal("10.250000"),
            discount=Decimal("0.00"),
            tax_rate=gravado_tax.rate,
            tax_sri_code=gravado_tax.sri_code,
        ),
    ]
    rejected_calculation = FISCAL_POLICY_V1.calculate_document(rejected_line_inputs)
    rejected_sequential = _SEED_INVOICE_SEQUENTIALS[2]
    rejected_access_key = _build_access_key(
        ruc=tenant_ruc,
        document_code=access_key_service.INVOICE_DOCUMENT_CODE,
        establishment_code=establishment_code,
        emission_point_code=emission_point_code,
        sequential=rejected_sequential,
        numeric_code=_SEED_NUMERIC_CODE_INVOICE_REJECTED,
    )
    rejected_invoice = await _upsert_sales_document(
        session,
        document_id=invoice_rejected_id,
        tenant_id=tenant_id,
        document_type=_INVOICE_DOCUMENT_TYPE,
        establishment_id=establishment_id,
        emission_point_id=emission_point_id,
        sequential=rejected_sequential,
        access_key=rejected_access_key,
        party_id=party_id,
        issue_date=_SEED_ISSUE_DATE,
        status="REJECTED",
        subtotal=rejected_calculation.subtotal,
        tax_total=rejected_calculation.tax_total,
        total=rejected_calculation.total,
    )
    await _upsert_sales_document_lines(
        session,
        tenant_id=tenant_id,
        document=rejected_invoice,
        line_ids=[uuid.uuid5(invoice_rejected_id, "line-1")],
        product_ids=[gravado_product_id],
        descriptions=["Servicio sintetico gravado 15%"],
        calculation_lines=rejected_calculation.lines,
    )
    await _upsert_sri_transmission(
        session,
        transmission_id=invoice_rejected_transmission_id,
        tenant_id=tenant_id,
        sales_document_id=rejected_invoice.id,
        access_key=rejected_access_key,
        status="REJECTED",
        messages=[
            {
                "code": "45",
                "message": "RUC del emisor no se encuentra activo (fixture sprint-02-v1)",
            }
        ],
        attempts=1,
    )

    # --- Nota de credito AUTHORIZED relacionada con la factura AUTHORIZED,
    # con monto menor al total acreditable (el total de la factura). ---
    credit_note_line_inputs = [
        LineInput(
            quantity=Decimal("1.000000"),
            unit_price=authorized_calculation.lines[0].unit_price,
            discount=Decimal("0.00"),
            tax_rate=gravado_tax.rate,
            tax_sri_code=gravado_tax.sri_code,
        ),
    ]
    credit_note_calculation = FISCAL_POLICY_V1.calculate_document(credit_note_line_inputs)
    assert credit_note_calculation.total < authorized_invoice.total  # noqa: S101
    credit_note_sequential = _SEED_CREDIT_NOTE_SEQUENTIALS[0]
    credit_note_access_key = _build_access_key(
        ruc=tenant_ruc,
        document_code=access_key_service.CREDIT_NOTE_DOCUMENT_CODE,
        establishment_code=establishment_code,
        emission_point_code=emission_point_code,
        sequential=credit_note_sequential,
        numeric_code=_SEED_NUMERIC_CODE_CREDIT_NOTE,
    )
    credit_note = await _upsert_sales_document(
        session,
        document_id=credit_note_authorized_id,
        tenant_id=tenant_id,
        document_type=_CREDIT_NOTE_DOCUMENT_TYPE,
        establishment_id=establishment_id,
        emission_point_id=emission_point_id,
        sequential=credit_note_sequential,
        access_key=credit_note_access_key,
        party_id=party_id,
        issue_date=_SEED_ISSUE_DATE,
        status="AUTHORIZED",
        subtotal=credit_note_calculation.subtotal,
        tax_total=credit_note_calculation.tax_total,
        total=credit_note_calculation.total,
        reason="Devolucion parcial sintetica (fixture sprint-02-v1)",
        authorization_number=f"SEED-AUTH-CN-{credit_note_sequential}",
        authorized_at=datetime(2026, 1, 16, 9, 0, tzinfo=UTC),
    )
    await _upsert_sales_document_lines(
        session,
        tenant_id=tenant_id,
        document=credit_note,
        line_ids=[uuid.uuid5(credit_note_authorized_id, "line-1")],
        product_ids=[gravado_product_id],
        descriptions=["Devolucion parcial servicio sintetico gravado 15%"],
        calculation_lines=credit_note_calculation.lines,
    )
    await _upsert_document_relation(
        session,
        tenant_id=tenant_id,
        credit_note_id=credit_note.id,
        related_invoice_id=authorized_invoice.id,
    )
    await _upsert_sri_transmission(
        session,
        transmission_id=credit_note_transmission_id,
        tenant_id=tenant_id,
        sales_document_id=credit_note.id,
        access_key=credit_note_access_key,
        status="AUTHORIZED",
        messages=[{"message": "Autorizado (fixture sprint-02-v1)"}],
        attempts=2,
        authorization_number=credit_note.authorization_number,
        authorized_at=credit_note.authorized_at,
    )

    # --- Sequence: dejar next_value por encima de todos los secuenciales ya
    # usados por este tenant en el seed, para no chocar con una emision real
    # posterior (create_invoice_draft/create_credit_note via _reserve_sequential).
    await _ensure_sequence_floor(
        session,
        tenant_id=tenant_id,
        document_type=_INVOICE_DOCUMENT_TYPE,
        establishment_id=establishment_id,
        emission_point_id=emission_point_id,
        used_sequentials=_SEED_INVOICE_SEQUENTIALS,
    )
    await _ensure_sequence_floor(
        session,
        tenant_id=tenant_id,
        document_type=_CREDIT_NOTE_DOCUMENT_TYPE,
        establishment_id=establishment_id,
        emission_point_id=emission_point_id,
        used_sequentials=_SEED_CREDIT_NOTE_SEQUENTIALS,
    )


async def _seed_billing(session: AsyncSession, masters_result: MastersSeedResult) -> None:
    await _seed_tenant_billing(
        session,
        tenant_id=DEMO_TENANT_ID,
        tenant_ruc="1791234502001",
        establishment_id=TENANT_A_ESTABLISHMENT_ID,
        establishment_code="001",
        emission_point_id=TENANT_A_EMISSION_POINT_ID,
        emission_point_code="001",
        party_id=TENANT_A_PARTY_ID,
        gravado_tax_category_id=masters_result.tax_category_ids[DEMO_TENANT_ID],
        gravado_product_id=TENANT_A_PRODUCT_ID,
        zero_rate_tax_category_id=masters_result.zero_rate_tax_category_ids[DEMO_TENANT_ID],
        zero_rate_product_id=TENANT_A_PRODUCT_ZERO_RATE_ID,
        invoice_authorized_id=TENANT_A_INVOICE_AUTHORIZED_ID,
        invoice_pending_id=TENANT_A_INVOICE_PENDING_ID,
        invoice_rejected_id=TENANT_A_INVOICE_REJECTED_ID,
        credit_note_authorized_id=TENANT_A_CREDIT_NOTE_AUTHORIZED_ID,
        invoice_authorized_transmission_id=TENANT_A_INVOICE_AUTHORIZED_TRANSMISSION_ID,
        invoice_pending_transmission_id=TENANT_A_INVOICE_PENDING_TRANSMISSION_ID,
        invoice_rejected_transmission_id=TENANT_A_INVOICE_REJECTED_TRANSMISSION_ID,
        credit_note_transmission_id=TENANT_A_CREDIT_NOTE_TRANSMISSION_ID,
    )
    await _seed_tenant_billing(
        session,
        tenant_id=SECOND_TENANT_ID,
        tenant_ruc="1795432104001",
        establishment_id=TENANT_B_ESTABLISHMENT_ID,
        establishment_code="001",
        emission_point_id=TENANT_B_EMISSION_POINT_ID,
        emission_point_code="001",
        party_id=TENANT_B_PARTY_ID,
        gravado_tax_category_id=masters_result.tax_category_ids[SECOND_TENANT_ID],
        gravado_product_id=TENANT_B_PRODUCT_ID,
        zero_rate_tax_category_id=masters_result.zero_rate_tax_category_ids[SECOND_TENANT_ID],
        zero_rate_product_id=TENANT_B_PRODUCT_ZERO_RATE_ID,
        invoice_authorized_id=TENANT_B_INVOICE_AUTHORIZED_ID,
        invoice_pending_id=TENANT_B_INVOICE_PENDING_ID,
        invoice_rejected_id=TENANT_B_INVOICE_REJECTED_ID,
        credit_note_authorized_id=TENANT_B_CREDIT_NOTE_AUTHORIZED_ID,
        invoice_authorized_transmission_id=TENANT_B_INVOICE_AUTHORIZED_TRANSMISSION_ID,
        invoice_pending_transmission_id=TENANT_B_INVOICE_PENDING_TRANSMISSION_ID,
        invoice_rejected_transmission_id=TENANT_B_INVOICE_REJECTED_TRANSMISSION_ID,
        credit_note_transmission_id=TENANT_B_CREDIT_NOTE_TRANSMISSION_ID,
    )


async def seed() -> None:
    settings = get_settings()
    if settings.APP_ENV not in {"development", "test"} and not settings.SYNTHETIC_SEED_ENABLED:
        raise RuntimeError(
            "Synthetic seed requires SYNTHETIC_SEED_ENABLED outside development/test"
        )

    async with SessionFactory() as session, session.begin():
        await _seed_platform(session)
        await session.flush()
        masters_result = await _seed_masters(session)
        await session.flush()
        await _seed_billing(session, masters_result)


if __name__ == "__main__":
    asyncio.run(seed())
