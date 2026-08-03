from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from email.utils import formataddr, parseaddr
from typing import cast
from urllib.parse import urlencode

import httpx
from fastapi import HTTPException
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthContext
from app.core.config import get_settings
from app.core.phone import normalize_ecuador_whatsapp
from app.models.crm import (
    EvolutionWhatsAppIntegration,
    GmailIntegration,
    Lead,
    LeadActivity,
    WhatsAppIntegration,
    WhatsAppRoutingPolicy,
)
from app.models.masters import Party
from app.schemas.crm import (
    EvolutionWhatsAppIntegrationRead,
    EvolutionWhatsAppIntegrationUpdate,
    GmailSyncResult,
    IntegrationStatusRead,
    WhatsAppIntegrationUpdate,
    WhatsAppRoutingUpdate,
)
from app.services.fiscal_settings import decrypt_secret, encrypt_secret

settings = get_settings()
GOOGLE_SCOPES = (
    "openid email profile "
    "https://www.googleapis.com/auth/gmail.readonly "
    "https://www.googleapis.com/auth/gmail.send"
)


@dataclass(frozen=True)
class GoogleSentMessage:
    message_id: str
    thread_id: str


@dataclass(frozen=True)
class GoogleThreadPdf:
    message_id: str
    sender: str
    snippet: str
    file_name: str
    data: bytes


def _evolution_configured() -> bool:
    return bool(settings.EVOLUTION_API_BASE_URL and settings.EVOLUTION_API_KEY)


def _evolution_api_key() -> str:
    if not settings.EVOLUTION_API_KEY:
        raise HTTPException(
            status_code=503, detail="Evolution API is not configured by the platform"
        )
    return settings.EVOLUTION_API_KEY.get_secret_value()


def _evolution_headers() -> dict[str, str]:
    return {"apikey": _evolution_api_key()}


def _public_api_url() -> str:
    return (settings.PUBLIC_API_URL or f"{settings.PUBLIC_APP_URL.rstrip('/')}/api/v1").rstrip("/")


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
    evolution = await session.scalar(
        select(EvolutionWhatsAppIntegration).where(
            EvolutionWhatsAppIntegration.tenant_id == context.tenant_id,
            EvolutionWhatsAppIntegration.active.is_(True),
        )
    )
    routing = await _routing_for_tenant(session, context.tenant_id)
    return IntegrationStatusRead(
        google_connected=bool(google and google.refresh_token_encrypted),
        google_email=google.email if google else None,
        google_last_sync_at=google.last_sync_at if google else None,
        google_configuration_available=_google_configured(),
        whatsapp_connected=whatsapp is not None,
        whatsapp_phone=whatsapp.display_phone_number if whatsapp else None,
        whatsapp_meta_connected=whatsapp is not None,
        whatsapp_evolution_connected=evolution is not None,
        whatsapp_evolution_phone=evolution.display_phone_number if evolution else None,
        evolution_configuration_available=_evolution_configured(),
        whatsapp_crm_provider=routing.crm_provider,
        whatsapp_collections_provider=routing.collections_provider,
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


async def save_evolution_whatsapp(
    session: AsyncSession,
    context: AuthContext,
    data: EvolutionWhatsAppIntegrationUpdate,
) -> EvolutionWhatsAppIntegrationRead:
    if not _evolution_configured():
        raise HTTPException(
            status_code=503, detail="Evolution API is not configured by the platform"
        )
    entity = await session.scalar(
        select(EvolutionWhatsAppIntegration).where(
            EvolutionWhatsAppIntegration.tenant_id == context.tenant_id
        )
    )
    if entity is None:
        entity = EvolutionWhatsAppIntegration(
            tenant_id=context.tenant_id,
            webhook_token_encrypted=encrypt_secret(secrets.token_urlsafe(32)),
        )
        session.add(entity)
    entity.instance_name = data.instance_name
    entity.display_phone_number = data.display_phone_number
    # Esta es una credencial de plataforma. Nunca se recibe ni devuelve al
    # navegador; el valor cifrado solo preserva compatibilidad con el modelo.
    entity.api_key_encrypted = encrypt_secret(_evolution_api_key())
    entity.active = True
    await session.flush()
    qr_code = await _configure_evolution_instance(entity)
    return EvolutionWhatsAppIntegrationRead(
        connected=True,
        display_phone_number=entity.display_phone_number,
        webhook_url=_evolution_webhook_url(entity),
        qr_code=qr_code,
        qr_expires_in_seconds=30 if qr_code else None,
    )


async def disconnect_evolution_whatsapp(session: AsyncSession, context: AuthContext) -> None:
    entity = await session.scalar(
        select(EvolutionWhatsAppIntegration).where(
            EvolutionWhatsAppIntegration.tenant_id == context.tenant_id
        )
    )
    if entity:
        entity.active = False
        await session.flush()


async def update_whatsapp_routing(
    session: AsyncSession,
    context: AuthContext,
    data: WhatsAppRoutingUpdate,
) -> None:
    routing = await session.get(WhatsAppRoutingPolicy, context.tenant_id)
    if routing is None:
        routing = WhatsAppRoutingPolicy(tenant_id=context.tenant_id)
        session.add(routing)
    routing.crm_provider = data.crm_provider
    routing.collections_provider = data.collections_provider
    await session.flush()


async def _routing_for_tenant(session: AsyncSession, tenant_id: uuid.UUID) -> WhatsAppRoutingPolicy:
    routing = await session.get(WhatsAppRoutingPolicy, tenant_id)
    return routing or WhatsAppRoutingPolicy(
        tenant_id=tenant_id,
        crm_provider="META",
        collections_provider="META",
    )


def _evolution_webhook_url(entity: EvolutionWhatsAppIntegration) -> str:
    token = decrypt_secret(entity.webhook_token_encrypted)
    return f"{_public_api_url()}/crm/webhooks/whatsapp/evolution/{entity.id}/{token}"


async def _configure_evolution_instance(entity: EvolutionWhatsAppIntegration) -> str | None:
    """Crea/reutiliza una instancia y deja el webhook tenant-safe configurado."""
    base_url = str(settings.EVOLUTION_API_BASE_URL).rstrip("/")
    headers = _evolution_headers()
    create_payload = {
        "instanceName": entity.instance_name,
        "integration": "WHATSAPP-BAILEYS",
        "qrcode": True,
    }
    webhook_payload = {
        "webhook": {
            "enabled": True,
            "url": _evolution_webhook_url(entity),
            "byEvents": False,
            "base64": False,
            "events": ["MESSAGES_UPSERT"],
        }
    }
    async with httpx.AsyncClient(timeout=30) as client:
        created = await client.post(
            f"{base_url}/instance/create", headers=headers, json=create_payload
        )
        if created.status_code not in {200, 201, 409}:
            raise HTTPException(
                status_code=502, detail="Evolution could not create the WhatsApp instance"
            )
        webhook = await client.post(
            f"{base_url}/webhook/set/{entity.instance_name}",
            headers=headers,
            json=webhook_payload,
        )
        if webhook.is_error:
            raise HTTPException(status_code=502, detail="Evolution could not configure the webhook")
        for attempt in range(3):
            qr_response = await client.get(
                f"{base_url}/instance/connect/{entity.instance_name}", headers=headers
            )
            if not qr_response.is_error:
                payload = qr_response.json()
                qr_code = payload.get("base64") if isinstance(payload, dict) else None
                if isinstance(qr_code, str):
                    return qr_code
            if attempt < 2:
                await asyncio.sleep(1)
    return None


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
    html_message: str | None = None,
    attachments: list[tuple[str, str, bytes]] | None = None,
    sender_address: str | None = None,
    sender_name: str | None = None,
    reply_to: str | None = None,
) -> str:
    sent = await send_google_email_with_thread(
        session,
        context,
        recipient=recipient,
        subject=subject,
        message=message,
        html_message=html_message,
        attachments=attachments,
    )
    return sent.message_id


async def send_google_email_with_thread(
    session: AsyncSession,
    context: AuthContext,
    *,
    recipient: str,
    subject: str,
    message: str,
    html_message: str | None = None,
    attachments: list[tuple[str, str, bytes]] | None = None,
) -> GoogleSentMessage:
    entity, token = await _google_access_token(session, context)
    email = EmailMessage()
    email["To"] = recipient
    from_address = sender_address or entity.email or "me"
    email["From"] = formataddr((sender_name or "", from_address))
    if reply_to:
        email["Reply-To"] = reply_to
    email["Subject"] = subject
    email.set_content(message)
    if html_message:
        email.add_alternative(html_message, subtype="html")
    for file_name, content_type, data in attachments or []:
        maintype, subtype = content_type.split("/", 1)
        email.add_attachment(data, maintype=maintype, subtype=subtype, filename=file_name)
    raw = base64.urlsafe_b64encode(email.as_bytes()).decode().rstrip("=")
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
            headers={"Authorization": f"Bearer {token}"},
            json={"raw": raw},
        )
    if response.is_error:
        if sender_address:
            raise HTTPException(
                status_code=502,
                detail=(
                    "Google could not send from the configured alias. "
                    "Verify it under Gmail 'Send mail as'."
                ),
            )
        raise HTTPException(status_code=502, detail="Google could not send the email")
    payload = response.json()
    return GoogleSentMessage(
        message_id=str(payload["id"]),
        thread_id=str(payload["threadId"]),
    )


def _gmail_pdf_parts(payload: dict[str, object]) -> list[dict[str, object]]:
    found: list[dict[str, object]] = []
    stack = [payload]
    while stack:
        part = stack.pop()
        mime_type = str(part.get("mimeType") or "").lower()
        file_name = str(part.get("filename") or "")
        if mime_type == "application/pdf" or file_name.lower().endswith(".pdf"):
            found.append(part)
        children = part.get("parts")
        if isinstance(children, list):
            stack.extend(child for child in children if isinstance(child, dict))
    return found


async def google_thread_pdfs(
    session: AsyncSession,
    context: AuthContext,
    *,
    thread_id: str,
    max_bytes: int,
) -> tuple[int, list[tuple[str, str]], list[GoogleThreadPdf]]:
    """Lee solo el hilo conocido de un contrato y devuelve sus PDF adjuntos."""
    _, token = await _google_access_token(session, context)
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(
            f"https://gmail.googleapis.com/gmail/v1/users/me/threads/{thread_id}",
            headers=headers,
            params={"format": "full"},
        )
        if response.is_error:
            raise HTTPException(status_code=502, detail="Google could not read the contract thread")
        thread = response.json()
        if str(thread.get("id") or "") != thread_id:
            raise HTTPException(status_code=502, detail="Google returned an unexpected thread")
        messages = thread.get("messages", [])
        if not isinstance(messages, list):
            return 0, [], []
        pdfs: list[GoogleThreadPdf] = []
        message_senders: list[tuple[str, str]] = []
        for raw_message in messages:
            if not isinstance(raw_message, dict):
                continue
            message_id = str(raw_message.get("id") or "")
            payload = raw_message.get("payload")
            if not message_id or not isinstance(payload, dict):
                continue
            metadata = {
                str(item.get("name", "")).lower(): str(item.get("value", ""))
                for item in payload.get("headers", [])
                if isinstance(item, dict)
            }
            sender = parseaddr(metadata.get("from", ""))[1].strip().lower()
            message_senders.append((message_id, sender))
            for part in _gmail_pdf_parts(payload):
                body = part.get("body")
                if not isinstance(body, dict):
                    continue
                encoded = body.get("data")
                attachment_id = body.get("attachmentId")
                if not encoded and attachment_id:
                    attachment = await client.get(
                        "https://gmail.googleapis.com/gmail/v1/users/me/messages/"
                        f"{message_id}/attachments/{attachment_id}",
                        headers=headers,
                    )
                    if attachment.is_error:
                        continue
                    encoded = attachment.json().get("data")
                if not isinstance(encoded, str):
                    continue
                try:
                    data = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
                except ValueError:
                    continue
                if len(data) > max_bytes:
                    continue
                pdfs.append(
                    GoogleThreadPdf(
                        message_id=message_id,
                        sender=sender,
                        snippet=str(raw_message.get("snippet") or "")[:500],
                        file_name=str(part.get("filename") or "contrato-firmado.pdf"),
                        data=data,
                    )
                )
        return len(messages), message_senders, pdfs


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
    purpose: str,
) -> str:
    try:
        recipient_digits = normalize_ecuador_whatsapp(recipient).lstrip("+")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    routing = await _routing_for_tenant(session, context.tenant_id)
    provider = routing.collections_provider if purpose == "COLLECTIONS" else routing.crm_provider
    if provider == "EVOLUTION":
        return await _send_evolution_whatsapp_message(
            session,
            context,
            recipient=recipient_digits,
            message=message,
        )
    return await _send_meta_whatsapp_message(
        session,
        context,
        recipient=recipient_digits,
        message=message,
        template_id=template_id,
    )


async def _send_meta_whatsapp_message(
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


async def _send_evolution_whatsapp_message(
    session: AsyncSession,
    context: AuthContext,
    *,
    recipient: str,
    message: str,
) -> str:
    if not _evolution_configured():
        raise HTTPException(
            status_code=503, detail="Evolution API is not configured by the platform"
        )
    entity = await session.scalar(
        select(EvolutionWhatsAppIntegration).where(
            EvolutionWhatsAppIntegration.tenant_id == context.tenant_id,
            EvolutionWhatsAppIntegration.active.is_(True),
        )
    )
    if entity is None:
        raise HTTPException(status_code=422, detail="Evolution WhatsApp is not connected")
    number = recipient
    base_url = str(settings.EVOLUTION_API_BASE_URL).rstrip("/")
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            f"{base_url}/message/sendText/{entity.instance_name}",
            headers=_evolution_headers(),
            json={"number": number, "text": message},
        )
    if response.is_error:
        raise HTTPException(status_code=502, detail="Evolution could not send the WhatsApp message")
    payload = response.json()
    key = payload.get("key") if isinstance(payload, dict) else None
    return str(key.get("id") if isinstance(key, dict) else payload.get("id") or "evolution-message")


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


async def process_evolution_whatsapp_webhook(
    session: AsyncSession,
    *,
    integration_id: uuid.UUID,
    webhook_token: str,
    payload: dict[str, object],
) -> int:
    """Registra mensajes entrantes Evolution; los payloads son datos no confiables."""
    integration = await session.scalar(
        select(EvolutionWhatsAppIntegration).where(
            EvolutionWhatsAppIntegration.id == integration_id,
            EvolutionWhatsAppIntegration.active.is_(True),
        )
    )
    if integration is None or not hmac.compare_digest(
        decrypt_secret(integration.webhook_token_encrypted), webhook_token
    ):
        raise HTTPException(status_code=401, detail="Invalid Evolution webhook token")
    if payload.get("event") != "MESSAGES_UPSERT":
        return 0
    data = payload.get("data")
    if not isinstance(data, dict):
        return 0
    key = data.get("key")
    if not isinstance(key, dict) or bool(key.get("fromMe")):
        return 0
    source_message_id = str(key.get("id") or "")
    if not source_message_id:
        return 0
    existing = await session.scalar(
        select(LeadActivity.id).where(
            LeadActivity.tenant_id == integration.tenant_id,
            LeadActivity.source_email_id == source_message_id,
        )
    )
    if existing is not None:
        return 0
    sender = "".join(
        character
        for character in str(key.get("remoteJid") or "").split("@", 1)[0]
        if character.isdigit()
    )
    if not sender:
        return 0
    parties = list(
        await session.scalars(
            select(Party).where(
                Party.tenant_id == integration.tenant_id,
                Party.active.is_(True),
            )
        )
    )
    party = next(
        (
            candidate
            for candidate in parties
            if "".join(character for character in (candidate.phone or "") if character.isdigit())
            == sender
        ),
        None,
    )
    if party is None:
        return 0
    lead = await session.scalar(
        select(Lead)
        .where(Lead.tenant_id == integration.tenant_id, Lead.party_id == party.id)
        .order_by(Lead.created_at.desc())
        .limit(1)
    )
    if lead is None:
        return 0
    message = data.get("message")
    description = "Mensaje recibido por WhatsApp"
    if isinstance(message, dict):
        description = str(
            message.get("conversation")
            or (message.get("extendedTextMessage") or {}).get("text")
            or description
        )
    session.add(
        LeadActivity(
            tenant_id=integration.tenant_id,
            lead_id=lead.id,
            actor_id="evolution-webhook",
            activity_type="WHATSAPP",
            subject="WhatsApp entrante",
            description=description,
            outcome="PENDING",
            source_email_id=source_message_id,
        )
    )
    await session.flush()
    return 1
