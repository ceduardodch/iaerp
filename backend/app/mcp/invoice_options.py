"""Minimal tenant catalog required to prepare an invoice via MCP."""

from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthContext
from app.schemas.base import APIModel
from app.services import masters


class InvoiceEmissionPoint(APIModel):
    id: UUID
    code: str
    establishment_id: UUID
    establishment_code: str
    establishment_name: str


class InvoiceTaxCategory(APIModel):
    id: UUID
    sri_code: str
    name: str
    rate: Decimal


class InvoiceOptions(APIModel):
    emission_points: list[InvoiceEmissionPoint]
    tax_categories: list[InvoiceTaxCategory]


async def read_invoice_options(
    session: AsyncSession, context: AuthContext, issue_date: date
) -> InvoiceOptions:
    establishments = {item.id: item for item in await masters.list_establishments(session, context)}
    points = await masters.list_emission_points(session, context)
    emission_points = [
        InvoiceEmissionPoint(
            id=point.id,
            code=point.code,
            establishment_id=establishment.id,
            establishment_code=establishment.code,
            establishment_name=establishment.name,
        )
        for point in points
        if (establishment := establishments.get(point.establishment_id)) is not None
    ]
    categories = await masters.list_tax_categories(session, context)
    # The issuer resolves each code to the newest active version. Offer it
    # only when that exact version also covers the requested invoice date.
    latest = {item.sri_code: item for item in sorted(categories, key=lambda item: item.valid_from)}
    return InvoiceOptions(
        emission_points=sorted(emission_points, key=lambda p: (p.establishment_code, p.code)),
        tax_categories=[
            InvoiceTaxCategory.model_validate(item)
            for _, item in sorted(latest.items())
            if item.valid_from <= issue_date
            and (item.valid_to is None or issue_date <= item.valid_to)
        ],
    )
