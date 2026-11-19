"""Create a catalog product for an invoice without exposing general product administration."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthContext
from app.core.ios_catalog_access import (
    CatalogKey,
    CatalogSession,
    check_catalog_membership,
    require_catalog_creator,
)
from app.core.ios_permissions import IOS_PRODUCT_CREATE
from app.core.timezones import today_in_fiscal_timezone
from app.models.masters import Product, TaxCategory
from app.schemas.base import APIModel
from app.schemas.masters import ProductCreate, ProductRead
from app.services import masters
from app.services.unit_of_work import execute_idempotent

router = APIRouter()
Creator = Annotated[
    AuthContext, Depends(require_catalog_creator("products:read", IOS_PRODUCT_CREATE))
]


class ProductLookup(APIModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    code: str = Field(min_length=1, max_length=80)


class NativeProductCreate(ProductCreate):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    # Required for exact recovery after a timeout or a second attempt from another device.
    code: str = Field(min_length=1, max_length=80)


async def _exact_product(session: AsyncSession, tenant: uuid.UUID, code: str) -> Product | None:
    rows = await session.scalars(
        select(Product).where(Product.tenant_id == tenant, Product.code == code)
    )
    return rows.one_or_none()


@router.post("/catalog-products/lookup", response_model=ProductRead)
async def lookup_native_product(
    data: ProductLookup, session: CatalogSession, context: Creator
) -> ProductRead:
    product = await _exact_product(session, context.tenant_id, data.code)
    if product is None:
        raise HTTPException(404, "Product not found")
    if not product.active:
        raise HTTPException(409, "The product with this code is inactive")
    return ProductRead.model_validate(product)


@router.post("/catalog-products", response_model=ProductRead, status_code=201)
async def create_native_product(
    data: NativeProductCreate,
    session: CatalogSession,
    context: Creator,
    idempotency_key: CatalogKey,
) -> dict[str, object]:
    async def create() -> tuple[str, dict[str, object]]:
        await check_catalog_membership(session, context)
        if await _exact_product(session, context.tenant_id, data.code) is not None:
            raise HTTPException(409, "Product code already exists in the company")
        tax = await session.scalar(
            select(TaxCategory)
            .where(
                TaxCategory.id == data.tax_category_id,
                TaxCategory.tenant_id == context.tenant_id,
                TaxCategory.active.is_(True),
            )
            .with_for_update()
        )
        if tax is None:
            raise HTTPException(404, "Tax category not found")
        today = today_in_fiscal_timezone()
        if tax.valid_from > today or (tax.valid_to is not None and tax.valid_to < today):
            raise HTTPException(422, "Tax category is not valid on the current fiscal date")
        product = await masters.create_product(session, context, data)
        return str(product.id), ProductRead.model_validate(product).model_dump(
            mode="json", by_alias=True
        )

    return await execute_idempotent(
        session,
        context=context,
        operation="ios.catalog_products.create",
        idempotency_key=idempotency_key,
        request_payload=data.model_dump(mode="json"),
        action="product.created",
        entity_type="product",
        callback=create,
    )
