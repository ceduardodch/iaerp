import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import Field

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


class FiscalSettingsUpdate(APIModel):
    sri_environment: Literal["1", "2"]


class FiscalSettingsRead(FiscalSettingsUpdate):
    certificate_configured: bool
    certificate_fingerprint_sha256: str | None = None
    certificate_subject: str | None = None
    certificate_valid_from: datetime | None = None
    certificate_valid_to: datetime | None = None
    certificate_uploaded_at: datetime | None = None


class SigningCertificateRead(FiscalSettingsRead):
    message: str


class MembershipRead(APIModel):
    tenant_id: uuid.UUID
    organization_id: str | None
    ruc: str
    tenant_name: str
    roles: list[str]
    active: bool


class ServiceAccountCreate(APIModel):
    name: str = Field(min_length=3, max_length=120)
    scopes: list[str] = Field(min_length=1)
    expires_at: datetime


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
