async def test_health_endpoints_verify_process_dependencies_and_schema(client):
    live = await client.get("/health/live")
    ready = await client.get("/health/ready")
    startup = await client.get("/health/startup")

    assert live.status_code == 200
    assert live.json() == {"status": "ok"}
    assert ready.status_code == 200
    assert ready.json() == {
        "status": "ok",
        "database": "ok",
        "redis": "ok",
    }
    assert startup.status_code == 200
    assert startup.json() == {
        "status": "ok",
        "database": "ok",
        "redis": "ok",
        "schema": "ok",
        "auth": "dev",
        "environment": "test",
    }
