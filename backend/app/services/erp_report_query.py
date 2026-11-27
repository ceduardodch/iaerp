"""Una proyección fija, restringida al tenant y ordenada para paginación."""

from dataclasses import dataclass
from typing import Any

from sqlalchemy import Select
from sqlalchemy.orm import InstrumentedAttribute
from sqlalchemy.sql.elements import ColumnElement


@dataclass(frozen=True)
class ReportQuery:
    statement: Select[Any]
    description: str
    date_basis: str | None = None
    date_column: ColumnElement[Any] | InstrumentedAttribute[Any] | None = None
