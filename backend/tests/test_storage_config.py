from collections.abc import Iterator
from types import SimpleNamespace

import pytest
from pydantic import SecretStr

from app.services import storage


@pytest.fixture(autouse=True)
def clear_storage_clients() -> Iterator[None]:
    storage._client.cache_clear()
    storage._public_client.cache_clear()
    yield
    storage._client.cache_clear()
    storage._public_client.cache_clear()


def _settings(
    *,
    internal_secure: bool,
    public_secure: bool | None,
) -> SimpleNamespace:
    return SimpleNamespace(
        MINIO_ENDPOINT="minio:9000",
        MINIO_PUBLIC_ENDPOINT="files.example.test",
        MINIO_PUBLIC_SECURE=public_secure,
        MINIO_ACCESS_KEY="test-access",
        MINIO_SECRET_KEY=SecretStr("test-secret"),
        MINIO_SECURE=internal_secure,
        MINIO_REGION="us-east-1",
    )


def test_internal_and_public_minio_clients_use_independent_tls(
    monkeypatch,
) -> None:
    calls: list[dict[str, object]] = []

    def fake_minio(endpoint: str, **kwargs: object) -> object:
        calls.append({"endpoint": endpoint, **kwargs})
        return object()

    monkeypatch.setattr(
        storage,
        "get_settings",
        lambda: _settings(internal_secure=False, public_secure=True),
    )
    monkeypatch.setattr(storage, "Minio", fake_minio)

    storage._client()
    storage._public_client()

    assert calls[0]["endpoint"] == "minio:9000"
    assert calls[0]["secure"] is False
    assert calls[1]["endpoint"] == "files.example.test"
    assert calls[1]["secure"] is True


def test_public_minio_tls_defaults_to_internal_setting(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    def fake_minio(endpoint: str, **kwargs: object) -> object:
        calls.append({"endpoint": endpoint, **kwargs})
        return object()

    monkeypatch.setattr(
        storage,
        "get_settings",
        lambda: _settings(internal_secure=True, public_secure=None),
    )
    monkeypatch.setattr(storage, "Minio", fake_minio)

    storage._public_client()

    assert calls[0]["secure"] is True
