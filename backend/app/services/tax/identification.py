"""Equivalencias seguras de identificación tributaria ecuatoriana."""


def _is_ascii_digits(value: str, *, length: int) -> bool:
    return len(value) == length and value.isascii() and value.isdigit()


def is_valid_natural_person_ruc(value: str) -> bool:
    """Valida un RUC de persona natural formado por cédula válida más ``001``."""
    if not _is_ascii_digits(value, length=13) or not value.endswith("001"):
        return False
    cedula = value[:10]
    if int(cedula[2]) > 5:
        return False
    total = 0
    for index, digit_text in enumerate(cedula[:9]):
        digit = int(digit_text)
        product = digit * (2 if index % 2 == 0 else 1)
        total += product - 9 if product > 9 else product
    check_digit = (10 - (total % 10)) % 10
    return check_digit == int(cedula[9])


def receiver_matches_tenant(receiver_identification: str | None, tenant_ruc: str) -> bool:
    """Acepta el RUC exacto o su cédula base solo para una persona natural."""
    if receiver_identification == tenant_ruc:
        return True
    return (
        receiver_identification is not None
        and is_valid_natural_person_ruc(tenant_ruc)
        and receiver_identification == tenant_ruc[:10]
    )
