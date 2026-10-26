"""Formato de identificaciones solo para el ATS; conserva el dato fuente."""

import re
import unicodedata


def normalize_ats_identification(value: str | None) -> str | None:
    """Quita únicamente espacios ASCII y guiones de presentación."""
    if value is None:
        return None
    return value.replace(" ", "").replace("-", "")


def ats_identification_type(value: str | None, *, sale: bool) -> str | None:
    normalized = normalize_ats_identification(value)
    if not normalized or re.fullmatch(r"[A-Za-z0-9]{3,13}", normalized) is None:
        return None
    if normalized == "9999999999999":
        return "07" if sale else None
    if normalized.isascii() and normalized.isdigit():
        if len(normalized) == 13:
            return "04" if sale else "01"
        if len(normalized) == 10:
            return "05" if sale else "02"
    return "06" if sale else "03"


def normalize_ats_name(value: str | None) -> str:
    """Transliteración ASCII solo para denoCli; conserva el nombre maestro."""
    normalized = unicodedata.normalize("NFKD", value or "")
    allowed = "".join(c for c in normalized if c.isascii() and (c.isalnum() or c.isspace()))
    return " ".join(allowed.split())[:500].rstrip()
