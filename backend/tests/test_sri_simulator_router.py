"""Pruebas del router de administracion ``/sri-sim`` (montado en app/main.py).

``SRI_SIMULATOR_ENABLED`` es ``True`` por defecto en development/test (ver
``conftest.py``: ``APP_ENV=test``), por lo que el router siempre esta montado
durante la suite. Estas pruebas fijan un escenario via HTTP y verifican que el
``SimulatorSRIClient`` (que comparte el mismo store singleton) lo respeta.
"""

from app.integrations.sri.simulator import get_store


async def test_set_scenario_via_http_is_visible_to_the_shared_store(client) -> None:
    access_key = "9" * 49
    get_store().reset()

    response = await client.post(
        "/sri-sim/scenarios",
        json={"accessKey": access_key, "behavior": "NOT_AUTHORIZED", "reason": "Prueba"},
    )
    assert response.status_code == 204

    from app.integrations.sri.simulator import SimulatorSRIClient

    sri_client = SimulatorSRIClient()
    await sri_client.send_reception(b"<factura/>", access_key)
    result = await sri_client.check_authorization(access_key)
    assert result.status == "NOT_AUTHORIZED"
    assert result.messages[0]["message"] == "Prueba"


async def test_get_scenario_returns_404_when_not_configured(client) -> None:
    get_store().reset()
    response = await client.get(f"/sri-sim/scenarios/{'8' * 49}")
    assert response.status_code == 404


async def test_reset_endpoint_clears_scenarios(client) -> None:
    access_key = "7" * 49
    await client.post(
        "/sri-sim/scenarios",
        json={"accessKey": access_key, "behavior": "AUTHORIZED"},
    )
    reset_response = await client.post("/sri-sim/reset")
    assert reset_response.status_code == 204

    get_response = await client.get(f"/sri-sim/scenarios/{access_key}")
    assert get_response.status_code == 404
