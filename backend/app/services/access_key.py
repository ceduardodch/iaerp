"""Clave de acceso SRI (49 digitos) y su digito verificador modulo 11.

Formato oficial (Ficha Tecnica de Comprobantes Electronicos, Anexo 1):

| Campo             | Digitos | Contenido                                    |
|-------------------|---------|-----------------------------------------------|
| Fecha de emision  | 8       | ``ddmmaaaa``                                   |
| Tipo de comprobante| 2      | ``01`` factura, ``04`` nota de credito         |
| RUC del emisor    | 13      | RUC completo del emisor                        |
| Ambiente          | 1       | ``1`` pruebas, ``2`` produccion                |
| Serie             | 6       | Establecimiento (3) + punto de emision (3)     |
| Secuencial        | 9       | Secuencial del comprobante, con ceros a la izq.|
| Codigo numerico   | 8       | Codigo numerico aleatorio de control           |
| Tipo de emision   | 1       | ``1`` normal (unico soportado por IAERP)       |
| Digito verificador| 1       | Modulo 11 sobre los 48 digitos anteriores      |

Total: 49 digitos. El digito verificador se calcula multiplicando cada digito
(de derecha a izquierda) por pesos ciclicos ``2, 3, 4, 5, 6, 7`` y aplicando:

``resultado = 11 - (suma_ponderada % 11)``

con las excepciones textuales de la ficha tecnica: si ``resultado`` da ``11``
el digito verificador es ``0``; si da ``10`` el digito verificador es ``1``.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import date

# Pesos ciclicos del modulo 11 aplicados de derecha a izquierda sobre los 48
# digitos previos al digito verificador (Ficha Tecnica, Anexo 1).
_MODULUS_11_WEIGHTS = (2, 3, 4, 5, 6, 7)

INVOICE_DOCUMENT_CODE = "01"
CREDIT_NOTE_DOCUMENT_CODE = "04"
_VALID_DOCUMENT_CODES = frozenset({INVOICE_DOCUMENT_CODE, CREDIT_NOTE_DOCUMENT_CODE})

ENVIRONMENT_TEST = "1"
ENVIRONMENT_PRODUCTION = "2"
_VALID_ENVIRONMENTS = frozenset({ENVIRONMENT_TEST, ENVIRONMENT_PRODUCTION})

# Unico tipo de emision soportado por IAERP: emision normal (en linea). La
# emision por contingencia (``2``) queda fuera de alcance (ver sprint-02.md,
# seccion "No incluido").
NORMAL_EMISSION_TYPE = "1"

_ACCESS_KEY_LENGTH = 49
_BASE_LENGTH = _ACCESS_KEY_LENGTH - 1


def compute_verifier_digit(digits: str) -> int:
    """Calcula el digito verificador modulo 11 sobre una cadena de 48 digitos.

    ``digits`` debe contener exactamente los primeros 48 digitos de la clave
    de acceso (fecha, tipo, RUC, ambiente, serie, secuencial, codigo numerico
    y tipo de emision), en ese orden. Lanza ``ValueError`` si la longitud o el
    contenido no son validos.
    """

    if len(digits) != _BASE_LENGTH or not digits.isdigit():
        raise ValueError(f"Expected exactly {_BASE_LENGTH} numeric digits, got {digits!r}")

    weighted_sum = 0
    for offset, char in enumerate(reversed(digits)):
        weight = _MODULUS_11_WEIGHTS[offset % len(_MODULUS_11_WEIGHTS)]
        weighted_sum += int(char) * weight

    remainder = weighted_sum % 11
    result = 11 - remainder
    if result == 11:
        return 0
    if result == 10:
        return 1
    return result


@dataclass(frozen=True)
class AccessKeyInput:
    """Datos crudos necesarios para construir una clave de acceso SRI."""

    issue_date: date
    document_code: str
    ruc: str
    environment: str
    establishment_code: str
    emission_point_code: str
    sequential: str
    numeric_code: str
    emission_type: str = NORMAL_EMISSION_TYPE


def _validate_input(data: AccessKeyInput) -> None:
    if data.document_code not in _VALID_DOCUMENT_CODES:
        raise ValueError(f"Unsupported document code: {data.document_code!r}")
    if data.environment not in _VALID_ENVIRONMENTS:
        raise ValueError(f"Unsupported environment code: {data.environment!r}")
    if not (data.ruc.isdigit() and len(data.ruc) == 13):
        raise ValueError(f"RUC must be exactly 13 digits, got {data.ruc!r}")
    if not (data.establishment_code.isdigit() and len(data.establishment_code) == 3):
        raise ValueError(
            f"Establishment code must be exactly 3 digits, got {data.establishment_code!r}"
        )
    if not (data.emission_point_code.isdigit() and len(data.emission_point_code) == 3):
        raise ValueError(
            f"Emission point code must be exactly 3 digits, got {data.emission_point_code!r}"
        )
    if not (data.sequential.isdigit() and len(data.sequential) == 9):
        raise ValueError(f"Sequential must be exactly 9 digits, got {data.sequential!r}")
    if not (data.numeric_code.isdigit() and len(data.numeric_code) == 8):
        raise ValueError(f"Numeric code must be exactly 8 digits, got {data.numeric_code!r}")
    if data.emission_type != NORMAL_EMISSION_TYPE:
        raise ValueError(f"Unsupported emission type: {data.emission_type!r}")


def build_access_key(data: AccessKeyInput) -> str:
    """Construye la clave de acceso SRI de 49 digitos a partir de sus partes.

    Valida longitudes de cada campo antes de concatenar para fallar temprano
    con un mensaje claro en vez de producir una clave de longitud incorrecta.
    """

    _validate_input(data)

    base = (
        data.issue_date.strftime("%d%m%Y")
        + data.document_code
        + data.ruc
        + data.environment
        + data.establishment_code
        + data.emission_point_code
        + data.sequential
        + data.numeric_code
        + data.emission_type
    )
    verifier = compute_verifier_digit(base)
    access_key = base + str(verifier)
    assert len(access_key) == _ACCESS_KEY_LENGTH  # noqa: S101 - guaranteed by validated field lengths
    return access_key


def generate_numeric_code() -> str:
    """Genera un codigo numerico de control de 8 digitos, no criptografico.

    El codigo numerico es un valor de control anti-duplicidad definido por el
    emisor, no un secreto; ``secrets`` se usa solo por conveniencia para
    obtener una distribucion uniforme sin sesgo de ``random``.
    """

    return f"{secrets.randbelow(100_000_000):08d}"


def verify_access_key(access_key: str) -> bool:
    """Revalida el digito verificador de una clave de acceso ya construida."""

    if len(access_key) != _ACCESS_KEY_LENGTH or not access_key.isdigit():
        return False
    base, declared_verifier = access_key[:_BASE_LENGTH], access_key[_BASE_LENGTH:]
    return compute_verifier_digit(base) == int(declared_verifier)


__all__ = [
    "CREDIT_NOTE_DOCUMENT_CODE",
    "ENVIRONMENT_PRODUCTION",
    "ENVIRONMENT_TEST",
    "INVOICE_DOCUMENT_CODE",
    "NORMAL_EMISSION_TYPE",
    "AccessKeyInput",
    "build_access_key",
    "compute_verifier_digit",
    "generate_numeric_code",
    "verify_access_key",
]
