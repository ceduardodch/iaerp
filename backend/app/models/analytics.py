import uuid

from sqlalchemy import JSON, Boolean, ForeignKeyConstraint, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.masters import TenantEntityMixin


class AnalyticClassification(UUIDPrimaryKeyMixin, TimestampMixin, TenantEntityMixin, Base):
    """Catálogo analítico configurable por tenant.

    ``max_depth`` solo define cuántos niveles puede tener el catálogo. No
    obliga a que un documento complete todos los niveles.
    """

    __tablename__ = "analytic_classifications"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_analytic_classifications_tenant_id"),
        UniqueConstraint("tenant_id", "code", name="uq_analytic_classifications_tenant_code"),
    )

    code: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(120))
    max_depth: Mapped[int] = mapped_column(Integer, default=1)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class AnalyticClassificationValue(UUIDPrimaryKeyMixin, TimestampMixin, TenantEntityMixin, Base):
    """Valor controlado de una clasificación y, opcionalmente, su padre."""

    __tablename__ = "analytic_classification_values"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "classification_id"],
            ["analytic_classifications.tenant_id", "analytic_classifications.id"],
            name="fk_analytic_values_tenant_classification",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "parent_id"],
            ["analytic_classification_values.tenant_id", "analytic_classification_values.id"],
            name="fk_analytic_values_tenant_parent",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_analytic_values_tenant_id"),
        UniqueConstraint(
            "tenant_id",
            "classification_id",
            "code",
            name="uq_analytic_values_tenant_classification_code",
        ),
        Index(
            "ix_analytic_values_tenant_classification_parent",
            "tenant_id",
            "classification_id",
            "parent_id",
        ),
    )

    classification_id: Mapped[uuid.UUID]
    parent_id: Mapped[uuid.UUID | None]
    code: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(120))
    color: Mapped[str | None] = mapped_column(String(7))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class AnalyticAssignment(UUIDPrimaryKeyMixin, TimestampMixin, TenantEntityMixin, Base):
    """Clasificación aplicada a una entidad de negocio.

    ``target_type`` evita una tabla distinta por cada módulo sin confiar en el
    cliente: cada caso de uso valida que el ``target_id`` pertenece al tenant.
    ``path_snapshot`` conserva los nombres jerárquicos que el operador vio al
    clasificar, incluso si el catálogo cambia luego.
    """

    __tablename__ = "analytic_assignments"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "classification_id"],
            ["analytic_classifications.tenant_id", "analytic_classifications.id"],
            name="fk_analytic_assignments_tenant_classification",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "value_id"],
            ["analytic_classification_values.tenant_id", "analytic_classification_values.id"],
            name="fk_analytic_assignments_tenant_value",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_analytic_assignments_tenant_id"),
        UniqueConstraint(
            "tenant_id",
            "target_type",
            "target_id",
            "classification_id",
            name="uq_analytic_assignments_target_classification",
        ),
        Index("ix_analytic_assignments_target", "tenant_id", "target_type", "target_id"),
        Index("ix_analytic_assignments_value", "tenant_id", "value_id"),
    )

    classification_id: Mapped[uuid.UUID]
    value_id: Mapped[uuid.UUID]
    target_type: Mapped[str] = mapped_column(String(40))
    target_id: Mapped[uuid.UUID]
    path_snapshot: Mapped[list[dict[str, str]]] = mapped_column(JSON)
