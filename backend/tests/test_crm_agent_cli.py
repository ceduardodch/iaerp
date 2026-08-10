import pytest

from scripts.crm_agent_cli import _parser


def test_create_commands_require_a_reusable_idempotency_key() -> None:
    with pytest.raises(SystemExit):
        _parser().parse_args(
            [
                "create-lead",
                "--name",
                "Prospecto",
                "--identification-type",
                "RUC",
                "--identification-number",
                "1790000000001",
                "--email",
                "prospecto@example.com",
                "--title",
                "Revision AWS",
            ]
        )


def test_activity_reminder_requires_timezone() -> None:
    with pytest.raises(SystemExit):
        _parser().parse_args(
            [
                "create-activity",
                "--lead-id",
                "11111111-1111-4111-8111-111111111111",
                "--type",
                "TASK",
                "--subject",
                "Primer contacto",
                "--reminder-date",
                "2026-08-10T09:00:00",
                "--idempotency-key",
                "agent-activity-20260810-001",
            ]
        )

    parsed = _parser().parse_args(
        [
            "create-activity",
            "--lead-id",
            "11111111-1111-4111-8111-111111111111",
            "--type",
            "TASK",
            "--subject",
            "Primer contacto",
            "--reminder-date",
            "2026-08-10T09:00:00-05:00",
            "--idempotency-key",
            "agent-activity-20260810-001",
        ]
    )
    assert parsed.reminder_date == "2026-08-10T09:00:00-05:00"
