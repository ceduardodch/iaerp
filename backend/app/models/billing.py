import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.masters import TenantEntityMixin


class SalesDocument(UUIDPrimaryKeyMixin, TimestampMixin, TenantEntityMixin, Base):
    """Cabecera comun de factura y nota de credito.

    Estados: DRAFT -> READY -> SIGNED -> RECEIVED -> AUTHORIZED, con estados
    alternos REJECTED, PENDING_AUTHORIZATION, FAILED y VOIDED (ver
    docs/03-domain-model.md). Una factura AUTHORIZED es inmutable.
    """

    __tablename__ = "sales_documents"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "establishment_id"],
            ["establishments.tenant_id", "establishments.id"],
            name="fk_sales_documents_tenant_establishment",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "emission_point_id"],
            ["emission_points.tenant_id", "emission_points.id"],
            name="fk_sales_documents_tenant_emission_point",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "party_id"],
            ["parties.tenant_id", "parties.id"],
            name="fk_sales_documents_tenant_party",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_sales_documents_tenant_id"),
        UniqueConstraint(
            "tenant_id",
            "document_type",
            "establishment_id",
            "emission_point_id",
            "sequential",
            name="uq_sales_documents_tenant_type_establishment_point_sequential",
        ),
        UniqueConstraint("access_key", name="uq_sales_documents_access_key"),
        Index("ix_sales_documents_tenant_status", "tenant_id", "status"),
        Index("ix_sales_documents_tenant_issue_date", "tenant_id", "issue_date"),
    )

    document_type: Mapped[str] = mapped_column(String(20))
    establishment_id: Mapped[uuid.UUID]
    emission_point_id: Mapped[uuid.UUID]
    # Secuencial SRI de 9 digitos, guardado como texto con padding para
    # conservar los ceros a la izquierda exigidos por el contrato.
    sequential: Mapped[str] = mapped_column(String(9))
    # Clave de acceso SRI: 49 digitos, unica globalmente cuando no es nula;
    # queda nula mientras el documento es DRAFT (se calcula al emitir).
    access_key: Mapped[str | None] = mapped_column(String(49))
    party_id: Mapped[uuid.UUID]
    issue_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(30), default="DRAFT")
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    subtotal: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    tax_total: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    total: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    fiscal_policy_version: Mapped[str] = mapped_column(String(20))
    reason: Mapped[str | None] = mapped_column(String(500))
    # Numero y fecha de autorizacion SRI; se llenan solo cuando el worker de
    # transmision (workers/sri_transmission.py) recibe AUTHORIZED.
    authorization_number: Mapped[str | None] = mapped_column(String(49))
    authorized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SalesDocumentLine(UUIDPrimaryKeyMixin, TenantEntityMixin, Base):
    """Linea de un ``SalesDocument`` con el impuesto ya cuantizado.

    ``tax_sri_code``/``tax_rate`` son una copia (snapshot) de la tarifa vigente
    al momento del calculo: un cambio posterior en ``TaxCategory`` nunca debe
    alterar un documento ya emitido.
    """

    __tablename__ = "sales_document_lines"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "sales_document_id"],
            ["sales_documents.tenant_id", "sales_documents.id"],
            name="fk_sales_document_lines_tenant_sales_document",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "product_id"],
            ["products.tenant_id", "products.id"],
            name="fk_sales_document_lines_tenant_product",
        ),
        Index("ix_sales_document_lines_document", "tenant_id", "sales_document_id"),
    )

    sales_document_id: Mapped[uuid.UUID]
    line_number: Mapped[int] = mapped_column(Integer)
    product_id: Mapped[uuid.UUID | None]
    description: Mapped[str] = mapped_column(String(500))
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    discount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    base_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    tax_sri_code: Mapped[str] = mapped_column(String(20))
    tax_rate: Mapped[Decimal] = mapped_column(Numeric(9, 6))
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))


class SalesDocumentInstallment(UUIDPrimaryKeyMixin, TenantEntityMixin, Base):
    """Plan de pago propuesto de una factura (``InvoiceInput.installments``).

    Sprint 3 Fase 2: antes de esta fase ``InvoiceInput.installments`` se
    aceptaba y descartaba (ver docstring historico de
    ``schemas/billing.py::InstallmentInput``); esta tabla persiste esas cuotas
    tal como el cliente las declaro en el borrador, para que
    ``workers/receivables.py::handle_invoice_authorized`` materialice
    ``ReceivableInstallment`` reales (fecha y monto) en vez de colapsar
    siempre a una cuota de contado por el total. Solo aplica a facturas
    (``document_type == INVOICE``); una nota de credito nunca tiene filas
    aqui. La suma de ``amount`` de las filas de una factura es siempre igual
    a ``SalesDocument.total`` -- verificado por el creador
    (``services/billing.py::create_invoice_draft``), no por un ``CHECK`` de
    base de datos (agregacion entre filas, mismo razonamiento que
    ``ReceivableInstallment``).
    """

    __tablename__ = "sales_document_installments"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "sales_document_id"],
            ["sales_documents.tenant_id", "sales_documents.id"],
            name="fk_sales_document_installments_tenant_sales_document",
        ),
        UniqueConstraint(
            "tenant_id",
            "sales_document_id",
            "sequence",
            name="uq_sales_document_installments_tenant_document_sequence",
        ),
        CheckConstraint(
            "amount > 0", name="ck_sales_document_installments_amount_positive"
        ),
        Index(
            "ix_sales_document_installments_document",
            "tenant_id",
            "sales_document_id",
        ),
    )

    sales_document_id: Mapped[uuid.UUID]
    sequence: Mapped[int] = mapped_column(Integer)
    due_date: Mapped[date] = mapped_column(Date)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))


class DocumentRelation(UUIDPrimaryKeyMixin, TenantEntityMixin, Base):
    """Relacion nota de credito -> factura autorizada que compensa."""

    __tablename__ = "document_relations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "credit_note_id"],
            ["sales_documents.tenant_id", "sales_documents.id"],
            name="fk_document_relations_tenant_credit_note",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "related_invoice_id"],
            ["sales_documents.tenant_id", "sales_documents.id"],
            name="fk_document_relations_tenant_related_invoice",
        ),
        UniqueConstraint(
            "tenant_id",
            "credit_note_id",
            name="uq_document_relations_tenant_credit_note",
        ),
        Index("ix_document_relations_related_invoice", "tenant_id", "related_invoice_id"),
    )

    credit_note_id: Mapped[uuid.UUID]
    related_invoice_id: Mapped[uuid.UUID]


class Sequence(UUIDPrimaryKeyMixin, TenantEntityMixin, Base):
    """Siguiente valor de secuencial por tenant/establecimiento/punto/tipo.

    La reserva atomica ocurre con ``SELECT ... FOR UPDATE`` sobre esta fila
    dentro de la misma transaccion que crea el ``SalesDocument`` (ver
    ``services/billing.py``); el ``UniqueConstraint`` en ``SalesDocument`` es
    la defensa adicional contra una fuga del lock.
    """

    __tablename__ = "sequences"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "establishment_id"],
            ["establishments.tenant_id", "establishments.id"],
            name="fk_sequences_tenant_establishment",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "emission_point_id"],
            ["emission_points.tenant_id", "emission_points.id"],
            name="fk_sequences_tenant_emission_point",
        ),
        UniqueConstraint(
            "tenant_id",
            "document_type",
            "establishment_id",
            "emission_point_id",
            name="uq_sequences_tenant_type_establishment_point",
        ),
    )

    document_type: Mapped[str] = mapped_column(String(20))
    establishment_id: Mapped[uuid.UUID]
    emission_point_id: Mapped[uuid.UUID]
    next_value: Mapped[int] = mapped_column(Integer, default=1)


class SRITransmission(UUIDPrimaryKeyMixin, TimestampMixin, TenantEntityMixin, Base):
    """Cada intento de transmision al SRI (o al simulador), con su respuesta.

    Estados: ``PENDING`` (creada, aun no transmitida) -> ``RECEIVED`` (el SRI
    acepto el XML a validacion) -> ``PENDING_AUTHORIZATION`` (se agendo
    consulta de autorizacion) -> ``AUTHORIZED``/``NOT_AUTHORIZED``/``REJECTED``
    (estados terminales) o ``FAILED`` (error tecnico, reintentable). La
    reconciliacion de E4-05 (``services/billing.py``/``workers/sri_transmission.py``)
    consulta por ``access_key`` antes de transmitir de nuevo: una clave con una
    fila en ``RECEIVED``/``PENDING_AUTHORIZATION``/``AUTHORIZED`` nunca vuelve a
    llamar ``send_reception``, solo ``check_authorization``.
    """

    __tablename__ = "sri_transmissions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "sales_document_id"],
            ["sales_documents.tenant_id", "sales_documents.id"],
            name="fk_sri_transmissions_tenant_sales_document",
        ),
        Index("ix_sri_transmissions_document", "tenant_id", "sales_document_id"),
        Index("ix_sri_transmissions_access_key", "access_key"),
    )

    sales_document_id: Mapped[uuid.UUID]
    access_key: Mapped[str] = mapped_column(String(49))
    status: Mapped[str] = mapped_column(String(30))
    messages: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    authorization_number: Mapped[str | None] = mapped_column(String(49))
    authorized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DocumentArtifact(UUIDPrimaryKeyMixin, TimestampMixin, TenantEntityMixin, Base):
    """XML firmado o RIDE PDF de un ``SalesDocument``, con checksum y version.

    Usado por fases posteriores (E4-03/E4-06); definido junto al resto del
    modelo de facturacion por la misma razon que ``SRITransmission``.
    """

    __tablename__ = "document_artifacts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "sales_document_id"],
            ["sales_documents.tenant_id", "sales_documents.id"],
            name="fk_document_artifacts_tenant_sales_document",
        ),
        UniqueConstraint(
            "tenant_id",
            "sales_document_id",
            "artifact_type",
            "version",
            name="uq_document_artifacts_tenant_document_type_version",
        ),
        Index("ix_document_artifacts_document", "tenant_id", "sales_document_id"),
    )

    sales_document_id: Mapped[uuid.UUID]
    artifact_type: Mapped[str] = mapped_column(String(20))
    object_key: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64))
    version: Mapped[int] = mapped_column(Integer, default=1)
