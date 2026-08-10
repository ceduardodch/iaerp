"""Cliente cerrado para que un agente opere solo el CRM autorizado."""

import argparse
import asyncio
import json
import os
import uuid
from datetime import datetime
from pathlib import Path

import httpx
from dotenv import load_dotenv

from app.integrations.oidc_client_credentials import ClientCredentialsToken

DEFAULT_TOKEN_URL = (
    "https://iaerp-auth.b2b.com.ec/realms/iaerp/protocol/openid-connect/token"
)


def _idempotency_key(value: str) -> str:
    if not 16 <= len(value) <= 128:
        raise argparse.ArgumentTypeError("la clave debe tener entre 16 y 128 caracteres")
    return value


def _aware_datetime(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("fecha ISO 8601 inválida") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise argparse.ArgumentTypeError("la fecha debe incluir zona horaria")
    return value


def _configuration() -> tuple[str, ClientCredentialsToken]:
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    base_url = os.environ.get("PROSPECT_CRM_URL")
    client_id = os.environ.get("PROSPECT_CRM_CLIENT_ID")
    client_secret = os.environ.get("PROSPECT_CRM_CLIENT_SECRET")
    token_url = os.environ.get("PROSPECT_CRM_TOKEN_URL", DEFAULT_TOKEN_URL)
    if not base_url or not client_id or not client_secret:
        raise SystemExit(
            "Faltan PROSPECT_CRM_URL, PROSPECT_CRM_CLIENT_ID o "
            "PROSPECT_CRM_CLIENT_SECRET en backend/.env"
        )
    return base_url, ClientCredentialsToken(token_url, client_id, client_secret)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    leads = commands.add_parser("leads")
    leads.add_argument("--status")
    leads.add_argument("--limit", type=int, default=100, choices=range(1, 201))
    activities = commands.add_parser("activities")
    activities.add_argument("--lead-id", required=True, type=uuid.UUID)
    create = commands.add_parser("create-lead")
    create.add_argument("--name", required=True)
    create.add_argument(
        "--identification-type",
        required=True,
        choices=("RUC", "CEDULA", "PASSPORT", "FINAL_CONSUMER"),
    )
    create.add_argument("--identification-number", required=True)
    create.add_argument("--email")
    create.add_argument("--phone")
    create.add_argument("--title", required=True)
    create.add_argument("--idempotency-key", required=True, type=_idempotency_key)
    activity = commands.add_parser("create-activity")
    activity.add_argument("--lead-id", required=True, type=uuid.UUID)
    activity.add_argument(
        "--type",
        required=True,
        choices=("CALL", "EMAIL", "WHATSAPP", "MEETING", "NOTE", "TASK"),
    )
    activity.add_argument("--subject", required=True)
    activity.add_argument("--description")
    activity.add_argument(
        "--outcome",
        default="PENDING",
        choices=("POSITIVE", "NEUTRAL", "NEGATIVE", "PENDING"),
    )
    activity.add_argument("--reminder-date", type=_aware_datetime)
    activity.add_argument("--idempotency-key", required=True, type=_idempotency_key)
    return parser


async def _run(args: argparse.Namespace) -> object:
    base_url, token = _configuration()
    async with httpx.AsyncClient(base_url=base_url, timeout=30) as client:
        if args.command == "leads":
            params = {"limit": args.limit}
            if args.status:
                params["status"] = args.status
            response = await token.request(client, "GET", "/api/v1/crm/leads", params=params)
        elif args.command == "activities":
            response = await token.request(
                client,
                "GET",
                f"/api/v1/crm/leads/{args.lead_id}/activities",
            )
        elif args.command == "create-lead":
            if not args.email and not args.phone:
                raise SystemExit("create-lead requiere --email o --phone")
            response = await token.request(
                client,
                "POST",
                "/api/v1/crm/leads/with-party",
                headers={"Idempotency-Key": args.idempotency_key},
                json={
                    "partyName": args.name,
                    "partyIdentificationType": args.identification_type,
                    "partyIdentificationNumber": args.identification_number,
                    "partyEmail": args.email,
                    "partyPhone": args.phone,
                    "title": args.title,
                    "status": "NEW",
                    "source": "MCP",
                },
            )
        else:
            response = await token.request(
                client,
                "POST",
                f"/api/v1/crm/leads/{args.lead_id}/activities",
                headers={"Idempotency-Key": args.idempotency_key},
                json={
                    "leadId": str(args.lead_id),
                    "activityType": args.type,
                    "subject": args.subject,
                    "description": args.description,
                    "outcome": args.outcome,
                    "reminderDate": args.reminder_date,
                    "reminderCompleted": False,
                },
            )
        response.raise_for_status()
        return response.json()


def main() -> None:
    result = asyncio.run(_run(_parser().parse_args()))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
