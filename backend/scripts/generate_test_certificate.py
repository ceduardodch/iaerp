"""Genera un certificado RSA autofirmado de PRUEBA para firmar XML XAdES-BES.

Uso: ``uv run python scripts/generate_test_certificate.py``

Produce un archivo ``.p12`` (clave privada + certificado autofirmado) cifrado
con la passphrase de ``IAERP_SIGNING_CERT_PASSWORD`` (o el valor de desarrollo
por defecto si la variable no esta definida) en ``backend/certs/``. Este
certificado es SOLO para dev/test: nunca reemplaza al certificado real emitido
por una entidad de certificacion acreditada que el SRI exige en produccion
(fuera de alcance de Sprint 2, ver docs/sprints/sprint-02.md "No incluido").

El archivo generado NUNCA se versiona: ``backend/certs/`` y ``*.p12``/``*.pfx``
estan en ``.gitignore`` (raiz del repo). ``signing.py`` invoca este script
automaticamente en dev/test si el archivo no existe todavia.
"""

from __future__ import annotations

import os
from pathlib import Path

from app.services.dev_certificate import generate_self_signed_p12

# Nunca usar este valor por defecto fuera de dev/test: es publico en el
# repositorio y solo protege un certificado que tampoco es valido ante el SRI.
_DEFAULT_DEV_PASSWORD = "iaerp-local-only-test-cert"  # noqa: S105 - dev-only default  # pragma: allowlist secret

DEFAULT_CERT_DIR = Path(__file__).resolve().parent.parent / "certs"
DEFAULT_CERT_FILENAME = "test-signing.p12"


def _resolve_password() -> bytes:
    return os.environ.get("IAERP_SIGNING_CERT_PASSWORD", _DEFAULT_DEV_PASSWORD).encode("utf-8")


def main() -> None:
    output_path = DEFAULT_CERT_DIR / DEFAULT_CERT_FILENAME
    password = _resolve_password()
    written_path = generate_self_signed_p12(output_path=output_path, password=password)
    print(f"Generated dev-only signing certificate at {written_path}")


if __name__ == "__main__":
    main()
