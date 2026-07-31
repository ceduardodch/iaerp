from datetime import timedelta
from typing import cast

from minio import Minio

from app.services.storage import _presigned_download_url_sync


class FakeMinio:
    def __init__(self) -> None:
        self.response_headers: dict[str, str] | None = None

    def presigned_get_object(
        self,
        bucket_name: str,
        object_key: str,
        *,
        expires: timedelta,
        response_headers: dict[str, str] | None,
    ) -> str:
        self.response_headers = response_headers
        return "https://documents.example.test/signed"


def test_presigned_pdf_url_can_use_inline_content_disposition() -> None:
    client = FakeMinio()

    url = _presigned_download_url_sync(
        cast(Minio, client),
        bucket_name="documents",
        object_key="tenant/ride.pdf",
        expiry=timedelta(minutes=5),
        file_name="FACTURA-001.pdf",
        content_type="application/pdf",
        content_disposition="inline",
    )

    assert url == "https://documents.example.test/signed"
    assert client.response_headers == {
        "response-content-disposition": 'inline; filename="FACTURA-001.pdf"',
        "response-content-type": "application/pdf",
    }
