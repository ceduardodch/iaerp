"""Modulo tributario Ecuador: evidencia, periodos y documentos fiscales.

Ver ``docs/adrs/0012-tax-module-scope.md``. Reglas que este modelo hace
explicitas:

- La fuente de verdad es evidencia real. ``TaxEvidence`` guarda el archivo
  original con su hash; ``FiscalDocument.is_preliminary`` marca lo que aun no
  tiene respaldo suficiente (por ejemplo un TXT que no separa facturas mixtas).
- Los comprobantes **recibidos** (compras) no existian en IAERP: se construyen
  desde la evidencia importada. Los emitidos propios se enlazan a su
  ``SalesDocument`` sin duplicar la fuente.
- Retencion de IVA y de renta se guardan SIEMPRE como conceptos distintos
  (``FiscalRetention.kind``): el campo 609 del formulario 104 es solo IVA.
- Ninguna clave se persiste: ``TenantTaxProfile.vault_ref`` es una referencia a
  1Password/Bitwarden o variable segura (coherente con el ADR 0005).
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
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

# Obligaciones soportadas. RDEP y ADI se modelan desde ya para no migrar la
# tabla despues, pero su generacion esta fuera del alcance actual (ADR 0012).
OBLIGATION_TYPES = ("IVA", "ATS", "RDEP", "RENTA", "ADI")

# Ciclo de vida de un periodo, tal como lo ve el usuario en pantalla.
PERIOD_STATUSES = (
    "PENDIENTE_DESCARGA",
    "EVIDENCIA_INCOMPLETA",
    "LISTO_REVISAR",
    "LISTO_DECLARAR",
    "DECLARADO",
)


class TenantTaxProfile(TimestampMixin, Base):
    """Perfil tributario de la entidad (1:1 con el tenant).

    Va en tabla aparte para no modificar ``Tenant``, que ya es la entidad fiscal
    (un RUC por tenant, ADR 0007).
    """

    __tablename__ = "tenant_tax_profiles"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
    )
    alias: Mapped[str | None] = mapped_column(String(120))
    person_type: Mapped[str | None] = mapped_column(String(20))
    tax_regime: Mapped[str | None] = mapped_column(String(60))
    obligations: Mapped[list[str]] = mapped_column(JSON, default=list)
    # Referencia al gestor de secretos. NUNCA la clave en si.
    vault_ref: Mapped[str | None] = mapped_column(String(200))

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_tenant_tax_profiles_tenant_id_tenants",
            ondelete="CASCADE",
        ),
    )


class TaxPeriod(UUIDPrimaryKeyMixin, TimestampMixin, TenantEntityMixin, Base):
    """Periodo por entidad, anio, mes y obligacion."""

    __tablename__ = "tax_periods"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_tax_periods_tenant_id"),
        UniqueConstraint(
            "tenant_id",
            "year",
            "month",
            "obligation_type",
            name="uq_tax_periods_tenant_year_month_obligation",
        ),
        CheckConstraint("month BETWEEN 1 AND 12", name="month_valid"),
        CheckConstraint("year BETWEEN 2000 AND 2100", name="year_valid"),
        CheckConstraint(
            "obligation_type IN ('IVA', 'ATS', 'RDEP', 'RENTA', 'ADI')",
            name="obligation_type_valid",
        ),
        CheckConstraint(
            "status IN ('PENDIENTE_DESCARGA', 'EVIDENCIA_INCOMPLETA', "
            "'LISTO_REVISAR', 'LISTO_DECLARAR', 'DECLARADO')",
            name="status_valid",
        ),
        Index("ix_tax_periods_tenant_year_month", "tenant_id", "year", "month"),
    )

    year: Mapped[int] = mapped_column(Integer)
    month: Mapped[int] = mapped_column(Integer)
    obligation_type: Mapped[str] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(30), default="PENDIENTE_DESCARGA")
    due_date: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)


class TaxEvidence(UUIDPrimaryKeyMixin, TimestampMixin, TenantEntityMixin, Base):
    """Archivo original cargado (XML, TXT, PDF o ZIP) con su hash.

    ``sha256`` es unico por tenant: volver a subir el mismo archivo no duplica
    evidencia. El binario vive en MinIO (``object_key``), nunca en la base.
    """

    __tablename__ = "tax_evidence"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_tax_evidence_tenant_id"),
        UniqueConstraint("tenant_id", "sha256", name="uq_tax_evidence_tenant_sha256"),
        CheckConstraint(
            "file_type IN ('XML', 'TXT', 'PDF', 'ZIP', 'OTHER')",
            name="file_type_valid",
        ),
        Index("ix_tax_evidence_tenant_period", "tenant_id", "tax_period_id"),
    )

    # Se resuelve al clasificar el archivo; un ZIP recien subido aun no lo tiene.
    tax_period_id: Mapped[uuid.UUID | None]
    filename: Mapped[str] = mapped_column(String(255))
    file_type: Mapped[str] = mapped_column(String(10))
    object_key: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(Integer)
    # De donde salio: portal SRI, carga manual del usuario o emision propia.
    origin: Mapped[str] = mapped_column(String(30), default="MANUAL")
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Diagnostico de la clasificacion (por que quedo sin periodo, por ejemplo).
    processing_notes: Mapped[str | None] = mapped_column(Text)


class TaxXmlRecoveryJob(UUIDPrimaryKeyMixin, TimestampMixin, TenantEntityMixin, Base):
    """Trabajo durable para completar XML recibidos mediante su clave SRI."""

    __tablename__ = "tax_xml_recovery_jobs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "tax_period_id"],
            ["tax_periods.tenant_id", "tax_periods.id"],
            name="fk_tax_xml_recovery_jobs_tenant_period",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_tax_xml_recovery_jobs_tenant_id"),
        CheckConstraint(
            "status IN ('QUEUED', 'RUNNING', 'COMPLETED')",
            name="tax_xml_recovery_status_valid",
        ),
        Index(
            "ix_tax_xml_recovery_jobs_tenant_period_created",
            "tenant_id",
            "tax_period_id",
            "created_at",
        ),
    )

    tax_period_id: Mapped[uuid.UUID]
    status: Mapped[str] = mapped_column(String(20), default="QUEUED")
    total_count: Mapped[int] = mapped_column(Integer, default=0)
    processed_count: Mapped[int] = mapped_column(Integer, default=0)
    recovered_count: Mapped[int] = mapped_column(Integer, default=0)
    unavailable_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    requested_by_actor_id: Mapped[str] = mapped_column(String(200))
    requested_by_actor_type: Mapped[str] = mapped_column(String(30))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TaxXmlRecoveryItem(UUIDPrimaryKeyMixin, TimestampMixin, TenantEntityMixin, Base):
    """Estado durable de un comprobante dentro de un trabajo de recuperación."""

    __tablename__ = "tax_xml_recovery_items"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "job_id"],
            ["tax_xml_recovery_jobs.tenant_id", "tax_xml_recovery_jobs.id"],
            name="fk_tax_xml_recovery_items_tenant_job",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "fiscal_document_id"],
            ["fiscal_documents.tenant_id", "fiscal_documents.id"],
            name="fk_tax_xml_recovery_items_tenant_document",
        ),
        UniqueConstraint(
            "tenant_id",
            "job_id",
            "fiscal_document_id",
            name="uq_tax_xml_recovery_items_job_document",
        ),
        CheckConstraint(
            "status IN ('PENDING', 'RECOVERED', 'UNAVAILABLE', 'FAILED')",
            name="tax_xml_recovery_item_status_valid",
        ),
        Index(
            "ix_tax_xml_recovery_items_job_status",
            "tenant_id",
            "job_id",
            "status",
        ),
    )

    job_id: Mapped[uuid.UUID]
    fiscal_document_id: Mapped[uuid.UUID]
    status: Mapped[str] = mapped_column(String(20), default="PENDING")


class FiscalDocument(UUIDPrimaryKeyMixin, TimestampMixin, TenantEntityMixin, Base):
    """Comprobante emitido o recibido, canonico para el calculo tributario.

    ``issue_date`` es la fecha REAL de emision del comprobante (la del XML), no
    la carpeta ni el mes de carga: el periodo se asigna con ella.
    """

    __tablename__ = "fiscal_documents"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_fiscal_documents_tenant_id"),
        # Una clave de acceso identifica un comprobante dentro de la entidad.
        UniqueConstraint(
            "tenant_id",
            "access_key",
            name="uq_fiscal_documents_tenant_access_key",
        ),
        CheckConstraint("direction IN ('EMITIDO', 'RECIBIDO')", name="direction_valid"),
        CheckConstraint(
            "doc_type IN ('FACTURA', 'NOTA_CREDITO', 'NOTA_DEBITO', 'RETENCION', 'LIQUIDACION')",
            name="doc_type_valid",
        ),
        Index("ix_fiscal_documents_tenant_issue_date", "tenant_id", "issue_date"),
        Index("ix_fiscal_documents_tenant_period", "tenant_id", "tax_period_id"),
        Index(
            "ix_fiscal_documents_credit_note_source",
            "tenant_id",
            "direction",
            "counterparty_identification",
            "related_document_number",
        ),
    )

    tax_period_id: Mapped[uuid.UUID | None]
    direction: Mapped[str] = mapped_column(String(10))
    doc_type: Mapped[str] = mapped_column(String(20))
    access_key: Mapped[str | None] = mapped_column(String(49))
    authorization_number: Mapped[str | None] = mapped_column(String(49))
    authorized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    issue_date: Mapped[date] = mapped_column(Date)
    establishment_code: Mapped[str | None] = mapped_column(String(3))
    emission_point_code: Mapped[str | None] = mapped_column(String(3))
    sequential: Mapped[str | None] = mapped_column(String(9))
    # Contraparte: emisor si es recibido, cliente si es emitido.
    counterparty_identification: Mapped[str | None] = mapped_column(String(20))
    counterparty_name: Mapped[str | None] = mapped_column(String(300))
    subtotal: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0.00"))
    tax_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0.00"))
    total: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0.00"))
    # Códigos SRI tomados del XML autorizado (p.ej. 20 = sistema financiero).
    # Una lista vacía significa que el documento no respaldó el dato.
    payment_methods: Mapped[list[str]] = mapped_column(JSON, default=list)
    # true cuando el respaldo no permite afirmar el detalle (TXT sin desglose,
    # solo PDF, etc.). El calculo lo reporta como preliminar, no lo adivina.
    is_preliminary: Mapped[bool] = mapped_column(Boolean, default=False)
    # Documento que sustenta esta nota de credito/debito o retencion.
    related_access_key: Mapped[str | None] = mapped_column(String(49))
    related_document_type: Mapped[str | None] = mapped_column(String(20))
    # Numero visible del comprobante modificado (001-001-000000001). El TXT
    # del portal y el XML de una nota lo traen aunque no incluyan la clave de
    # acceso de la factura; se conserva para resolver el enlace sin adivinar.
    related_document_number: Mapped[str | None] = mapped_column(String(30))
    # Emitido propio: enlace al comprobante que IAERP ya genero.
    sales_document_id: Mapped[uuid.UUID | None]
    evidence_id: Mapped[uuid.UUID | None]


class FiscalDocumentTax(UUIDPrimaryKeyMixin, TenantEntityMixin, Base):
    """Desglose de impuestos de un comprobante.

    Se guarda una fila por combinacion de codigo/tarifa para poder separar
    compras con IVA, 0%, exentas y no objeto sin recalcular desde el total.
    """

    __tablename__ = "fiscal_document_taxes"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "fiscal_document_id"],
            ["fiscal_documents.tenant_id", "fiscal_documents.id"],
            name="fk_fiscal_document_taxes_tenant_fiscal_document",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_fiscal_document_taxes_tenant_id"),
        CheckConstraint(
            "tax_bracket IN ('GRAVADO', 'TARIFA_CERO', 'EXENTO', 'NO_OBJETO')",
            name="tax_bracket_valid",
        ),
        Index(
            "ix_fiscal_document_taxes_document",
            "tenant_id",
            "fiscal_document_id",
        ),
    )

    fiscal_document_id: Mapped[uuid.UUID]
    # Codigo de porcentaje IVA del SRI (tal como viene en el XML).
    sri_tax_code: Mapped[str] = mapped_column(String(10))
    tax_bracket: Mapped[str] = mapped_column(String(20))
    rate: Mapped[Decimal] = mapped_column(Numeric(9, 6), default=Decimal("0"))
    base_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0.00"))
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0.00"))


class FiscalRetention(UUIDPrimaryKeyMixin, TimestampMixin, TenantEntityMixin, Base):
    """Retencion de IVA o de renta.

    ``kind`` las mantiene separadas a proposito: la retencion de IVA alimenta el
    campo 609 del IVA mensual y la de renta se reserva para renta anual.
    """

    __tablename__ = "fiscal_retentions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "fiscal_document_id"],
            ["fiscal_documents.tenant_id", "fiscal_documents.id"],
            name="fk_fiscal_retentions_tenant_fiscal_document",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_fiscal_retentions_tenant_id"),
        CheckConstraint("kind IN ('IVA', 'RENTA')", name="kind_valid"),
        Index("ix_fiscal_retentions_tenant_document", "tenant_id", "fiscal_document_id"),
    )

    # Comprobante de retencion que la contiene.
    fiscal_document_id: Mapped[uuid.UUID]
    kind: Mapped[str] = mapped_column(String(10))
    sri_code: Mapped[str] = mapped_column(String(10))
    percentage: Mapped[Decimal] = mapped_column(Numeric(9, 4), default=Decimal("0"))
    base_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0.00"))
    retained_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0.00"))
    # Documento sustento (la factura sobre la que se retuvo).
    supporting_access_key: Mapped[str | None] = mapped_column(String(49))
    supporting_document_number: Mapped[str | None] = mapped_column(String(30))


class TaxFormFieldMap(UUIDPrimaryKeyMixin, TimestampMixin, TenantEntityMixin, Base):
    """Mapa configurable de campos del formulario (104 u otros).

    Los codigos NO se codifican en el motor de calculo: cambian por formulario y
    por vigencia. ``is_paste`` distingue lo que el usuario copia al formulario de
    lo que el SRI autocalcula (solo control).
    """

    __tablename__ = "tax_form_field_maps"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_tax_form_field_maps_tenant_id"),
        UniqueConstraint(
            "tenant_id",
            "form_code",
            "field_code",
            "valid_from",
            name="uq_tax_form_field_maps_tenant_form_field_valid",
        ),
        Index("ix_tax_form_field_maps_tenant_form", "tenant_id", "form_code"),
    )

    form_code: Mapped[str] = mapped_column(String(10))
    field_code: Mapped[str] = mapped_column(String(10))
    label: Mapped[str] = mapped_column(String(200))
    # Clave del resultado del motor de IVA que alimenta este campo.
    source_key: Mapped[str] = mapped_column(String(60))
    is_paste: Mapped[bool] = mapped_column(Boolean, default=True)
    valid_from: Mapped[date] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)


class TaxReturnDraft(UUIDPrimaryKeyMixin, TimestampMixin, TenantEntityMixin, Base):
    """Borrador de declaracion con los valores calculados y su trazabilidad."""

    __tablename__ = "tax_return_drafts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "tax_period_id"],
            ["tax_periods.tenant_id", "tax_periods.id"],
            name="fk_tax_return_drafts_tenant_tax_period",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_tax_return_drafts_tenant_id"),
        UniqueConstraint(
            "tenant_id",
            "tax_period_id",
            "form_code",
            name="uq_tax_return_drafts_tenant_period_form",
        ),
    )

    tax_period_id: Mapped[uuid.UUID]
    form_code: Mapped[str] = mapped_column(String(10), default="104")
    # {campo: {value, is_paste, sources: [...], is_preliminary}}
    fields: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="BORRADOR")
    observations: Mapped[str | None] = mapped_column(Text)


class TaxAnnex(UUIDPrimaryKeyMixin, TimestampMixin, TenantEntityMixin, Base):
    """Anexo generado (ATS, RDEP, ADI) con su XML y ZIP en MinIO."""

    __tablename__ = "tax_annexes"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "tax_period_id"],
            ["tax_periods.tenant_id", "tax_periods.id"],
            name="fk_tax_annexes_tenant_tax_period",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_tax_annexes_tenant_id"),
        CheckConstraint(
            "annex_type IN ('ATS', 'RDEP', 'ADI')",
            name="annex_type_valid",
        ),
        CheckConstraint(
            "status IN ('GENERADO', 'VALIDADO', 'RECHAZADO', 'ENTREGADO')",
            name="status_valid",
        ),
        Index("ix_tax_annexes_tenant_period", "tenant_id", "tax_period_id"),
    )

    tax_period_id: Mapped[uuid.UUID]
    annex_type: Mapped[str] = mapped_column(String(10))
    xml_object_key: Mapped[str | None] = mapped_column(Text)
    zip_object_key: Mapped[str | None] = mapped_column(Text)
    xml_sha256: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), default="GENERADO")
    version: Mapped[int] = mapped_column(Integer, default=1)


class SRIValidationIssue(UUIDPrimaryKeyMixin, TimestampMixin, TenantEntityMixin, Base):
    """Error o advertencia devuelto por el SRI, con su ubicacion exacta.

    Permite ubicar el comprobante, proponer la correccion y regenerar el anexo
    sin perder el historial de lo que ya se corrigio.
    """

    __tablename__ = "sri_validation_issues"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_sri_validation_issues_tenant_id"),
        CheckConstraint("severity IN ('ERROR', 'ADVERTENCIA')", name="severity_valid"),
        CheckConstraint("status IN ('PENDIENTE', 'CORREGIDO')", name="status_valid"),
        Index("ix_sri_validation_issues_tenant_annex", "tenant_id", "tax_annex_id"),
    )

    tax_annex_id: Mapped[uuid.UUID | None]
    fiscal_document_id: Mapped[uuid.UUID | None]
    severity: Mapped[str] = mapped_column(String(20), default="ERROR")
    line_number: Mapped[int | None] = mapped_column(Integer)
    column_number: Mapped[int | None] = mapped_column(Integer)
    message: Mapped[str] = mapped_column(Text)
    suggested_fix: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="PENDIENTE")


class TaxTask(UUIDPrimaryKeyMixin, TimestampMixin, TenantEntityMixin, Base):
    """Pendiente del asistente tributario.

    ``requires_approval`` deja explicito que ninguna automatizacion envia,
    entrega ni paga por su cuenta (ADR 0012).
    """

    __tablename__ = "tax_tasks"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_tax_tasks_tenant_id"),
        CheckConstraint(
            "status IN ('PENDIENTE', 'EN_PROCESO', 'HECHO', 'DESCARTADO')",
            name="status_valid",
        ),
        Index("ix_tax_tasks_tenant_status", "tenant_id", "status"),
    )

    tax_period_id: Mapped[uuid.UUID | None]
    task_type: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(200))
    detail: Mapped[str | None] = mapped_column(Text)
    due_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="PENDIENTE")
    requires_approval: Mapped[bool] = mapped_column(Boolean, default=True)


__all__ = [
    "FiscalDocument",
    "FiscalDocumentTax",
    "FiscalRetention",
    "OBLIGATION_TYPES",
    "PERIOD_STATUSES",
    "SRIValidationIssue",
    "TaxAnnex",
    "TaxEvidence",
    "TaxFormFieldMap",
    "TaxPeriod",
    "TaxReturnDraft",
    "TaxTask",
    "TenantTaxProfile",
]
