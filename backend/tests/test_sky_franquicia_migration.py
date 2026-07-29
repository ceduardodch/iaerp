from app.services.sky_franquicia_migration import validate_source_invoices


def _row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "id": "source-invoice-1",
        "status": "AUTHORIZED",
        "sri_access_key": "1" * 49,
        "sri_auth_code": "1" * 49,
        "sri_xml": "<autorizacion />",
        "line_count": 1,
        "subtotal_15": "100.00",
        "subtotal_0": "0.00",
        "discount": "0.00",
        "line_subtotal": "100.00",
    }
    row.update(overrides)
    return row


def test_valid_source_invoice_has_no_validation_issues() -> None:
    assert validate_source_invoices([_row()]) == []


def test_validation_rejects_unreconciled_or_incomplete_documents() -> None:
    issues = validate_source_invoices(
        [
            _row(sri_xml=None, line_subtotal="99.99"),
            _row(id="source-invoice-2", sri_access_key="1" * 49),
        ]
    )

    assert {issue.code for issue in issues} == {
        "AUTHORIZED_ARTIFACT_GAP",
        "LINE_SUBTOTAL_MISMATCH",
        "DUPLICATE_ACCESS_KEY",
    }
