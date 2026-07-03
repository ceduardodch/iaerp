import json
import os
import sys
from typing import Any

import httpx
import jwt

BASE_URL = os.getenv("KEYCLOAK_URL", "http://localhost:8080")
REALM = os.getenv("KEYCLOAK_REALM", "iaerp")
USER_CLIENT_ID = os.getenv("KEYCLOAK_MCP_CLIENT_ID", "iaerp-mcp-cli")
USERNAME = os.getenv("KEYCLOAK_TEST_USERNAME", "owner")
PASSWORD = os.getenv("KEYCLOAK_TEST_PASSWORD", "DemoPass123!")
RESOURCE = os.getenv("MCP_SERVER_URL", "http://localhost:8000/mcp")

ORGANIZATIONS = {
    "iaerp-norte": "33333333-3333-4333-8333-333333333333",
    "iaerp-sur": "abababab-abab-4bab-8bab-abababababab",
}
SERVICE_ACCOUNTS = {
    "iaerp-agent-norte": os.getenv(
        "KEYCLOAK_AGENT_NORTE_SECRET",
        "local-only-agent-norte-secret",
    ),
    "iaerp-agent-sur": os.getenv(
        "KEYCLOAK_AGENT_SUR_SECRET",
        "local-only-agent-sur-secret",
    ),
}


def token_endpoint() -> str:
    return f"{BASE_URL}/realms/{REALM}/protocol/openid-connect/token"


def issue_user_token(scope: str, resource: str | None = RESOURCE) -> httpx.Response:
    data = {
        "grant_type": "password",
        "client_id": USER_CLIENT_ID,
        "username": USERNAME,
        "password": PASSWORD,
        "scope": f"openid {scope} context:read parties:read",
    }
    if resource is not None:
        data["resource"] = resource
    return httpx.post(token_endpoint(), data=data, timeout=15)


def issue_service_token(client_id: str, secret: str) -> httpx.Response:
    return httpx.post(
        token_endpoint(),
        data={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": secret,
        },
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


def has_audience(claims: dict[str, Any], expected: str) -> bool:
    audience = claims.get("aud")
    return audience == expected or (isinstance(audience, list) and expected in audience)


def selected_organization(claims: dict[str, Any], alias: str, expected_id: str) -> bool:
    organization = claims.get("organization")
    return (
        isinstance(organization, dict)
        and len(organization) == 1
        and isinstance(organization.get(alias), dict)
        and organization[alias].get("id") == expected_id
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

    user_responses = {alias: issue_user_token(f"organization:{alias}") for alias in ORGANIZATIONS}
    user_claims = {alias: decode(response) for alias, response in user_responses.items()}
    all_organizations_response = issue_user_token("organization:*")
    all_organizations_claims = decode(all_organizations_response)

    without_resource = issue_user_token("organization:iaerp-norte", None)
    foreign_resource = issue_user_token(
        "organization:iaerp-norte",
        "https://invalid.example/mcp",
    )

    service_responses = {
        client_id: issue_service_token(client_id, secret)
        for client_id, secret in SERVICE_ACCOUNTS.items()
    }
    service_claims = {
        client_id: decode(response) for client_id, response in service_responses.items()
    }

    selected = {
        alias: selected_organization(user_claims[alias], alias, organization_id)
        for alias, organization_id in ORGANIZATIONS.items()
    }
    service_accounts = {
        client_id: (claims.get("azp") == client_id and has_audience(claims, RESOURCE))
        for client_id, claims in service_claims.items()
    }
    all_organizations = all_organizations_claims.get("organization")

    report = {
        "keycloakVersion": "26.6.4",
        "issuerDiscovery": discovery.status_code == 200,
        "oauthAuthorizationServerMetadata": oauth_metadata.status_code == 200,
        "selectedOrganizations": selected,
        "allOrganizationsOnlyWhenRequested": (
            isinstance(all_organizations, dict) and set(all_organizations) == set(ORGANIZATIONS)
        ),
        "fixedMcpAudience": all(has_audience(claims, RESOURCE) for claims in user_claims.values()),
        "serviceAccounts": service_accounts,
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
        report["allOrganizationsOnlyWhenRequested"],
        report["fixedMcpAudience"],
        all(selected.values()),
        all(service_accounts.values()),
    ]
    return 0 if all(required) else 1


if __name__ == "__main__":
    sys.exit(main())
