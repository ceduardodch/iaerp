"""Normalización de teléfonos para WhatsApp de clientes en Ecuador."""

from __future__ import annotations

import re

ECUADOR_WHATSAPP_PATTERN = re.compile(r"^\+5939\d{8}$")
ECUADOR_WHATSAPP_EXAMPLE = "+593991041297"


def normalize_ecuador_whatsapp(value: str) -> str:
    """Normaliza un móvil ecuatoriano y devuelve formato E.164.

    Acepta entradas comunes de usuario como ``0991041297`` o ``593991041297``,
    pero persiste y usa exclusivamente ``+593991041297``.
    """
    normalized = re.sub(r"[\s().-]", "", value.strip())
    if normalized.startswith("09") and len(normalized) == 10:
        normalized = "+593" + normalized[1:]
    elif normalized.startswith("593"):
        normalized = "+" + normalized
    if not ECUADOR_WHATSAPP_PATTERN.fullmatch(normalized):
        raise ValueError(f"WhatsApp phone must use {ECUADOR_WHATSAPP_EXAMPLE}")
    return normalized
