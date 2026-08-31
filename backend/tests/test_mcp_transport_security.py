from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from app.mcp.server import _transport_security_for
from app.schemas.platform import ServiceAccountCreate


def test_mcp_transport_security_allows_only_the_configured_public_origin() -> None:
    security = _transport_security_for("https://iaerp.b2b.com.ec/mcp")

    assert security.enable_dns_rebinding_protection is True
    assert security.allowed_hosts == ["iaerp.b2b.com.ec"]
    assert security.allowed_origins == ["https://iaerp.b2b.com.ec"]


def test_mcp_transport_security_keeps_local_development_hosts() -> None:
    security = _transport_security_for("http://localhost:8000/mcp")

    assert "localhost:8000" in security.allowed_hosts
    assert "localhost:*" in security.allowed_hosts
    assert "http://localhost:8000" in security.allowed_origins
    assert "http://localhost:*" in security.allowed_origins


def test_service_account_accepts_tax_scopes_but_not_unknown_scopes() -> None:
    account = ServiceAccountCreate(
        name="SRI Daily Import",
        scopes=["tax:write", "tax:read", "tax:write"],
        expiresAt=datetime.now(UTC) + timedelta(days=365),
    )

    assert account.scopes == ["tax:read", "tax:write"]

    with pytest.raises(ValidationError, match="unsupported service account scopes"):
        ServiceAccountCreate(
            name="Unsafe agent",
            scopes=["admin:write"],
            expiresAt=datetime.now(UTC) + timedelta(days=365),
        )
