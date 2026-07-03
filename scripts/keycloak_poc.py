import json
import os
import sys
from typing import Any

import httpx
import jwt

BASE_URL = os.getenv("KEYCLOAK_URL", "http://localhost:8080")
REALM = os.getenv("KEYCLOAK_REALM", "iaerp")
CLIENT_ID = os.getenv("KEYCLOAK_MCP_CLIENT_ID", "iaerp-mcp-cli")
USERNAME = os.getenv("KEYCLOAK_TEST_USERNAME", "owner")
PASSWORD = os.getenv("KEYCLOAK_TEST_PASSWORD", "DemoPass123!")
RESOURCE = os.getenv("MCP_SERVER_URL", "http://localhost:8000/mcp")
ORGANIZATION_ID = "33333333-3333-4333-8333-333333333333"


def issue_token(resource: str | None) -> httpx.Response:
    data = {
        "grant_type": "password",
        "client_id": CLIENT_ID,
        "username": USERNAME,
        "password": PASSWORD,
        "scope": "openid organization:iaerp-demo context:read parties:read",
    }
    if resource is not None:
        data["resource"] = resource
    return httpx.post(
        f"{BASE_URL}/realms/{REALM}/protocol/openid-connect/token",
        data=data,
        timeout=15,
    )


def decode(response: httpx.Response) -> dict[str, Any]:
    response.raise_for_status()
    token = response.json()["access_token"]
    return jwt.decode(
        token,
        options={
            "verify_signature": False,
            "verify_aud": False,
            "verify_exp": False,
        },
    )


def main() -> int:
    discovery = httpx.get(
        f"{BASE_URL}/realms/{REALM}/.well-known/openid-configuration",
        timeout=15,
    )
    oauth_metadata = httpx.get(
        f"{BASE_URL}/.well-known/oauth-authorization-server/realms/{REALM}",
        timeout=15,
    )
    with_resource = issue_token(RESOURCE)
    without_resource = issue_token(None)
    foreign_resource = issue_token("https://invalid.example/mcp")
    claims = decode(with_resource)

    organization = claims.get("organization")
    organization_ok = (
        isinstance(organization, dict)
        and organization.get("iaerp-demo", {}).get("id") == ORGANIZATION_ID
    )
    audience_ok = claims.get("aud") == RESOURCE or (
        isinstance(claims.get("aud"), list) and RESOURCE in claims["aud"]
    )

    report = {
        "keycloakVersion": "26.6.4",
        "issuerDiscovery": discovery.status_code == 200,
        "oauthAuthorizationServerMetadata": oauth_metadata.status_code == 200,
        "resourceRequestAccepted": with_resource.status_code == 200,
        "fixedMcpAudience": audience_ok,
        "singleOrganizationWithId": organization_ok,
        "requestWithoutResourceStatus": without_resource.status_code,
        "foreignResourceStatus": foreign_resource.status_code,
        "nativeRfc8707Strict": foreign_resource.status_code >= 400,
        "compatibilityProfile": (
            "native-rfc8707"
            if foreign_resource.status_code >= 400
            else "fixed-audience-with-resource-server-validation"
        ),
    }
    print(json.dumps(report, indent=2, sort_keys=True))

    required = [
        report["issuerDiscovery"],
        report["oauthAuthorizationServerMetadata"],
        report["resourceRequestAccepted"],
        report["fixedMcpAudience"],
        report["singleOrganizationWithId"],
    ]
    return 0 if all(required) else 1


if __name__ == "__main__":
    sys.exit(main())
