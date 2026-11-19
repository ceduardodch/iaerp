"""Configure only the public iaerp-ios OIDC client using existing admin env.

Run inside the existing IAERP API environment with a JSON envelope on stdin:
{"client": <reviewed template>, "profileScope": <reviewed profile scope>,
 "expectedBackendHashes": {"app/core/auth.py": "<sha256>", ...}}.
Default preparation leaves the client disabled. --enable requires exact SHA256
hashes of the reviewed security files in /app, checked before contacting OAuth.
No token, secret, user record, or existing client's representation is printed.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys

import httpx

BACKEND_FILES = frozenset({
    "app/core/auth.py", "app/core/ios_permissions.py",
    "app/services/draft_requests.py", "app/api/router.py", "app/api/ios_customers.py",
    "app/api/ios_products.py", "app/core/ios_catalog_access.py",
    "app/integrations/sri/soap.py", "app/workers/sri_transmission.py", "app/services/invoice_delivery.py", "app/services/billing.py", "app/services/crm_integrations.py",
})
DEFAULT_SCOPES = frozenset({
    "profile", "context:read", "memberships:read", "organization:read",
    "parties:read", "customers:create", "products:read", "products:create", "invoices:read", "invoices:write", "invoices:issue", "invoices:email", "receivables:read",
})


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def verify_backend_hashes(expected: object, root: Path = Path("/app")) -> None:
    require(isinstance(expected, dict) and set(expected) == BACKEND_FILES,
            "Enabling requires the complete set of expectedBackendHashes entries")
    for relative in sorted(BACKEND_FILES):
        digest = expected[relative]
        require(isinstance(digest, str) and re.fullmatch(r"[0-9a-f]{64}", digest) is not None,
                "Expected backend hashes must be lowercase SHA256 hex")
    for relative in sorted(BACKEND_FILES):
        try:
            actual = hashlib.sha256((root / relative).read_bytes()).hexdigest()
        except OSError:
            raise RuntimeError("Required deployed backend file is unavailable: " + relative) from None
        require(actual == expected[relative], "Deployed backend hash mismatch: " + relative)


def validate_templates(desired: dict, profile: dict) -> None:
    callback = "ec.com.b2b.iaerp:/oauth2redirect"
    require(desired.get("clientId") == "iaerp-ios" and desired.get("protocol") == "openid-connect",
            "Only the native OIDC client is supported")
    for key, value in {
        "publicClient": True, "standardFlowEnabled": True, "enabled": False,
        "bearerOnly": False, "implicitFlowEnabled": False,
        "directAccessGrantsEnabled": False, "serviceAccountsEnabled": False,
        "fullScopeAllowed": False,
    }.items():
        require(desired.get(key) is value, "Unsafe native client setting: " + key)
    require(desired.get("redirectUris") == [callback] and desired.get("webOrigins") == [],
            "Native callback and origins must match the reviewed template")
    require(desired.get("attributes") == {
        "pkce.code.challenge.method": "S256", "post.logout.redirect.uris": callback,
    }, "Native PKCE and logout settings must match the reviewed template")
    for field, expected in (("defaultClientScopes", DEFAULT_SCOPES),
                            ("optionalClientScopes", frozenset({"organization"}))):
        names = desired.get(field)
        require(isinstance(names, list) and all(isinstance(name, str) for name in names)
                and len(names) == len(expected) and set(names) == expected,
                "Native scopes must match the reviewed allowlist")
    require("secret" not in desired and profile.get("name") == "profile",
            "Native templates must not contain a client secret or another scope")


def mapper_settings(mappers: list) -> list:
    return sorted(({
        key: mapper.get(key) for key in ("name", "protocol", "protocolMapper", "config")
    } for mapper in mappers), key=lambda mapper: mapper["name"])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--enable", action="store_true")
    args = parser.parse_args()
    envelope = json.load(sys.stdin)
    desired = envelope["client"]
    profile = envelope["profileScope"]
    validate_templates(desired, profile)
    if args.enable:
        verify_backend_hashes(envelope.get("expectedBackendHashes"))
    desired["enabled"] = False  # Stage every mutation with access disabled.

    base = os.environ["OIDC_ADMIN_URL"].rstrip("/")
    realm = os.environ["OIDC_ADMIN_REALM"]
    with httpx.Client(timeout=20) as client:
        token = client.post(
            f"{base}/realms/{realm}/protocol/openid-connect/token",
            data={
                "grant_type": "client_credentials",
                "client_id": os.environ["OIDC_ADMIN_CLIENT_ID"],
                "client_secret": os.environ["OIDC_ADMIN_CLIENT_SECRET"],
            },
        )
        token.raise_for_status()
        headers = {"Authorization": "Bearer " + token.json()["access_token"]}
        admin = f"{base}/admin/realms/{realm}"

        def request(method: str, path: str, **kwargs: object) -> httpx.Response:
            response = client.request(method, admin + path, headers=headers, **kwargs)
            response.raise_for_status()
            return response

        scopes = request("GET", "/client-scopes").json()
        by_name = {item["name"]: item for item in scopes}
        if "profile" not in by_name:
            request("POST", "/client-scopes", json=profile)
            by_name = {item["name"]: item for item in request("GET", "/client-scopes").json()}
        for scope_name in ("customers:create", "products:create", "invoices:issue", "invoices:email"):
            if scope_name not in by_name:
                request("POST", "/client-scopes", json={
                    "name": scope_name, "protocol": "openid-connect",
                    "attributes": {"include.in.token.scope": "true"},
                })
                by_name = {item["name"]: item for item in request("GET", "/client-scopes").json()}
            entry = by_name.get(scope_name, {})
            require(entry.get("protocol") == "openid-connect"
                    and entry.get("attributes", {}).get("include.in.token.scope") == "true"
                    and not entry.get("protocolMappers"),
                    "Unexpected native scope configuration: " + scope_name)
        names = set(desired["defaultClientScopes"] + desired["optionalClientScopes"])
        if not names.issubset(by_name):
            raise RuntimeError("A required native client scope is unavailable")
        existing = request("GET", "/clients", params={"clientId": "iaerp-ios"}).json()
        if len(existing) > 1:
            raise RuntimeError("Ambiguous native client registration")
        if existing:
            if existing[0].get("enabled") and not args.enable:
                raise RuntimeError("An enabled native client already exists; refusing to disable it implicitly")
            identifier = existing[0]["id"]
            request("PUT", f"/clients/{identifier}", json=desired)
        else:
            request("POST", "/clients", json=desired)
            registered = request("GET", "/clients", params={"clientId": "iaerp-ios"}).json()
            require(len(registered) == 1, "Native client registration could not be identified")
            identifier = registered[0]["id"]

        staged = request("GET", f"/clients/{identifier}").json()
        require(staged.get("clientId") == "iaerp-ios" and staged.get("enabled") is False,
                "Native client must be confirmed disabled before reconciling scopes")

        # Reconcile only this client's associations. Realm defaults and every
        # other client remain untouched, including web and service accounts.
        for kind, field in (("default", "defaultClientScopes"), ("optional", "optionalClientScopes")):
            current = request("GET", f"/clients/{identifier}/{kind}-client-scopes").json()
            for scope in current:
                if scope["name"] not in desired[field]:
                    request("DELETE", f"/clients/{identifier}/{kind}-client-scopes/{scope['id']}")
            for name in desired[field]:
                request("PUT", f"/clients/{identifier}/{kind}-client-scopes/{by_name[name]['id']}")

        def verified_report(enabled: bool) -> dict:
            final = request("GET", f"/clients/{identifier}").json()
            fields = (
                "clientId", "protocol", "enabled", "publicClient", "bearerOnly",
                "standardFlowEnabled", "implicitFlowEnabled", "directAccessGrantsEnabled",
                "serviceAccountsEnabled", "fullScopeAllowed", "redirectUris", "webOrigins",
            )
            report = {key: final.get(key) for key in fields}
            for key in fields:
                expected = enabled if key == "enabled" else desired[key]
                actual = report[key]
                require(actual == expected and type(actual) is type(expected),
                        "Native client readback mismatch: " + key)
            attributes = final.get("attributes", {})
            require(all(attributes.get(key) == value for key, value in desired["attributes"].items()),
                    "Native PKCE/logout readback mismatch")
            report["attributes"] = {key: attributes.get(key) for key in desired["attributes"]}
            require(mapper_settings(final.get("protocolMappers", [])) == mapper_settings(desired["protocolMappers"]),
                    "Native protocol mapper readback mismatch")
            for kind, field in (("default", "defaultClientScopes"), ("optional", "optionalClientScopes")):
                actual = request("GET", f"/clients/{identifier}/{kind}-client-scopes").json()
                report[kind + "Scopes"] = sorted(item["name"] for item in actual)
                require(report[kind + "Scopes"] == sorted(desired[field]),
                        "Native client scope readback mismatch: " + kind)
            return report

        report = verified_report(False)
        if args.enable:
            # No association is changed after enabling. Recheck local deployment
            # immediately before the final OAuth mutation as well.
            verify_backend_hashes(envelope.get("expectedBackendHashes"))
            try:
                request("PUT", f"/clients/{identifier}", json={**desired, "enabled": True})
                report = verified_report(True)
            except Exception:
                # A failed final readback must not knowingly leave access open.
                # Network loss can prevent confirmation; surface that explicitly.
                try:
                    request("PUT", f"/clients/{identifier}", json={**desired, "enabled": False})
                    verified_report(False)
                except Exception:
                    raise RuntimeError("Enabling failed; disabled state could not be confirmed") from None
                raise RuntimeError("Enabling failed; native client returned to disabled") from None
        print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
