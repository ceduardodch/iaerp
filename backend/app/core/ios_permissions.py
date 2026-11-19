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
    if IOS_INVOICE_WRITER_ROLES.intersection(roles):
        allowed = allowed | {
            "invoices:issue",
            "invoices:email",
            "invoices:write",
            IOS_CUSTOMER_CREATE,
            IOS_PRODUCT_CREATE,
        }
    return frozenset(scopes).intersection(allowed)


def ios_request_permitted(
    method: str, route_path: str, *, api_prefix: str, scopes: Iterable[str] = ()
) -> bool:
    if method in {"GET", "HEAD", "OPTIONS"}:
        return True
    native_action = re.fullmatch(
        re.escape(api_prefix)
        + r"/invoices/[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}/(issue|email)",
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
