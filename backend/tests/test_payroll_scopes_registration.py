"""Registro de los scopes ``payroll:read``/``payroll:write`` fuera de los
endpoints: cuentas de servicio, realm de Keycloak y bootstrap de staging.

``test_payroll_api.py`` ya cubre que los endpoints exijan estos scopes; aquí
se cubre que el resto del sistema los reconozca. Sin este registro, un agente
MCP no podría pedir un token con scope ``payroll:*`` (rechazado con 422) y el
realm de staging nunca ofrecería el scope al cliente web.
"""

import json
from pathlib import Path

from tests.test_platform_api import TENANT_A, auth, token_for

REPO_ROOT = Path(__file__).resolve().parents[2]


async def test_service_account_can_request_payroll_scopes(client) -> None:
    token = await token_for(client, "a@iaerp.local", TENANT_A)
    response = await client.post(
        "/api/v1/service-accounts",
        headers=auth(token, "payroll-scope-service-account-0001"),
        json={
            "name": "Payroll Agent",
            "scopes": ["payroll:read", "payroll:write"],
            "expiresAt": "2030-01-01T00:00:00Z",
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["account"]["scopes"] == ["payroll:read", "payroll:write"]


def test_keycloak_realm_declares_payroll_scopes() -> None:
    realm = json.loads((REPO_ROOT / "infra/keycloak/iaerp-realm.json").read_text())

    declared = {scope["name"] for scope in realm["clientScopes"]}
    assert {"payroll:read", "payroll:write"} <= declared

    web_client = next(c for c in realm["clients"] if c["clientId"] == "iaerp-web")
    assert {"payroll:read", "payroll:write"} <= set(web_client["defaultClientScopes"])


def test_configure_staging_registers_payroll_scopes() -> None:
    script = (REPO_ROOT / "infra/keycloak/configure-staging.sh").read_text()
    assert "payroll:read" in script
    assert "payroll:write" in script
