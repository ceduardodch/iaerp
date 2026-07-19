from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from email.utils import parseaddr
from typing import cast
from urllib.parse import urlencode

import httpx
from fastapi import HTTPException
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthContext
from app.core.config import get_settings
from app.models.crm import GmailIntegration, Lead, LeadActivity, WhatsAppIntegration
from app.models.masters import Party
from app.schemas.crm import GmailSyncResult, IntegrationStatusRead, WhatsAppIntegrationUpdate
from app.services.fiscal_settings import decrypt_secret, encrypt_secret

settings = get_settings()
GOOGLE_SCOPES = (
    "openid email profile "
    "https://www.googleapis.com/auth/gmail.readonly "
    "https://www.googleapis.com/auth/gmail.send"
)


def _google_configured() -> bool:
    return bool(
        settings.GOOGLE_CLIENT_ID
        and settings.GOOGLE_CLIENT_SECRET
        and settings.GOOGLE_OAUTH_REDIRECT_URI
    )


async def google_integration_for_tenant(
    session: AsyncSession,
    tenant_id: uuid.UUID,
) -> GmailIntegration | None:
    return cast(
        GmailIntegration | None,
        await session.scalar(
            select(GmailIntegration)
            .where(
                GmailIntegration.tenant_id == tenant_id,
                GmailIntegration.active.is_(True),
            )
            .order_by(GmailIntegration.updated_at.desc())
            .limit(1)
        ),
    )


async def integration_status(session: AsyncSession, context: AuthContext) -> IntegrationStatusRead:
    user_id = uuid.UUID(context.actor_id)
    google = await session.scalar(
        select(GmailIntegration).where(
            GmailIntegration.tenant_id == context.tenant_id,
            GmailIntegration.user_id == user_id,
            GmailIntegration.active.is_(True),
        )
    )
    whatsapp = await session.scalar(
        select(WhatsAppIntegration).where(
            WhatsAppIntegration.tenant_id == context.tenant_id,
            WhatsAppIntegration.active.is_(True),
        )
    )
    return IntegrationStatusRead(
        google_connected=bool(google and google.refresh_token_encrypted),
        google_email=google.email if google else None,
        google_last_sync_at=google.last_sync_at if google else None,
        google_configuration_available=_google_configured(),
        whatsapp_connected=whatsapp is not None,
        whatsapp_phone=whatsapp.display_phone_number if whatsapp else None,
    )


async def google_authorization_url(context: AuthContext) -> str:
    if not _google_configured():
        raise HTTPException(status_code=503, detail="Google OAuth is not configured")
    state = secrets.token_urlsafe(32)
    redis = Redis.from_url(settings.REDIS_URL, decode_responses=True)
    try:
        await redis.setex(
            f"iaerp:google-oauth:{state}",
            600,
            json.dumps(
                {
                    "tenant_id": str(context.tenant_id),
                    "user_id": context.actor_id,
                }
            ),
        )
    finally:
        await redis.aclose()
    return "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(
        {
            "client_id": settings.GOOGLE_CLIENT_ID,
            "redirect_uri": settings.GOOGLE_OAUTH_REDIRECT_URI,
            "response_type": "code",
            "scope": GOOGLE_SCOPES,
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
        }
    )


async def complete_google_oauth(session: AsyncSession, *, state: str, code: str) -> None:
    redis = Redis.from_url(settings.REDIS_URL, decode_responses=True)
    try:
        raw = await redis.getdel(f"iaerp:google-oauth:{state}")
    finally:
        await redis.aclose()
    if raw is None or not _google_configured():
        raise HTTPException(status_code=400, detail="Google OAuth state is invalid or expired")
    client_secret = settings.GOOGLE_CLIENT_SECRET
    if client_secret is None:
        raise HTTPException(status_code=503, detail="Google OAuth is not configured")
    payload = json.loads(raw)
    async with httpx.AsyncClient(timeout=30) as client:
        token_response = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": code,
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": client_secret.get_secret_value(),
                "redirect_uri": settings.GOOGLE_OAUTH_REDIRECT_URI,
                "grant_type": "authorization_code",
            },
        )
        if token_response.is_error:
            raise HTTPException(status_code=400, detail="Google authorization failed")
        tokens = token_response.json()
        profile_response = await client.get(
            "https://openidconnect.googleapis.com/v1/userinfo",
            headers={"Authorization": f"Bearer {tokens['access_token']}"},
        )
        profile_response.raise_for_status()
    tenant_id = uuid.UUID(payload["tenant_id"])
    user_id = uuid.UUID(payload["user_id"])
    entity = await session.scalar(
        select(GmailIntegration).where(
            GmailIntegration.tenant_id == tenant_id,
            GmailIntegration.user_id == user_id,
        )
    )
    if entity is None:
        entity = GmailIntegration(
            tenant_id=tenant_id,
            user_id=user_id,
            scopes_granted=tokens.get("scope", GOOGLE_SCOPES).split(),
            sync_enabled=True,
            active=True,
        )
        session.add(entity)
    entity.email = profile_response.json().get("email")
    entity.access_token = None
    entity.refresh_token = None
    entity.access_token_encrypted = encrypt_secret(tokens["access_token"])
    refresh_token = tokens.get("refresh_token")
    if refresh_token:
        entity.refresh_token_encrypted = encrypt_secret(refresh_token)
    entity.token_expires_at = datetime.now(UTC) + timedelta(
        seconds=int(tokens.get("expires_in", 3600))
    )
    entity.active = True
    await session.flush()


async def disconnect_google(session: AsyncSession, context: AuthContext) -> None:
    entity = await session.scalar(
        select(GmailIntegration).where(
            GmailIntegration.tenant_id == context.tenant_id,
            GmailIntegration.user_id == uuid.UUID(context.actor_id),
        )
    )
    if entity:
        entity.active = False
        entity.access_token_encrypted = None
        entity.refresh_token_encrypted = None
        await session.flush()


async def save_whatsapp(
    session: AsyncSession,
    context: AuthContext,
    data: WhatsAppIntegrationUpdate,
) -> None:
    entity = await session.scalar(
        select(WhatsAppIntegration).where(WhatsAppIntegration.tenant_id == context.tenant_id)
    )
    if entity is None:
        entity = WhatsAppIntegration(tenant_id=context.tenant_id)
        session.add(entity)
    entity.business_account_id = data.business_account_id
    entity.phone_number_id = data.phone_number_id
    entity.display_phone_number = data.display_phone_number
    entity.access_token_encrypted = encrypt_secret(data.access_token)
    entity.app_secret_encrypted = encrypt_secret(data.app_secret)
    entity.verify_token_encrypted = encrypt_secret(data.verify_token)
    entity.active = True
    await session.flush()


async def disconnect_whatsapp(session: AsyncSession, context: AuthContext) -> None:
    entity = await session.scalar(
        select(WhatsAppIntegration).where(WhatsAppIntegration.tenant_id == context.tenant_id)
    )
    if entity:
        entity.active = False
        await session.flush()


async def _google_access_token(
    session: AsyncSession, context: AuthContext
) -> tuple[GmailIntegration, str]:
    entity = await session.scalar(
        select(GmailIntegration).where(
            GmailIntegration.tenant_id == context.tenant_id,
            GmailIntegration.user_id == uuid.UUID(context.actor_id),
            GmailIntegration.active.is_(True),
        )
    )
    if not entity or not entity.access_token_encrypted:
        raise HTTPException(status_code=422, detail="Google Workspace is not connected")
    token = decrypt_secret(entity.access_token_encrypted)
    now = datetime.now(UTC)
    expires_at = entity.token_expires_at
    if expires_at and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if expires_at and expires_at > now + timedelta(seconds=30):
        return entity, token
    if not entity.refresh_token_encrypted or not _google_configured():
        raise HTTPException(status_code=422, detail="Google Workspace must be reconnected")
    client_secret = settings.GOOGLE_CLIENT_SECRET
    if client_secret is None:
        raise HTTPException(status_code=503, detail="Google OAuth is not configured")
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": client_secret.get_secret_value(),
                "refresh_token": decrypt_secret(entity.refresh_token_encrypted),
                "grant_type": "refresh_token",
            },
        )
    if response.is_error:
        raise HTTPException(status_code=422, detail="Google Workspace must be reconnected")
    refreshed = response.json()
    token = refreshed["access_token"]
    entity.access_token_encrypted = encrypt_secret(token)
    entity.token_expires_at = now + timedelta(seconds=int(refreshed.get("expires_in", 3600)))
    await session.flush()
    return entity, token


async def send_google_email(
    session: AsyncSession,
    context: AuthContext,
    *,
    recipient: str,
    subject: str,
    message: str,
) -> str:
    entity, token = await _google_access_token(session, context)
    email = EmailMessage()
    email["To"] = recipient
    email["From"] = entity.email or "me"
    email["Subject"] = subject
    email.set_content(message)
    raw = base64.urlsafe_b64encode(email.as_bytes()).decode().rstrip("=")
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
            headers={"Authorization": f"Bearer {token}"},
            json={"raw": raw},
        )
    if response.is_error:
        raise HTTPException(status_code=502, detail="Google could not send the email")
    return str(response.json()["id"])


async def sync_google_inbox(
    session: AsyncSession,
    context: AuthContext,
) -> GmailSyncResult:
    integration, token = await _google_access_token(session, context)
    query = "in:inbox"
    if integration.last_sync_at is not None:
        last_sync = integration.last_sync_at
        if last_sync.tzinfo is None:
            last_sync = last_sync.replace(tzinfo=UTC)
        query += f" after:{int(last_sync.timestamp())}"

    errors: list[str] = []
    messages_processed = 0
    activities_created = 0
    matched_leads: set[uuid.UUID] = set()
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(timeout=30) as client:
        list_response = await client.get(
            "https://gmail.googleapis.com/gmail/v1/users/me/messages",
            headers=headers,
            params={"q": query, "maxResults": 50},
        )
        if list_response.is_error:
            raise HTTPException(status_code=502, detail="Google could not synchronize Gmail")

        for item in list_response.json().get("messages", []):
            message_id = str(item.get("id") or "")
            if not message_id:
                continue
            messages_processed += 1
            existing = await session.scalar(
                select(LeadActivity.id).where(
                    LeadActivity.tenant_id == context.tenant_id,
                    LeadActivity.source_email_id == message_id,
                )
            )
            if existing is not None:
                continue
            try:
                message_response = await client.get(
                    f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{message_id}",
                    headers=headers,
                    params={
                        "format": "metadata",
                        "metadataHeaders": ["From", "Subject"],
                    },
                )
                message_response.raise_for_status()
                message = message_response.json()
                metadata_headers = {
                    str(header.get("name", "")).lower(): str(header.get("value", ""))
                    for header in message.get("payload", {}).get("headers", [])
                }
                sender = parseaddr(metadata_headers.get("from", ""))[1].strip().lower()
                if not sender:
                    continue
                party = await session.scalar(
                    select(Party).where(
                        Party.tenant_id == context.tenant_id,
                        Party.email.isnot(None),
                        Party.email.ilike(sender),
                        Party.active.is_(True),
                    )
                )
                if party is None:
                    continue
                lead = await session.scalar(
                    select(Lead)
                    .where(
                        Lead.tenant_id == context.tenant_id,
                        Lead.party_id == party.id,
                    )
                    .order_by(Lead.created_at.desc())
                    .limit(1)
                )
                if lead is None:
                    continue
                session.add(
                    LeadActivity(
                        tenant_id=context.tenant_id,
                        lead_id=lead.id,
                        actor_id=context.actor_id,
                        activity_type="EMAIL",
                        subject=metadata_headers.get("subject") or "Correo recibido",
                        description=str(message.get("snippet") or ""),
                        outcome="PENDING",
                        source_email_id=message_id,
                        source_email_thread_id=str(message.get("threadId") or "") or None,
                    )
                )
                activities_created += 1
                matched_leads.add(lead.id)
            except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
                errors.append(f"{message_id}: {type(exc).__name__}")

    sync_time = datetime.now(UTC)
    integration.last_sync_at = sync_time
    await session.flush()
    return GmailSyncResult(
        messages_processed=messages_processed,
        activities_created=activities_created,
        leads_matched=len(matched_leads),
        errors=errors,
        last_sync_at=sync_time,
    )


async def send_whatsapp_message(
    session: AsyncSession,
    context: AuthContext,
    *,
    recipient: str,
    message: str,
    template_id: str | None,
) -> str:
    entity = await session.scalar(
        select(WhatsAppIntegration).where(
            WhatsAppIntegration.tenant_id == context.tenant_id,
            WhatsAppIntegration.active.is_(True),
        )
    )
    if entity is None:
        raise HTTPException(status_code=422, detail="WhatsApp is not connected")
    body: dict[str, object]
    if template_id:
        body = {
            "messaging_product": "whatsapp",
            "to": recipient,
            "type": "template",
            "template": {"name": template_id, "language": {"code": "es"}},
        }
    else:
        body = {
            "messaging_product": "whatsapp",
            "to": recipient,
            "type": "text",
            "text": {"body": message},
        }
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            f"https://graph.facebook.com/{settings.WHATSAPP_GRAPH_VERSION}/{entity.phone_number_id}/messages",
            headers={"Authorization": f"Bearer {decrypt_secret(entity.access_token_encrypted)}"},
            json=body,
        )
    if response.is_error:
        raise HTTPException(status_code=502, detail="Meta could not send the WhatsApp message")
    return str(response.json()["messages"][0]["id"])


def valid_meta_signature(raw_body: bytes, signature: str, app_secret: str) -> bool:
    expected = "sha256=" + hmac.new(app_secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


async def verify_whatsapp_token(session: AsyncSession, token: str) -> bool:
    entities = await session.scalars(
        select(WhatsAppIntegration).where(WhatsAppIntegration.active.is_(True))
    )
    return any(
        hmac.compare_digest(decrypt_secret(item.verify_token_encrypted), token) for item in entities
    )


async def process_whatsapp_webhook(
    session: AsyncSession,
    *,
    raw_body: bytes,
    signature: str,
    payload: dict[str, object],
) -> int:
    entries = payload.get("entry")
    if not isinstance(entries, list):
        return 0
    phone_number_id: str | None = None
    messages: list[dict[str, object]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        for change in entry.get("changes", []):
            if not isinstance(change, dict) or not isinstance(change.get("value"), dict):
                continue
            value = change["value"]
            metadata = value.get("metadata")
            if isinstance(metadata, dict):
                phone_number_id = str(metadata.get("phone_number_id") or "")
            messages.extend(item for item in value.get("messages", []) if isinstance(item, dict))
    if not phone_number_id:
        return 0
    integration = await session.scalar(
        select(WhatsAppIntegration).where(
            WhatsAppIntegration.phone_number_id == phone_number_id,
            WhatsAppIntegration.active.is_(True),
        )
    )
    if integration is None or not valid_meta_signature(
        raw_body, signature, decrypt_secret(integration.app_secret_encrypted)
    ):
        raise HTTPException(status_code=401, detail="Invalid Meta webhook signature")
    created = 0
    parties = list(
        await session.scalars(
            select(Party).where(
                Party.tenant_id == integration.tenant_id,
                Party.active.is_(True),
            )
        )
    )
    parties_by_phone = {
        "".join(character for character in (party.phone or "") if character.isdigit()): party
        for party in parties
        if party.phone
    }
    for message in messages:
        sender = "".join(
            character for character in str(message.get("from") or "") if character.isdigit()
        )
        party = parties_by_phone.get(sender)
        if party is None:
            continue
        lead = await session.scalar(
            select(Lead)
            .where(
                Lead.tenant_id == integration.tenant_id,
                Lead.party_id == party.id,
            )
            .order_by(Lead.created_at.desc())
        )
        if lead is None:
            continue
        text_payload = message.get("text")
        description = (
            str(text_payload.get("body"))
            if isinstance(text_payload, dict)
            else "Mensaje recibido por WhatsApp"
        )
        session.add(
            LeadActivity(
                tenant_id=integration.tenant_id,
                lead_id=lead.id,
                actor_id="whatsapp-webhook",
                activity_type="WHATSAPP",
                subject="WhatsApp entrante",
                description=description,
                outcome="PENDING",
                source_email_id=str(message.get("id") or "") or None,
            )
        )
        created += 1
    await session.flush()
    return created
