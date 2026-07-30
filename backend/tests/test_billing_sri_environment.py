import pytest
from fastapi import HTTPException

from app.services.billing import _validate_sri_environment_alignment


def test_soap_emission_requires_same_organization_and_transmission_environment() -> None:
    with pytest.raises(HTTPException) as error:
        _validate_sri_environment_alignment(
            fiscal_environment="1",
            transmission_mode="soap",
            transmission_environment="2",
        )

    assert error.value.status_code == 409
    assert "environment 1" in str(error.value.detail)
    assert "environment 2" in str(error.value.detail)


@pytest.mark.parametrize("mode", ["simulator", "soap"])
def test_matching_environment_is_accepted(mode: str) -> None:
    _validate_sri_environment_alignment(
        fiscal_environment="2",
        transmission_mode=mode,
        transmission_environment="2",
    )
