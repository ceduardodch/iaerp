"""ERP permissions for the delegated, company-scoped Grok connector."""

from collections.abc import Iterable

from app.core.ios_permissions import IOS_COLLECTION_WRITER_ROLES, IOS_INVOICE_WRITER_ROLES

GROK_CLIENT_ID = "iaerp-grok-informes"
_READ_SCOPES = frozenset(
    {"context:read", "invoices:read", "parties:read", "products:read", "receivables:read"}
)
_TAX_READER_ROLES = frozenset({"owner", "admin", "accountant", "auditor"})
_OIDC_SCOPES = frozenset({"openid", "profile", "email", "organization", "offline_access"})


def is_grok_client(claims: dict[str, object]) -> bool:
    return any(claims.get(name) == GROK_CLIENT_ID for name in ("azp", "client_id"))


def grok_effective_scopes(
    scopes: frozenset[str], membership_roles: Iterable[str]
) -> frozenset[str]:
    allowed = _READ_SCOPES | _OIDC_SCOPES
    roles = frozenset(membership_roles)
    if not _TAX_READER_ROLES.isdisjoint(roles):
        allowed |= {"tax:read"}
    if not IOS_INVOICE_WRITER_ROLES.isdisjoint(roles):
        allowed |= {"invoices:write", "invoices:issue", "invoices:email"}
    if not IOS_COLLECTION_WRITER_ROLES.isdisjoint(roles):
        allowed |= {"receivables:write"}
    return scopes & allowed
