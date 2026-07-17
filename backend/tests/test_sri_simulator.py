"""Pruebas unitarias del simulador SRI (los 6 comportamientos, E4-04).

El escenario se fija explicitamente por clave (nunca al azar), como exige
``docs/sprints/sprint-02.md`` (decision 7), para que las pruebas sean
reproducibles.
"""

import pytest

from app.integrations.sri.simulator import ScenarioStore, SimulatorSRIClient


@pytest.fixture
def store() -> ScenarioStore:
    return ScenarioStore()


@pytest.fixture
def client(store: ScenarioStore) -> SimulatorSRIClient:
    return SimulatorSRIClient(store=store)


ACCESS_KEY = "1" * 49


async def test_default_scenario_receives_then_authorizes_on_second_check(
    client: SimulatorSRIClient,
) -> None:
    """Sin escenario configurado: RECEIVED en recepcion, PENDING luego AUTHORIZED."""

    reception = await client.send_reception(b"<factura/>", ACCESS_KEY)
    assert reception.status == "RECEIVED"

    first_check = await client.check_authorization(ACCESS_KEY)
    assert first_check.status == "PENDING_AUTHORIZATION"
    assert first_check.authorization_number is None

    second_check = await client.check_authorization(ACCESS_KEY)
    assert second_check.status == "AUTHORIZED"
    assert second_check.authorization_number == ACCESS_KEY
    assert second_check.authorized_at is not None


async def test_received_scenario_explicit(
    store: ScenarioStore, client: SimulatorSRIClient
) -> None:
    store.set_scenario(ACCESS_KEY, "RECEIVED")
    reception = await client.send_reception(b"<factura/>", ACCESS_KEY)
    assert reception.status == "RECEIVED"


async def test_returned_scenario_rejects_at_reception_with_reason(
    store: ScenarioStore, client: SimulatorSRIClient
) -> None:
    store.set_scenario(ACCESS_KEY, "RETURNED", reason="RUC invalido")
    reception = await client.send_reception(b"<factura/>", ACCESS_KEY)
    assert reception.status == "RETURNED"
    assert reception.messages[0]["message"] == "RUC invalido"


async def test_returned_scenario_has_nothing_to_authorize(
    store: ScenarioStore, client: SimulatorSRIClient
) -> None:
    store.set_scenario(ACCESS_KEY, "RETURNED")
    await client.send_reception(b"<factura/>", ACCESS_KEY)
    with pytest.raises(ValueError, match="RETURNED at reception"):
        await client.check_authorization(ACCESS_KEY)


async def test_authorized_scenario_authorizes_immediately(
    store: ScenarioStore, client: SimulatorSRIClient
) -> None:
    store.set_scenario(ACCESS_KEY, "AUTHORIZED")
    reception = await client.send_reception(b"<factura/>", ACCESS_KEY)
    assert reception.status == "RECEIVED"

    result = await client.check_authorization(ACCESS_KEY)
    assert result.status == "AUTHORIZED"
    assert result.authorization_number == ACCESS_KEY
    assert result.authorized_at is not None


async def test_not_authorized_scenario(store: ScenarioStore, client: SimulatorSRIClient) -> None:
    store.set_scenario(ACCESS_KEY, "NOT_AUTHORIZED", reason="Error en diferencias")
    await client.send_reception(b"<factura/>", ACCESS_KEY)
    result = await client.check_authorization(ACCESS_KEY)
    assert result.status == "NOT_AUTHORIZED"
    assert result.authorization_number is None
    assert result.messages[0]["message"] == "Error en diferencias"


async def test_timeout_scenario_raises_on_reception(
    store: ScenarioStore, client: SimulatorSRIClient
) -> None:
    store.set_scenario(ACCESS_KEY, "TIMEOUT")
    with pytest.raises(TimeoutError):
        await client.send_reception(b"<factura/>", ACCESS_KEY)


async def test_timeout_scenario_raises_on_authorization_check(
    store: ScenarioStore, client: SimulatorSRIClient
) -> None:
    store.set_scenario(ACCESS_KEY, "RECEIVED")
    await client.send_reception(b"<factura/>", ACCESS_KEY)
    store.set_scenario(ACCESS_KEY, "TIMEOUT")
    with pytest.raises(TimeoutError):
        await client.check_authorization(ACCESS_KEY)


async def test_duplicate_response_scenario_returns_same_authorization_repeatedly(
    store: ScenarioStore, client: SimulatorSRIClient
) -> None:
    """DUPLICATE_RESPONSE: el simulador siempre re-entrega la misma autorizacion.

    Simula que el SRI reenvia la misma respuesta AUTHORIZED ante una segunda
    consulta; el numero de autorizacion nunca cambia entre llamadas.
    """

    store.set_scenario(ACCESS_KEY, "DUPLICATE_RESPONSE")
    await client.send_reception(b"<factura/>", ACCESS_KEY)

    first = await client.check_authorization(ACCESS_KEY)
    second = await client.check_authorization(ACCESS_KEY)
    assert first.status == second.status == "AUTHORIZED"
    assert first.authorization_number == second.authorization_number == ACCESS_KEY


async def test_scenarios_are_isolated_per_access_key(
    store: ScenarioStore, client: SimulatorSRIClient
) -> None:
    other_key = "2" * 49
    store.set_scenario(ACCESS_KEY, "NOT_AUTHORIZED")
    store.set_scenario(other_key, "AUTHORIZED")

    await client.send_reception(b"<factura/>", ACCESS_KEY)
    await client.send_reception(b"<factura/>", other_key)

    result_a = await client.check_authorization(ACCESS_KEY)
    result_b = await client.check_authorization(other_key)
    assert result_a.status == "NOT_AUTHORIZED"
    assert result_b.status == "AUTHORIZED"


async def test_reset_clears_all_scenarios(store: ScenarioStore, client: SimulatorSRIClient) -> None:
    store.set_scenario(ACCESS_KEY, "AUTHORIZED")
    store.reset()
    reception = await client.send_reception(b"<factura/>", ACCESS_KEY)
    # After reset, the default scenario (RECEIVED) applies again.
    assert reception.status == "RECEIVED"
