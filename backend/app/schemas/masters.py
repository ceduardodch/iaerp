import uuid
from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import EmailStr, Field, field_validator

from app.core.phone import normalize_ecuador_whatsapp
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


class AnalyticClassificationCreate(APIModel):
    code: str = Field(pattern=r"^[A-Z][A-Z0-9_]{1,39}$")
    name: str = Field(min_length=1, max_length=120)
    max_depth: int = Field(default=1, ge=1, le=3)


class AnalyticClassificationRead(AnalyticClassificationCreate):
    id: uuid.UUID
    active: bool


class AnalyticClassificationValueCreate(APIModel):
    parent_id: uuid.UUID | None = None
    code: str = Field(pattern=r"^[A-Z0-9][A-Z0-9_-]{0,39}$")
    name: str = Field(min_length=1, max_length=120)
    color: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")


class AnalyticClassificationValueRead(AnalyticClassificationValueCreate):
    id: uuid.UUID
    classification_id: uuid.UUID
    active: bool


class AnalyticAssignmentsUpdate(APIModel):
    value_ids: list[uuid.UUID] = Field(default_factory=list, max_length=20)


class AnalyticAssignmentRead(APIModel):
    classification_id: uuid.UUID
    classification_code: str
    classification_name: str
    value_id: uuid.UUID
    path: list[dict[str, str]]


class PartyFields(APIModel):
    name: str = Field(min_length=1, max_length=200)
    identification_type: Literal["RUC", "CEDULA", "PASSPORT", "FINAL_CONSUMER"]
    identification_number: str = Field(min_length=1, max_length=30)
    roles: list[Literal["CUSTOMER", "SUPPLIER"]] = Field(min_length=1)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=40)
    address: str | None = Field(default=None, max_length=500)
    payment_terms_days: int | None = Field(default=None, ge=0, le=365)
    expected_iva_withholding_rate: Decimal | None = Field(
        default=None, ge=0, le=100, max_digits=5, decimal_places=2
    )
    expected_income_withholding_rate: Decimal | None = Field(
        default=None, ge=0, le=100, max_digits=5, decimal_places=2
    )
    withholding_profile_valid_from: date | None = None

    @field_validator("roles")
    @classmethod
    def unique_roles(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("roles must be unique")
        return value


class PartyCreate(PartyFields):
    @field_validator("phone")
    @classmethod
    def normalize_whatsapp_phone(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        return normalize_ecuador_whatsapp(value)


class PartyRead(PartyFields):
    # Un prospecto CRM aún no es cliente ni proveedor; por eso puede no tener
    # roles de catálogo hasta que se lo convierta.
    roles: list[Literal["CUSTOMER", "SUPPLIER"]] = Field(default_factory=list)
    id: uuid.UUID


class ProductCreate(APIModel):
    name: str = Field(min_length=1, max_length=200)
    code: str | None = Field(default=None, max_length=80)
    unit_price: Decimal = Field(ge=0, max_digits=18, decimal_places=6)
    tax_category_id: uuid.UUID


class ProductRead(ProductCreate):
    id: uuid.UUID
