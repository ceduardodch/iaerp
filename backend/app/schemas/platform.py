import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import EmailStr, Field, field_validator

from app.schemas.base import APIModel


class DevTokenRequest(APIModel):
    email: str
    tenant_id: uuid.UUID
    scopes: list[str] = Field(default_factory=list)


class TokenResponse(APIModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class TenantContextRead(APIModel):
    tenant_id: uuid.UUID
    ruc: str
    name: str
    roles: list[str]
    scopes: list[str]
    automation_writes_enabled: bool
    default_payment_terms_days: int


class OrganizationProfileUpdate(APIModel):
    name: str = Field(min_length=1, max_length=200)
    ruc: str = Field(pattern=r"^[0-9]{13}$")
    default_payment_terms_days: int = Field(default=0, ge=0, le=365)


class OrganizationProfileRead(OrganizationProfileUpdate):
    tenant_id: uuid.UUID


class FiscalSettingsUpdate(APIModel):
    sri_environment: Literal["1", "2"]


class FiscalSettingsRead(FiscalSettingsUpdate):
    electronic_invoicing_provider_name: str
    electronic_invoicing_provider_ruc: str
    certificate_configured: bool
    ride_logo_configured: bool
    certificate_fingerprint_sha256: str | None = None
    certificate_subject: str | None = None
    certificate_valid_from: datetime | None = None
    certificate_valid_to: datetime | None = None
    certificate_uploaded_at: datetime | None = None


class InvoiceEmailTemplateUpdate(APIModel):
    subject: str = Field(min_length=1, max_length=500)
    body: str = Field(min_length=1, max_length=5000)
    from_address: EmailStr | None = None
    from_name: str | None = Field(default=None, min_length=1, max_length=200)

    @field_validator("from_name")
    @classmethod
    def validate_from_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if "\r" in normalized or "\n" in normalized:
            raise ValueError("Sender name cannot contain line breaks")
        return normalized


class InvoiceEmailTemplateRead(InvoiceEmailTemplateUpdate):
    available_variables: list[str]


class SigningCertificateRead(FiscalSettingsRead):
    message: str


class MembershipRead(APIModel):
    tenant_id: uuid.UUID
    organization_id: str | None
    ruc: str
    tenant_name: str
    roles: list[str]
    active: bool


SERVICE_ACCOUNT_ALLOWED_SCOPES = frozenset(
    {
        "context:read",
        "parties:read",
        "parties:write",
        "products:read",
        "products:write",
        "invoices:read",
        "invoices:write",
        "invoices:issue",
        "credit-notes:issue",
        "receivables:read",
        "receivables:write",
        "receivables:notify",
        "payables:read",
        "payables:write",
        "payables:extract",
        "analytics:read",
        "analytics:write",
        "leads:read",
        "leads:write",
        "leads:capture",
        "payroll:read",
        "payroll:write",
    }
)


class ServiceAccountCreate(APIModel):
    name: str = Field(min_length=3, max_length=120)
    scopes: list[str] = Field(min_length=1, max_length=32)
    expires_at: datetime

    @field_validator("scopes")
    @classmethod
    def scopes_are_allowed(cls, value: list[str]) -> list[str]:
        unsupported = set(value).difference(SERVICE_ACCOUNT_ALLOWED_SCOPES)
        if unsupported:
            raise ValueError(f"unsupported service account scopes: {sorted(unsupported)}")
        return sorted(set(value))


class ServiceAccountRead(APIModel):
    id: uuid.UUID
    client_id: str
    name: str
    scopes: list[str]
    active: bool
    expires_at: datetime


class ServiceAccountCreated(APIModel):
    account: ServiceAccountRead
    client_secret: str


class AutomationSettingsUpdate(APIModel):
    writes_enabled: bool
    daily_amount_limit: Decimal = Field(ge=0, max_digits=18, decimal_places=2)


class AutomationSettingsRead(AutomationSettingsUpdate):
    updated_at: datetime


class OperationRead(APIModel):
    operation_id: uuid.UUID
    status: str
    correlation_id: str
    created_at: datetime
    expires_at: datetime
    result: dict[str, object] | None = None
    error: dict[str, object] | None = None


class ErrorRead(APIModel):
    code: str
    message: str
    correlation_id: str


class OpsFailureRead(APIModel):
    """Fallo operativo terminal, tal como quedo en ``dead_letters``.

    ``correlation_id`` y ``aggregate_*`` viven dentro del ``payload`` que
    escriben los workers, no en columnas propias; se exponen aplanados porque
    sin el correlation ID no hay forma de cruzar el fallo con los logs de la
    request que lo origino.
    """

    id: uuid.UUID
    source_type: str
    source_id: uuid.UUID
    event_type: str
    error: str
    attempts: int
    status: str
    correlation_id: str | None = None
    aggregate_type: str | None = None
    aggregate_id: str | None = None
    created_at: datetime
    resolved_at: datetime | None = None
