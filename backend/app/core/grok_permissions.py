"""ERP permissions for the delegated, company-scoped Grok connector."""

from collections.abc import Iterable

from app.core.ios_permissions import IOS_COLLECTION_WRITER_ROLES, IOS_INVOICE_WRITER_ROLES

GROK_CLIENT_ID = "iaerp-grok-informes"
_READ_SCOPES = frozenset(
    {"context:read", "invoices:read", "parties:read", "products:read", "receivables:read"}
)
GROK_BUSINESS_ANALYSIS_SCOPE = "grok:business-analysis:read"
GROK_TAX_SUMMARY_SCOPE = "grok:tax-summary:read"
_TAX_READER_ROLES = frozenset({"owner", "admin", "accountant", "auditor"})
_OIDC_SCOPES = frozenset({"openid", "profile", "email", "organization", "offline_access"})


def is_grok_client(claims: dict[str, object]) -> bool:
    return any(claims.get(name) == GROK_CLIENT_ID for name in ("azp", "client_id"))


def grok_effective_scopes(
    scopes: frozenset[str],
    membership_roles: Iterable[str],
    *,
    analysis_enabled: bool,
) -> frozenset[str]:
    allowed = _READ_SCOPES | _OIDC_SCOPES
    roles = frozenset(membership_roles)
    if not IOS_INVOICE_WRITER_ROLES.isdisjoint(roles):
        allowed |= {"invoices:write", "invoices:issue", "invoices:email"}
    if not IOS_COLLECTION_WRITER_ROLES.isdisjoint(roles):
        allowed |= {"receivables:write"}
    effective = scopes & allowed
    fiscal_grants = {GROK_TAX_SUMMARY_SCOPE, "tax:read"}
    if (
        analysis_enabled
        and fiscal_grants.intersection(scopes)
        and _TAX_READER_ROLES.intersection(roles)
    ):
        effective |= {"tax:read"}
    if (
        analysis_enabled
        and GROK_BUSINESS_ANALYSIS_SCOPE in scopes
        and roles.intersection({"owner", "admin"})
    ):
        effective |= {"reports:read"}
    return effective
