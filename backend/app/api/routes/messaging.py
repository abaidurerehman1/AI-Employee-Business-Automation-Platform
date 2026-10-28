import asyncio
import hmac
import json
import re
import uuid
from datetime import UTC, datetime, timedelta
from email.utils import parseaddr
from typing import Annotated, Literal
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, EmailStr, Field, TypeAdapter, ValidationError
import httpx
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from svix.webhooks import Webhook, WebhookVerificationError
from twilio.request_validator import RequestValidator
from app.api.dependencies import DbSession, TenantContext, require_csrf, require_permission
from app.models.auth import Organization, User
from app.core.config import settings
from app.core.messaging_delivery import unsubscribe_signature
from app.models.messaging import GmailConnection, MessageEvent, MessageTemplate, OutboundMessage, Suppression
from app.worker import deliver_message_task

router = APIRouter(prefix="/messaging", tags=["messaging"])
Tenant = Annotated[TenantContext, Depends(require_permission("integrations.manage"))]
Manager = Annotated[TenantContext, Depends(require_permission("integrations.manage"))]
Csrf = Annotated[User, Depends(require_csrf)]


class MessageInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    channel: Literal["email", "sms"]
    recipient: str = Field(min_length=3, max_length=320)
    subject: str = Field(default="", max_length=200)
    body: str = Field(min_length=1, max_length=10000)
    idempotency_key: str = Field(min_length=1, max_length=120)
    consent_confirmed: Literal[True]


class TemplateInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=120)
    channel: Literal["email", "sms"]
    subject: str = Field(default="", max_length=200)
    body: str = Field(min_length=1, max_length=10000)


class SuppressInput(BaseModel):
    channel: Literal["email", "sms"]
    recipient: str = Field(min_length=3, max_length=320)


def normalize(channel: str, recipient: str) -> str:
    if channel == "email":
        try:
            return str(TypeAdapter(EmailStr).validate_python(recipient)).lower()
        except ValidationError as exc:
            raise HTTPException(422, "Invalid email address") from exc
    number = re.sub(r"[\s().-]", "", recipient)
    if not re.fullmatch(r"\+[1-9][0-9]{7,14}", number):
        raise HTTPException(422, "SMS numbers must use international format, e.g. +12345678901")
    return number


def render(record):
    return {col.name: getattr(record, col.name) for col in record.__table__.columns}


@router.get("/providers")
async def provider_status(db: DbSession, context: Manager):
    status = "not_configured"
    if settings.resend_api_key and settings.resend_from_email:
        sender = parseaddr(settings.resend_from_email)[1]
        domain = sender.rsplit("@", 1)[-1].lower() if "@" in sender else ""
        try:
            async with httpx.AsyncClient(timeout=8) as client:
                response = await client.get("https://api.resend.com/domains", headers={"Authorization": f"Bearer {settings.resend_api_key}"})
                response.raise_for_status()
                domains = response.json().get("data", [])
            status = "verified" if any(item.get("name", "").lower() == domain and item.get("status") == "verified" for item in domains) else "unverified"
        except (httpx.HTTPError, ValueError):
            status = "unavailable"
    gmail = await db.scalar(select(GmailConnection).where(GmailConnection.organization_id == context.organization.id))
    return {"gmail": {"connected": bool(gmail), "email": gmail.email if gmail else None,
        "oauth_configured": bool(settings.google_client_id and settings.google_client_secret and settings.oauth_encryption_key)},
        "email": {"sender": settings.resend_from_email or None, "domain_status": status,
        "unsubscribe_configured": bool(settings.messaging_unsubscribe_secret and settings.messaging_public_base_url)},
        "sms": {"configured": bool(settings.twilio_account_sid and settings.twilio_auth_token and settings.twilio_from_number)}}


@router.get("/templates")
async def list_templates(db: DbSession, context: Tenant):
    items = (await db.scalars(select(MessageTemplate).where(MessageTemplate.organization_id == context.organization.id).order_by(MessageTemplate.created_at.desc()))).all()
    return [render(item) for item in items]


@router.post("/templates", status_code=201)
async def create_template(payload: TemplateInput, db: DbSession, context: Manager, _user: Csrf):
    if payload.channel == "email" and not payload.subject:
        raise HTTPException(422, "Email subject is required")
    if payload.channel == "sms" and len(payload.body) > 1560:
        raise HTTPException(422, "SMS body is too long")
    item = MessageTemplate(organization_id=context.organization.id, **payload.model_dump())
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return render(item)


@router.get("/messages")
async def list_messages(db: DbSession, context: Manager):
    items = (await db.scalars(select(OutboundMessage).where(OutboundMessage.organization_id == context.organization.id).order_by(OutboundMessage.created_at.desc()).limit(100))).all()
    return [render(item) for item in items]


@router.post("/messages", status_code=202)
async def queue_message(payload: MessageInput, db: DbSession, context: Manager, _user: Csrf):
    recipient = normalize(payload.channel, payload.recipient)
    if payload.channel == "email" and not payload.subject:
        raise HTTPException(422, "Email subject is required")
    if payload.channel == "sms" and len(payload.body) > 1560:
        raise HTTPException(422, "SMS body is too long")
    existing = await db.scalar(select(OutboundMessage).where(OutboundMessage.organization_id == context.organization.id, OutboundMessage.idempotency_key == payload.idempotency_key))
    if existing:
        if (existing.channel, existing.recipient, existing.subject, existing.body) != (payload.channel, recipient, payload.subject, payload.body):
            raise HTTPException(409, "Idempotency key was used for a different message")
        return render(existing)
    suppressed = await db.scalar(select(Suppression.id).where(Suppression.organization_id == context.organization.id, Suppression.channel == payload.channel, Suppression.recipient == recipient))
    if suppressed:
        raise HTTPException(409, "Recipient is suppressed")
    await db.scalar(select(Organization).where(Organization.id == context.organization.id).with_for_update())
    count = await db.scalar(select(func.count(OutboundMessage.id)).where(
        OutboundMessage.organization_id == context.organization.id,
        OutboundMessage.created_at >= datetime.now(UTC) - timedelta(hours=1)))
    if count >= settings.messaging_hourly_limit:
        raise HTTPException(429, "Hourly message limit reached")
    item = OutboundMessage(organization_id=context.organization.id, created_by=context.user.id, channel=payload.channel,
        recipient=recipient, subject=payload.subject, body=payload.body, idempotency_key=payload.idempotency_key, status="queued", attempt_count=0)
    db.add(item)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(409, "Message request already exists") from exc
    await db.refresh(item)
    try:
        await asyncio.to_thread(deliver_message_task.delay, str(item.id))
    except Exception as exc:
        await db.refresh(item, with_for_update=True)
        if item.status == "queued":
            item.status, item.error_message = "failed", "Unable to queue message."
            await db.commit()
        raise HTTPException(503, "Unable to confirm queue submission; check message status before retrying") from exc
    return render(item)


@router.api_route("/unsubscribe/{message_id}", methods=["GET", "POST"])
async def unsubscribe(message_id: uuid.UUID, db: DbSession, signature: str = Query(max_length=100)):
    if not settings.messaging_unsubscribe_secret or not re.fullmatch(r"[0-9a-f]{64}", signature) or not hmac.compare_digest(unsubscribe_signature(message_id), signature):
        raise HTTPException(404, "Unsubscribe link is invalid")
    message = await db.get(OutboundMessage, message_id)
    if not message or message.channel != "email":
        raise HTTPException(404, "Unsubscribe link is invalid")
    existing = await db.scalar(select(Suppression.id).where(Suppression.organization_id == message.organization_id,
        Suppression.channel == message.channel, Suppression.recipient == message.recipient))
    if not existing:
        db.add(Suppression(organization_id=message.organization_id, channel=message.channel, recipient=message.recipient, reason="unsubscribe"))
    from app.core.campaigns import record_optout
    await record_optout(db, message.organization_id, message.channel, message.recipient, "unsubscribe", message.id)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
    return {"message": "You have been unsubscribed."}


@router.post("/messages/{message_id}/retry", status_code=202)
async def retry_message(message_id: uuid.UUID, db: DbSession, context: Manager, _user: Csrf):
    from app.models.campaign import CampaignRecipient
    if await db.scalar(select(CampaignRecipient.id).where(CampaignRecipient.message_id == message_id, CampaignRecipient.organization_id == context.organization.id)):
        raise HTTPException(409, "Campaign delivery is controlled through the approved campaign workflow")
    item = await db.scalar(select(OutboundMessage).where(OutboundMessage.id == message_id,
        OutboundMessage.organization_id == context.organization.id).with_for_update())
    if not item:
        raise HTTPException(404, "Message not found")
    if item.status != "failed" or item.provider_id:
        raise HTTPException(409, "Only messages known not to have been sent can be retried")
    if item.attempt_count >= 3:
        raise HTTPException(409, "Message retry limit reached")
    item.status, item.error_message = "queued", None
    await db.commit()
    try:
        await asyncio.to_thread(deliver_message_task.delay, str(item.id))
    except Exception as exc:
        raise HTTPException(503, "Unable to queue message; check status before trying again") from exc
    return render(item)


@router.get("/suppressions")
async def list_suppressions(db: DbSession, context: Manager):
    items = (await db.scalars(select(Suppression).where(Suppression.organization_id == context.organization.id).order_by(Suppression.created_at.desc()).limit(100))).all()
    return [render(item) for item in items]


@router.post("/suppressions", status_code=201)
async def add_suppression(payload: SuppressInput, db: DbSession, context: Manager, _user: Csrf):
    recipient = normalize(payload.channel, payload.recipient)
    existing = await db.scalar(select(Suppression).where(Suppression.organization_id == context.organization.id, Suppression.channel == payload.channel, Suppression.recipient == recipient))
    if existing:
        return render(existing)
    item = Suppression(organization_id=context.organization.id, channel=payload.channel, recipient=recipient, reason="manual")
    db.add(item)
    from app.core.campaigns import record_optout
    await record_optout(db, context.organization.id, payload.channel, recipient, "manual")
    await db.commit()
    await db.refresh(item)
    return render(item)


@router.get("/events")
async def list_events(db: DbSession, context: Manager):
    items = (await db.scalars(select(MessageEvent).where(MessageEvent.organization_id == context.organization.id).order_by(MessageEvent.created_at.desc()).limit(100))).all()
    return [render(item) for item in items]


async def suppress(db, message, reason):
    from app.core.campaigns import record_optout
    await record_optout(db, message.organization_id, message.channel, message.recipient, reason)
    existing = await db.scalar(select(Suppression.id).where(Suppression.organization_id == message.organization_id,
        Suppression.channel == message.channel, Suppression.recipient == message.recipient))
    if not existing:
        db.add(Suppression(organization_id=message.organization_id, channel=message.channel, recipient=message.recipient, reason=reason))


@router.post("/webhooks/resend")
async def resend_webhook(request: Request, db: DbSession):
    if not settings.resend_webhook_secret:
        raise HTTPException(503, "Webhook not configured")
    raw = await request.body()
    if len(raw) > 262144:
        raise HTTPException(413, "Payload too large")
    try:
        Webhook(settings.resend_webhook_secret).verify(raw, dict(request.headers))
        payload = json.loads(raw)
        event_id = request.headers["svix-id"]
        kind = payload["type"]
        provider_id = payload["data"]["email_id"]
    except (WebhookVerificationError, ValueError, KeyError, TypeError) as exc:
        raise HTTPException(401, "Invalid webhook") from exc
    if await db.scalar(select(MessageEvent.id).where(MessageEvent.provider == "resend", MessageEvent.event_id == event_id)):
        return {"status": "already_received"}
    if kind == "email.received":
        if not settings.resend_api_key:
            raise HTTPException(503, "Email provider not configured")
        sender = parseaddr(str(payload["data"].get("from", "")))[1].lower()
        organizations = (await db.scalars(select(OutboundMessage.organization_id).where(
            OutboundMessage.channel == "email", OutboundMessage.recipient == sender).distinct().limit(2))).all()
        if len(organizations) != 1:
            return {"status": "unmatched"}
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                response = await client.get(f"https://api.resend.com/emails/receiving/{provider_id}", headers={"Authorization": f"Bearer {settings.resend_api_key}"})
                response.raise_for_status()
                received = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise HTTPException(503, "Unable to retrieve incoming email") from exc
        candidates = (await db.scalars(select(OutboundMessage).where(OutboundMessage.channel == "email",
            OutboundMessage.recipient == sender, OutboundMessage.organization_id == organizations[0]).limit(2))).all()
        if len(candidates) != 1:
            return {"status": "unmatched"}
        message = candidates[0]
        db.add(MessageEvent(organization_id=message.organization_id, message_id=message.id, provider="resend",
            event_id=event_id, kind="reply", content=str(received.get("text") or "(No plain-text body)")[:10000]))
        from app.core.campaigns import record_crm_event
        await record_crm_event(db, message, "reply")
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
        return {"status": "received"}
    message = await db.scalar(select(OutboundMessage).where(OutboundMessage.provider_id == provider_id, OutboundMessage.channel == "email").with_for_update())
    if not message:
        raise HTTPException(503, "Message not yet available")
    state = {"email.delivered": "delivered", "email.bounced": "bounced", "email.complained": "complained", "email.failed": "failed"}.get(kind)
    rank = {"failed": 1, "delivered": 2, "bounced": 3, "complained": 4}
    if state and rank.get(state, 0) > rank.get(message.status, 0):
        message.status = state
    if state in {"bounced", "complained"}:
        await suppress(db, message, state)
    db.add(MessageEvent(organization_id=message.organization_id, message_id=message.id, provider="resend", event_id=event_id, kind=kind))
    from app.core.campaigns import record_crm_event
    await record_crm_event(db, message, kind)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
    return {"status": "received"}


@router.post("/webhooks/twilio/{organization_id}")
async def twilio_webhook(organization_id: uuid.UUID, request: Request, db: DbSession):
    if not settings.twilio_auth_token or not settings.messaging_public_base_url:
        raise HTTPException(503, "Webhook not configured")
    if len(await request.body()) > 262144:
        raise HTTPException(413, "Payload too large")
    form = await request.form()
    params = dict(form)
    url = f"{settings.messaging_public_base_url.rstrip('/')}/api/v1/messaging/webhooks/twilio/{organization_id}"
    if not RequestValidator(settings.twilio_auth_token).validate(url, params, request.headers.get("X-Twilio-Signature", "")):
        raise HTTPException(403, "Invalid webhook")
    sid = params.get("MessageSid", "")
    state = params.get("MessageStatus", "")
    if not sid:
        raise HTTPException(400, "Missing message ID")
    incoming = "Body" in params and not state
    event_id = f"{organization_id}:{sid}:{'inbound' if incoming else state}"
    if await db.scalar(select(MessageEvent.id).where(MessageEvent.provider == "twilio", MessageEvent.event_id == event_id)):
        return Response(content="<Response/>", media_type="application/xml")
    if incoming:
        recipient = normalize("sms", params.get("From", ""))
        message = await db.scalar(select(OutboundMessage).where(OutboundMessage.organization_id == organization_id,
            OutboundMessage.channel == "sms", OutboundMessage.recipient == recipient).order_by(OutboundMessage.created_at.desc()).limit(1))
        body = str(params.get("Body", ""))[:10000]
        is_optout = body.strip().upper() in {"STOP", "STOPALL", "UNSUBSCRIBE", "CANCEL", "END", "QUIT"}
        if not message and not is_optout:
            return Response(content="<Response/>", media_type="application/xml")
        if is_optout:
            from app.core.campaigns import record_optout
            await record_optout(db, organization_id, "sms", recipient, "opt_out", message.id if message else None)
            existing = await db.scalar(select(Suppression.id).where(Suppression.organization_id == organization_id,
                Suppression.channel == "sms", Suppression.recipient == recipient))
            if not existing:
                db.add(Suppression(organization_id=organization_id, channel="sms", recipient=recipient, reason="opt_out"))
        db.add(MessageEvent(organization_id=organization_id, message_id=message.id if message else None, provider="twilio", event_id=event_id, kind="reply", content=body))
        if message:
            from app.core.campaigns import record_crm_event
            await record_crm_event(db, message, "reply")
    else:
        message = await db.scalar(select(OutboundMessage).where(OutboundMessage.organization_id == organization_id,
            OutboundMessage.provider_id == sid, OutboundMessage.channel == "sms").with_for_update())
        if not message:
            raise HTTPException(503, "Message not yet available")
        if state in {"delivered", "failed", "undelivered"} and message.status not in {"delivered", "failed", "undelivered"}:
            message.status = state
        db.add(MessageEvent(organization_id=organization_id, message_id=message.id, provider="twilio", event_id=event_id, kind=state))
        from app.core.campaigns import record_crm_event
        await record_crm_event(db, message, state)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
    return Response(content="<Response/>", media_type="application/xml")
