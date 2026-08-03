import pytest

from app.services.billing import _collection_status_from_receivable


@pytest.mark.parametrize(
    ("stored_status", "collection_status"),
    [
        ("OPEN", "OPEN"),
        ("PARTIALLY_PAID", "PARTIAL"),
        ("PAID", "SETTLED"),
        ("VOID", "VOIDED"),
        (None, None),
        ("UNKNOWN", None),
    ],
)
def test_collection_status_does_not_expose_internal_receivable_values(
    stored_status: str | None,
    collection_status: str | None,
) -> None:
    assert _collection_status_from_receivable(stored_status) == collection_status
