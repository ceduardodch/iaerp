import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class TenantEntityMixin:
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True)


class Establishment(UUIDPrimaryKeyMixin, TimestampMixin, TenantEntityMixin, Base):
    __tablename__ = "establishments"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_establishments_tenant_id"),
        UniqueConstraint("tenant_id", "code", name="uq_establishments_tenant_code"),
    )

    code: Mapped[str] = mapped_column(String(3))
    name: Mapped[str] = mapped_column(String(120))
    address: Mapped[str] = mapped_column(String(500))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class EmissionPoint(UUIDPrimaryKeyMixin, TimestampMixin, TenantEntityMixin, Base):
    __tablename__ = "emission_points"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "establishment_id"],
            ["establishments.tenant_id", "establishments.id"],
            name="fk_emission_points_tenant_establishment",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_emission_points_tenant_id"),
        UniqueConstraint(
            "tenant_id",
            "establishment_id",
            "code",
            name="uq_emission_points_tenant_establishment_code",
        ),
    )

    establishment_id: Mapped[uuid.UUID]
    code: Mapped[str] = mapped_column(String(3))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class TaxCategory(UUIDPrimaryKeyMixin, TimestampMixin, TenantEntityMixin, Base):
    __tablename__ = "tax_categories"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_tax_categories_tenant_id"),
        UniqueConstraint(
            "tenant_id",
            "sri_code",
            "valid_from",
            name="uq_tax_categories_tenant_code_valid",
        ),
    )

    sri_code: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(120))
    rate: Mapped[Decimal] = mapped_column(Numeric(9, 6))
    valid_from: Mapped[date] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Tag(UUIDPrimaryKeyMixin, TimestampMixin, TenantEntityMixin, Base):
    __tablename__ = "tags"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_tags_tenant_id"),
        UniqueConstraint("tenant_id", "name", name="uq_tags_tenant_name"),
    )

    name: Mapped[str] = mapped_column(String(64))
    color: Mapped[str] = mapped_column(String(7))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Party(UUIDPrimaryKeyMixin, TimestampMixin, TenantEntityMixin, Base):
    __tablename__ = "parties"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_parties_tenant_id"),
        UniqueConstraint(
            "tenant_id",
            "identification_type",
            "identification_number",
            name="uq_parties_tenant_identification",
        ),
        Index("ix_parties_tenant_name", "tenant_id", "name"),
    )

    name: Mapped[str] = mapped_column(String(200))
    identification_type: Mapped[str] = mapped_column(String(30))
    identification_number: Mapped[str] = mapped_column(String(30))
    roles: Mapped[list[str]] = mapped_column(JSON)
    email: Mapped[str | None] = mapped_column(String(320))
    phone: Mapped[str | None] = mapped_column(String(40))
    address: Mapped[str | None] = mapped_column(String(500))
    consent_opt_out: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Product(UUIDPrimaryKeyMixin, TimestampMixin, TenantEntityMixin, Base):
    __tablename__ = "products"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "tax_category_id"],
            ["tax_categories.tenant_id", "tax_categories.id"],
            name="fk_products_tenant_tax_category",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_products_tenant_id"),
        UniqueConstraint("tenant_id", "code", name="uq_products_tenant_code"),
        Index("ix_products_tenant_name", "tenant_id", "name"),
    )

    name: Mapped[str] = mapped_column(String(200))
    code: Mapped[str | None] = mapped_column(String(80))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    tax_category_id: Mapped[uuid.UUID]
    active: Mapped[bool] = mapped_column(Boolean, default=True)
