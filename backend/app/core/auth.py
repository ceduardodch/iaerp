import asyncio
import secrets
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated, cast

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jwt import PyJWKClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.session import get_session
from app.models.platform import Membership, ServiceAccount, Tenant, User

settings = get_settings()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.API_PREFIX}/dev/token")


@dataclass(frozen=True)
class AuthContext:
    actor_id: str
    actor_type: str
    tenant_id: uuid.UUID
    roles: frozenset[str]
    scopes: frozenset[str]
    token_id: str


def create_dev_token(
    *,
    subject: str,
    tenant_id: uuid.UUID,
    roles: list[str],
    scopes: list[str],
) -> tuple[str, int]:
    if settings.AUTH_MODE != "dev":
        raise RuntimeError("Development tokens are disabled")
    expires_in = 3600
    now = datetime.now(UTC)
    payload = {
        "iss": "iaerp-dev",
        "aud": [settings.OIDC_API_AUDIENCE, settings.OIDC_MCP_AUDIENCE],
        "azp": "iaerp-dev-web",
        "sub": subject,
        "tenant_id": str(tenant_id),
        "roles": roles,
        "scope": " ".join(scopes),
        "iat": now,
        "exp": now + timedelta(seconds=expires_in),
        "jti": secrets.token_urlsafe(24),
    }
    return (
        jwt.encode(payload, settings.DEV_JWT_SECRET, algorithm="HS256"),
        expires_in,
    )


def _extract_organization_id(payload: dict[str, object]) -> str:
    organizations = payload.get("organization")
    if not isinstance(organizations, dict) or len(organizations) != 1:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Token must contain exactly one organization",
        )
    organization = next(iter(organizations.values()))
    if not isinstance(organization, dict) or not isinstance(organization.get("id"), str):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Organization id is missing",
        )
    return cast(str, organization["id"])


async def decode_access_token(
    token: str,
    *,
    audience: str | None = None,
) -> dict[str, object]:
    expected_audience = audience or settings.OIDC_API_AUDIENCE
    if settings.AUTH_MODE == "dev":
        return jwt.decode(
            token,
            settings.DEV_JWT_SECRET,
            algorithms=["HS256"],
            audience=expected_audience,
            issuer="iaerp-dev",
        )

    jwks_url = settings.OIDC_JWKS_URL or (
        f"{settings.OIDC_ISSUER_URL}/protocol/openid-connect/certs"
    )
    jwks = PyJWKClient(jwks_url)
    signing_key = await asyncio.to_thread(jwks.get_signing_key_from_jwt, token)
    return jwt.decode(
        token,
        signing_key.key,
        algorithms=["RS256"],
        audience=expected_audience,
        issuer=settings.OIDC_ISSUER_URL,
    )


async def resolve_auth_context(
    payload: dict[str, object],
    session: AsyncSession,
) -> AuthContext:
    token_id = str(payload.get("jti") or "")
    scopes = frozenset(str(payload.get("scope") or "").split())

    tenant_id: uuid.UUID
    if settings.AUTH_MODE == "dev":
        tenant_value = payload.get("tenant_id")
        if not isinstance(tenant_value, str):
            raise HTTPException(status_code=403, detail="Tenant claim is missing")
        tenant_id = uuid.UUID(tenant_value)
    else:
        organization_id = _extract_organization_id(payload)
        resolved_tenant_id = await session.scalar(
            select(Tenant.id).where(
                Tenant.organization_id == organization_id,
                Tenant.active.is_(True),
            )
        )
        if resolved_tenant_id is None:
            raise HTTPException(status_code=404, detail="Tenant not found")
        tenant_id = resolved_tenant_id

    subject = payload.get("sub")
    client_id = payload.get("client_id") or payload.get("azp")
    if isinstance(subject, str) and not subject.startswith("service-account-"):
        row = await session.execute(
            select(User, Membership)
            .join(Membership, Membership.user_id == User.id)
            .where(
                User.external_subject == subject,
                User.active.is_(True),
                Membership.tenant_id == tenant_id,
                Membership.active.is_(True),
            )
        )
        user_membership = row.first()
        if user_membership is None:
            raise HTTPException(status_code=404, detail="Membership not found")
        user, membership = user_membership
        return AuthContext(
            actor_id=str(user.id),
            actor_type="USER",
            tenant_id=tenant_id,
            roles=frozenset(membership.roles),
            scopes=scopes,
            token_id=token_id,
        )

    if not isinstance(client_id, str):
        raise HTTPException(status_code=403, detail="Client identity is missing")
    service_account = await session.scalar(
        select(ServiceAccount).where(
            ServiceAccount.client_id == client_id,
            ServiceAccount.tenant_id == tenant_id,
            ServiceAccount.active.is_(True),
            ServiceAccount.expires_at > datetime.now(UTC),
        )
    )
    if service_account is None:
        raise HTTPException(status_code=404, detail="Service account not found")
    effective_scopes = scopes.intersection(service_account.scopes)
    return AuthContext(
        actor_id=str(service_account.id),
        actor_type="SERVICE_ACCOUNT",
        tenant_id=tenant_id,
        roles=frozenset({"agent"}),
        scopes=frozenset(effective_scopes),
        token_id=token_id,
    )


async def get_auth_context(
    token: Annotated[str, Depends(oauth2_scheme)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AuthContext:
    try:
        payload = await decode_access_token(token)
    except (jwt.PyJWTError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid access token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    return await resolve_auth_context(payload, session)


def require_scopes(
    *required: str,
) -> Callable[..., Awaitable[AuthContext]]:
    async def dependency(
        context: Annotated[AuthContext, Depends(get_auth_context)],
    ) -> AuthContext:
        missing = set(required).difference(context.scopes)
        if missing:
            scope_value = " ".join(sorted(missing))
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing scopes: {scope_value}",
                headers={
                    "WWW-Authenticate": (
                        f'Bearer error="insufficient_scope", scope="{scope_value}"'
                    )
                },
            )
        return context

    return dependency
