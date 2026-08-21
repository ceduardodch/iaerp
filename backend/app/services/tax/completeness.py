"""Reglas comunes para decidir si un comprobante respalda el cálculo fiscal."""

from __future__ import annotations

import uuid
from collections.abc import Iterable

from app.models.tax import FiscalDocument

TAX_DETAIL_DOCUMENT_TYPES = frozenset(
    {"FACTURA", "NOTA_CREDITO", "NOTA_DEBITO", "LIQUIDACION"}
)


def missing_tax_detail_document_ids(
    documents: Iterable[FiscalDocument],
    tax_document_ids: set[uuid.UUID],
) -> set[uuid.UUID]:
    """Devuelve documentos que necesitan bases por tarifa y no las tienen."""
    return {
        document.id
        for document in documents
        if document.doc_type in TAX_DETAIL_DOCUMENT_TYPES
        and document.id not in tax_document_ids
    }


__all__ = ["TAX_DETAIL_DOCUMENT_TYPES", "missing_tax_detail_document_ids"]
