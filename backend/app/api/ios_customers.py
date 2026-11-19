"""Tenant-scoped quick customer entry from the native invoice flow."""

import uuid
from typing import Annotated, Literal, Self

from fastapi import APIRouter, Depends, HTTPException
from pydantic import ConfigDict, EmailStr, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthContext
from app.core.ios_catalog_access import (
    CatalogKey,
    CatalogSession,
    check_catalog_membership,
    require_catalog_creator,
)
from app.core.ios_permissions import IOS_CUSTOMER_CREATE
from app.models.masters import Party
from app.schemas.base import APIModel
from app.schemas.masters import PartyCreate, PartyRead
from app.services import masters
from app.services.unit_of_work import execute_idempotent

router = APIRouter()


class CustomerLookup(APIModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    identification_type: Literal["RUC", "CEDULA", "PASSPORT", "FINAL_CONSUMER"]
    identification_number: str = Field(min_length=1, max_length=30)

    @model_validator(mode="after")
    def check_document_format(self) -> Self:
        number = self.identification_number
        length = {"RUC": 13, "CEDULA": 10}.get(self.identification_type)
        if length is not None and not (
            number.isascii() and number.isdigit() and len(number) == length
        ):
            raise ValueError(f"{self.identification_type} requires {length} digits")
        if self.identification_type == "PASSPORT" and len(number) < 3:
            raise ValueError("A passport requires at least three characters")
        if self.identification_type == "FINAL_CONSUMER" and number != "9999999999999":
            raise ValueError("Invalid final consumer identification")
        return self


class CustomerCreate(CustomerLookup):
    name: str = Field(min_length=1, max_length=200)
    email: EmailStr | None = None
    address: str | None = Field(default=None, max_length=500)
    phone: str | None = Field(default=None, max_length=40)
    payment_terms_days: int | None = Field(default=None, ge=0, le=365)

    @field_validator("phone")
    @classmethod
    def normalize_phone(cls, value: str | None) -> str | None:
        return PartyCreate.normalize_whatsapp_phone(value)


Creator = Annotated[
    AuthContext, Depends(require_catalog_creator("parties:read", IOS_CUSTOMER_CREATE))
]


async def _exact_party(
    session: AsyncSession, tenant: uuid.UUID, identity: CustomerLookup
) -> Party | None:
    result = await session.scalars(
        select(Party).where(
            Party.tenant_id == tenant,
            Party.identification_type == identity.identification_type,
            Party.identification_number == identity.identification_number,
        )
    )

    return result.one_or_none()


@router.post("/customers/lookup", response_model=PartyRead)
async def lookup_native_customer(
    data: CustomerLookup, session: CatalogSession, context: Creator
) -> PartyRead:
    party = await _exact_party(session, context.tenant_id, data)
    if party is None:
        raise HTTPException(404, "Customer not found")
    if not party.active or "CUSTOMER" not in party.roles:
        raise HTTPException(409, "Identification already belongs to another catalog entry")
    return PartyRead.model_validate(party)


@router.post("/customers", response_model=PartyRead, status_code=201)
async def create_native_customer(
    data: CustomerCreate,
    session: CatalogSession,
    context: Creator,
    idempotency_key: CatalogKey,
) -> dict[str, object]:
    async def create() -> tuple[str, dict[str, object]]:
        await check_catalog_membership(session, context)
        if await _exact_party(session, context.tenant_id, data) is not None:
            raise HTTPException(409, "Identification already exists in the company")
        fields = PartyCreate.model_validate(
            {**data.model_dump(by_alias=False), "roles": ["CUSTOMER"]}
        )
        party = await masters.create_party(session, context, fields)
        return str(party.id), PartyRead.model_validate(party).model_dump(mode="json", by_alias=True)

    return await execute_idempotent(
        session,
        context=context,
        operation="ios.customers.create",
        idempotency_key=idempotency_key,
        request_payload=data.model_dump(mode="json"),
        action="party.created",
        entity_type="party",
        callback=create,
    )
