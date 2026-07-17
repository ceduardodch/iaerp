import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import Field, field_validator

from app.schemas.base import APIModel

DocumentType = Literal["INVOICE", "CREDIT_NOTE"]
ArtifactType = Literal["xml-signed", "ride-pdf"]
DocumentStatus = Literal[
    "DRAFT",
    "READY",
    "SIGNED",
    "RECEIVED",
    "PENDING_AUTHORIZATION",
    "AUTHORIZED",
    "NOT_AUTHORIZED",
    "REJECTED",
    "FAILED",
    "VOIDED",
]


class InstallmentInput(APIModel):
    """Cuota de cobro planeada declarada en el borrador de factura.

    Sprint 3 Fase 2: se persiste tal cual llega en
    ``SalesDocumentInstallment`` (``services/billing.py::create_invoice_draft``),
    validando que la suma de todas las cuotas sea exactamente igual al
    ``total`` recalculado del documento. Cuando la factura es autorizada,
    ``workers/receivables.py::handle_invoice_authorized`` materializa estas
    mismas cuotas como ``ReceivableInstallment`` reales (misma fecha y
    monto), cayendo a una unica cuota de contado solo si el documento no
    tiene cuotas persistidas (defensa para documentos de datos antiguos).
    """

    due_date: date
    amount: Decimal = Field(gt=0, max_digits=18, decimal_places=2)


class InvoiceLineInput(APIModel):
    product_id: uuid.UUID | None = None
    description: str = Field(min_length=1)
    quantity: Decimal = Field(gt=0, max_digits=12, decimal_places=6)
    unit_price: Decimal = Field(ge=0, max_digits=12, decimal_places=6)
    discount: Decimal = Field(default=Decimal("0.00"), ge=0, max_digits=16, decimal_places=2)
    tax_code: str = Field(min_length=1)


class InvoiceInput(APIModel):
    customer_id: uuid.UUID
    establishment_id: uuid.UUID
    emission_point_id: uuid.UUID
    issue_date: date
    # Plan de pago opcional. Si se omite (o llega vacio), el backend crea una
    # sola cuota al contado por el total con vencimiento en la fecha de
    # emision. Si se declara, la suma debe cuadrar exactamente con el total
    # recalculado por el backend. Esto permite que un cliente simple (la UI,
    # que nunca calcula el total) emita sin declarar cuotas, y que un plan de
    # pago multiple siga siendo posible.
    installments: list[InstallmentInput] = Field(default_factory=list)
    lines: list[InvoiceLineInput] = Field(min_length=1)


class CreditNoteInput(APIModel):
    invoice_id: uuid.UUID
    reason: str = Field(min_length=3)
    lines: list[InvoiceLineInput] = Field(min_length=1)


class SalesDocumentLineRead(APIModel):
    id: uuid.UUID
    line_number: int
    product_id: uuid.UUID | None
    description: str
    quantity: Decimal
    unit_price: Decimal
    discount: Decimal
    base_amount: Decimal
    tax_code: str
    tax_rate: Decimal
    tax_amount: Decimal


SRITransmissionStatus = Literal[
    "PENDING",
    "RECEIVED",
    "PENDING_AUTHORIZATION",
    "AUTHORIZED",
    "NOT_AUTHORIZED",
    "REJECTED",
    "FAILED",
]


class SRITransmissionRead(APIModel):
    """Ultimo intento de transmision SRI de un ``SalesDocument``.

    ``message`` es el primer mensaje legible del ultimo intento (si el SRI o
    el simulador devolvieron alguno); ``lastAttemptAt`` reutiliza
    ``updated_at`` de la fila mas reciente, que se toca en cada intento.
    """

    status: SRITransmissionStatus
    message: str | None
    last_attempt_at: datetime
    authorization_number: str | None


class SalesDocumentRead(APIModel):
    id: uuid.UUID
    type: DocumentType
    status: DocumentStatus
    sequential: str
    issue_date: date
    access_key: str | None
    subtotal: Decimal
    tax: Decimal
    total: Decimal
    currency: str
    party_id: uuid.UUID
    establishment_id: uuid.UUID
    emission_point_id: uuid.UUID
    fiscal_policy_version: str
    reason: str | None
    authorization_number: str | None = None
    authorized_at: datetime | None = None
    sri_transmission: SRITransmissionRead | None = None
    lines: list[SalesDocumentLineRead] = Field(default_factory=list)

    @field_validator("sequential")
    @classmethod
    def sequential_is_nine_digits(cls, value: str) -> str:
        if not value.isdigit() or len(value) != 9:
            raise ValueError("sequential must be a 9-digit string")
        return value


class DocumentArtifactRead(APIModel):
    """Metadatos de un artefacto (XML firmado o RIDE PDF) de un ``SalesDocument``.

    Nunca incluye la URL de descarga: esa se emite solo bajo demanda, con
    corta duracion, en ``GET /invoices/{id}/artifacts/{artifactId}/download``
    (ver ``services/storage.py`` y ADR 0005).
    """

    id: uuid.UUID
    artifact_type: ArtifactType
    sha256: str
    version: int
    created_at: datetime


class ArtifactDownloadRead(APIModel):
    download_url: str
    expires_in_seconds: int
