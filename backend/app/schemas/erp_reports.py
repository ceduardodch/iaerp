"""Contrato tabular de reportes Grok. Las cifras monetarias se transmiten en decimal exacto."""

from datetime import date
from enum import StrEnum
from typing import Self

from pydantic import ConfigDict, Field, model_validator

from app.schemas.base import APIModel


class ReportName(StrEnum):
    CATALOG = "catalog"
    SALES = "sales"
    CREDIT_NOTES = "credit_notes"
    BANK_TRANSACTIONS = "bank_transactions"
    PURCHASES = "purchases"
    RECEIVABLES = "receivables"
    COLLECTIONS = "collections"
    PAYMENTS = "payments"
    CUSTOMERS = "customers"
    SUPPLIERS = "suppliers"
    PRODUCTS = "products"
    CLASSIFICATIONS = "classifications"
    CONTRACTS = "contracts"
    PROPOSALS = "proposals"
    AWS_CUTS = "aws_cuts"
    CRM = "crm"
    CAMPAIGNS = "campaigns"
    INBOX = "inbox"
    NOTIFICATIONS = "notifications"
    PAYROLL = "payroll"
    COMPANY = "company"
    ESTABLISHMENTS = "establishments"


class ERPReportPage(APIModel):
    """Celdas en el orden indicado por columns. Fechas ISO y valores monetarios en texto."""

    model_config = ConfigDict(extra="forbid")

    report: ReportName
    organization_alias: str | None
    company_name: str
    description: str
    date_basis: str | None
    start_date: date | None
    end_date: date | None
    columns: list[str] = Field(min_length=1, max_length=32)
    rows: list[list[str | int | bool | None]] = Field(max_length=100)
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)
    next_offset: int | None


    @model_validator(mode="after")
    def match_columns(self) -> Self:
        if any(len(row) != len(self.columns) for row in self.rows):
            raise ValueError("El número de celdas debe coincidir con las columnas del reporte.")
        return self
