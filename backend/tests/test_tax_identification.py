from app.services.tax.identification import (
    is_valid_natural_person_ruc,
    receiver_matches_tenant,
)


def test_receiver_matches_exact_ruc() -> None:
    assert receiver_matches_tenant("1799999999001", "1799999999001")


def test_receiver_matches_cedula_for_valid_natural_person_ruc() -> None:
    assert is_valid_natural_person_ruc("1712345675001")
    assert receiver_matches_tenant("1712345675", "1712345675001")


def test_receiver_rejects_cedula_prefix_for_company_ruc() -> None:
    assert not is_valid_natural_person_ruc("1799999999001")
    assert not receiver_matches_tenant("1799999999", "1799999999001")


def test_receiver_rejects_invalid_natural_person_ruc_and_other_cedula() -> None:
    assert not is_valid_natural_person_ruc("1712345676001")
    assert not receiver_matches_tenant("1712345675", "1712345676001")
    assert not receiver_matches_tenant("1712345676", "1712345675001")
