"""Permissions for the first native iOS client, not a global ERP role matrix.

The signed client identity chooses this policy; active tenant membership is
still resolved from IAERP on every request. Unknown or unrelated roles never
gain invoice writes. Existing web and service-account policies stay unchanged.
"""

import re
from collections.abc import Iterable

IOS_PRODUCT_CREATE = "products:create"
IOS_CUSTOMER_CREATE = "customers:create"
IOS_CLIENT_ID = "iaerp-ios"
IOS_READ_SCOPES = frozenset(
    {
        "context:read",
        "memberships:read",
        "organization:read",
        "parties:read",
        "products:read",
        "invoices:read",
    }
)
# Initial business roles are documented in docs/02-scope-and-restrictions.md.
# Seed-only labels such as operator/accountant do not imply billing authority.
IOS_OVERVIEW_ROLES = frozenset({"owner", "admin", "collections", "auditor"})
IOS_COLLECTION_WRITER_ROLES = frozenset({"owner", "admin", "collections"})
IOS_INVOICE_WRITER_ROLES = frozenset({"owner", "admin", "billing"})


def is_ios_client(payload: dict[str, object]) -> bool:
    """Either signed identity claim activates the restriction, never bypasses it."""
    return any(payload.get(claim) == IOS_CLIENT_ID for claim in ("azp", "client_id"))


def validate_ios_client(
    payload: dict[str, object], *, api_audience: str, mcp_audience: str
) -> None:
    for claim in ("azp", "client_id"):
        value = payload.get(claim)
        if value is not None and value != IOS_CLIENT_ID:
            raise ValueError("Inconsistent native client identity")
    value = payload.get("aud")
    audiences = [value] if isinstance(value, str) else value
    if (
        not isinstance(audiences, list)
        or not all(isinstance(item, str) for item in audiences)
        or api_audience not in audiences
        or mcp_audience in audiences
    ):
        raise ValueError("Native client requires the API audience without MCP access")


def ios_effective_scopes(scopes: Iterable[str], membership_roles: Iterable[str]) -> frozenset[str]:
    allowed = IOS_READ_SCOPES
    roles = frozenset(membership_roles)
    if IOS_OVERVIEW_ROLES.intersection(roles):
        allowed = allowed | {"receivables:read"}
    if IOS_COLLECTION_WRITER_ROLES.intersection(roles):
        allowed = allowed | {"collections:terms", "collections:notify"}
    if IOS_INVOICE_WRITER_ROLES.intersection(roles):
        allowed = allowed | {
            "invoices:issue",
            "invoices:email",
            "invoices:write",
            IOS_CUSTOMER_CREATE,
            IOS_PRODUCT_CREATE,
        }
    return frozenset(scopes).intersection(allowed)


_UUID_PATH = r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}"


def _collection_action_scope(method: str, path: str, api_prefix: str) -> str | None:
    match = re.fullmatch(
        re.escape(api_prefix) + "/collections/accounts/" + _UUID_PATH
        + "/(promise|due-date|enable-reminders|reminder)", path
    )
    if match is None:
        return None
    return {
        ("PUT", "promise"): "collections:terms",
        ("PUT", "due-date"): "collections:terms",
        ("PUT", "enable-reminders"): "collections:notify",
        ("POST", "reminder"): "collections:notify",
    }.get((method, match[1]))


def ios_receivable_read_permitted(path: str, api_prefix: str, method: str = "GET") -> bool:
    if method not in {"GET", "HEAD", "OPTIONS"}:
        return _collection_action_scope(method, path, api_prefix) is not None
    accounts = f"{api_prefix}/collections/accounts"
    return (
        path in {f"{api_prefix}/receivables/overview", accounts}
        or re.fullmatch(re.escape(accounts) + "/" + _UUID_PATH, path) is not None
    )


def ios_request_permitted(
    method: str, route_path: str, *, api_prefix: str, scopes: Iterable[str] = ()
) -> bool:
    if method in {"GET", "HEAD", "OPTIONS"}:
        return True
    collection_scope = _collection_action_scope(method, route_path, api_prefix)
    if collection_scope is not None:
        return collection_scope in scopes
    native_action = re.fullmatch(
        re.escape(api_prefix)
        + "/invoices/" + _UUID_PATH + "/(issue|email)",
        route_path,
    )
    if method == "POST" and native_action:
        return "invoices:" + native_action[1] in scopes
    # invoices:write is shared by issue/email/void and draft in the legacy API.
    # Native writes use the dedicated quick-entry routes below.
    return method == "POST" and route_path in {
        f"{api_prefix}/invoices",
        f"{api_prefix}/invoices/preview",
        f"{api_prefix}/customers",
        f"{api_prefix}/customers/lookup",
        f"{api_prefix}/catalog-products",
        f"{api_prefix}/catalog-products/lookup",
    }
