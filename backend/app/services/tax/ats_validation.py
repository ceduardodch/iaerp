"""Valida estructura ATS con la copia sellada del esquema oficial del SRI."""

import re
from functools import lru_cache
from pathlib import Path

from lxml import etree


@lru_cache(maxsize=1)
def _schema() -> etree.XMLSchema:
    parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False)
    return etree.XMLSchema(etree.parse(str(Path(__file__).parent / "schemas" / "ats.xsd"), parser))


def validate_ats_xml(xml_bytes: bytes) -> None:
    """Rechaza un ATS inválido antes de guardarlo; no expone sus valores."""
    try:
        parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False)
        root = etree.fromstring(xml_bytes, parser)
        if getattr(root.getroottree().docinfo, "doctype", None):
            raise ValueError("El ATS no admite declaraciones DTD.")
        _schema().assertValid(root)
    except (etree.DocumentInvalid, etree.XMLSyntaxError) as exc:
        error = getattr(exc.error_log, "last_error", None)
        path = error.path if error is not None else None
        field = (path or "/documento").rsplit("/", maxsplit=1)[-1].split("[")[0]
        if re.fullmatch(r"[A-Za-z][A-Za-z0-9]*", field) is None:
            field = "documento"
        line = error.line if error is not None else 1
        raise ValueError(
            f"El ATS no cumple el esquema del SRI: revisa {field} (línea {line})."
        ) from None
