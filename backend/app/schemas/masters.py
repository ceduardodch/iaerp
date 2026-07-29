import uuid
from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import EmailStr, Field, field_validator

from app.schemas.base import APIModel


class EstablishmentCreate(APIModel):
    code: str = Field(pattern=r"^[0-9]{3}$")
    name: str = Field(min_length=1, max_length=120)
    address: str = Field(min_length=1, max_length=500)


class EstablishmentRead(EstablishmentCreate):
    id: uuid.UUID
    active: bool


class EmissionPointCreate(APIModel):
    establishment_id: uuid.UUID
    code: str = Field(pattern=r"^[0-9]{3}$")


class EmissionPointRead(EmissionPointCreate):
    id: uuid.UUID
    active: bool


class TaxCategoryRead(APIModel):
    id: uuid.UUID
    sri_code: str
    name: str
    rate: Decimal
    valid_from: date
    valid_to: date | None
    active: bool


class TaxCategoryCreate(APIModel):
    """Nueva categoría tributaria con vigencia fiscal explícita.

    Las categorías no se corrigen sobre registros históricos: si cambia una
    tarifa se registra una nueva vigencia para conservar la trazabilidad de
    los productos y comprobantes ya emitidos.
    """

    sri_code: str = Field(min_length=1, max_length=20)
    name: str = Field(min_length=1, max_length=120)
    rate: Decimal = Field(ge=0, le=100, max_digits=9, decimal_places=6)
    valid_from: date


class TagCreate(APIModel):
    name: str = Field(min_length=1, max_length=64)
    color: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")


class TagRead(TagCreate):
    id: uuid.UUID
    active: bool


class PartyCreate(APIModel):
    name: str = Field(min_length=1, max_length=200)
    identification_type: Literal["RUC", "CEDULA", "PASSPORT", "FINAL_CONSUMER"]
    identification_number: str = Field(min_length=1, max_length=30)
    roles: list[Literal["CUSTOMER", "SUPPLIER"]] = Field(min_length=1)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=40)
    address: str | None = Field(default=None, max_length=500)
    payment_terms_days: int | None = Field(default=None, ge=0, le=365)

    @field_validator("roles")
    @classmethod
    def unique_roles(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("roles must be unique")
        return value


class PartyRead(PartyCreate):
    id: uuid.UUID


class ProductCreate(APIModel):
    name: str = Field(min_length=1, max_length=200)
    code: str | None = Field(default=None, max_length=80)
    unit_price: Decimal = Field(ge=0, max_digits=18, decimal_places=6)
    tax_category_id: uuid.UUID


class ProductRead(ProductCreate):
    id: uuid.UUID
