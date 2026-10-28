import logging
import hashlib
import hmac
from datetime import UTC, datetime
import uuid
import base64
from email.message import EmailMessage
from urllib.parse import urlparse
import httpx
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from app.core.config import settings
from app.models.messaging import GmailConnection, OutboundMessage, Suppression
from app.models.auth import Membership, User
from app.core.permissions import has_permission

logger = logging.getLogger(__name__)


def unsubscribe_signature(message_id: uuid.UUID) -> str:
    return hmac.new(settings.messaging_unsubscribe_secret.encode(), str(message_id).encode(), hashlib.sha256).hexdigest()


async def deliver_message(message_id: uuid.UUID) -> None:
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions() as db:
            from app.core.campaigns import delivery_guard
            permitted, campaign_provider = await delivery_guard(db, message_id)
            if not permitted:
                return
            message = await db.scalar(select(OutboundMessage).where(OutboundMessage.id == message_id).with_for_update())
            if not message or message.status != "queued":
                return
            sender = await db.scalar(select(Membership).join(User, User.id == Membership.user_id).where(
                Membership.organization_id == message.organization_id,
                Membership.user_id == message.created_by,
                Membership.is_active.is_(True), User.is_active.is_(True)))
            if not sender or not has_permission(sender.role, "integrations.manage"):
                message.status = "failed"
                message.error_message = "Sender no longer has permission in this workspace."
                await db.commit()
                return
            blocked = await db.scalar(select(Suppression.id).where(Suppression.organization_id == message.organization_id,
                Suppression.channel == message.channel, Suppression.recipient == message.recipient))
            if blocked:
                message.status = "suppressed"
                await db.commit()
                return
            gmail = await db.scalar(select(GmailConnection).where(GmailConnection.organization_id == message.organization_id)) if message.channel == "email" else None
            if campaign_provider == "resend":
                gmail = None
            gmail_configured = bool(gmail and settings.google_client_id and settings.google_client_secret and settings.oauth_encryption_key)
            resend_configured = bool(settings.resend_api_key and settings.resend_from_email)
            if gmail and not gmail_configured:
                message.status, message.error_message = "failed", "Gmail credentials are not configured. Reconnect the account."
                await db.commit()
                return
            if message.channel == "email" and not ((gmail_configured or resend_configured) and settings.messaging_public_base_url and settings.messaging_unsubscribe_secret):
                message.status, message.error_message = "failed", "Email provider, verified sender, or unsubscribe configuration is incomplete."
                await db.commit()
                return
            gmail_email, gmail_refresh = None, None
            if gmail_configured:
                try:
                    gmail_email = gmail.email
                    gmail_refresh = Fernet(settings.oauth_encryption_key.encode()).decrypt(gmail.encrypted_refresh_token.encode()).decode()
                except (ValueError, InvalidToken):
                    message.status, message.error_message = "failed", "Gmail connection cannot be decrypted. Reconnect the account."
                    await db.commit()
                    return
            if message.channel == "email":
                parsed_url = urlparse(settings.messaging_public_base_url)
                link_host = parsed_url.hostname
                if not link_host or (parsed_url.scheme != "https" and link_host not in {"localhost", "127.0.0.1", "::1"}):
                    message.status, message.error_message = "failed", "Configure a public HTTPS unsubscribe URL."
                    await db.commit()
                    return
                if link_host in {"localhost", "127.0.0.1", "::1"} and (
                    not gmail_email or message.recipient.lower() != gmail_email.lower()
                ):
                    message.status, message.error_message = "failed", "Local unsubscribe links are only suitable for testing to the connected Gmail account. Configure a public HTTPS URL for other recipients."
                    await db.commit()
                    return
            if message.channel == "sms" and not (settings.twilio_account_sid and settings.twilio_auth_token and settings.twilio_from_number):
                message.status, message.error_message = "failed", "SMS provider is not configured."
                await db.commit()
                return
            message.status = "sending"
            message.started_at = datetime.now(UTC)
            message.attempt_count += 1
            channel, recipient, subject, body = message.channel, message.recipient, message.subject, message.body
            organization_id = message.organization_id
            attempt_number = message.attempt_count
            from app.models.campaign import CampaignDeliveryAttempt
            if campaign_provider:
                db.add(CampaignDeliveryAttempt(organization_id=organization_id, message_id=message_id, attempt=attempt_number, status="sending"))
            await db.commit()
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                if channel == "email":
                    link = f"{settings.messaging_public_base_url.rstrip('/')}/api/v1/messaging/unsubscribe/{message_id}?signature={unsubscribe_signature(message_id)}"
                    if gmail_refresh:
                        token_response = await client.post("https://oauth2.googleapis.com/token", data={"client_id": settings.google_client_id,
                            "client_secret": settings.google_client_secret, "refresh_token": gmail_refresh, "grant_type": "refresh_token"})
                        token_response.raise_for_status()
                        access_token = token_response.json()["access_token"]
                        email = EmailMessage()
                        email["From"], email["To"], email["Subject"] = gmail_email, recipient, subject
                        email["List-Unsubscribe"] = f"<{link}>"
                        email["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
                        email.set_content(f"{body}\n\nUnsubscribe: {link}")
                        encoded = base64.urlsafe_b64encode(email.as_bytes()).decode()
                        response = await client.post("https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
                            headers={"Authorization": f"Bearer {access_token}"}, json={"raw": encoded})
                    else:
                        data = {"from": settings.resend_from_email, "to": [recipient], "subject": subject, "text": f"{body}\n\nUnsubscribe: {link}",
                                "headers": {"List-Unsubscribe": f"<{link}>", "List-Unsubscribe-Post": "List-Unsubscribe=One-Click"}}
                        if settings.resend_reply_to:
                            data["reply_to"] = settings.resend_reply_to
                        response = await client.post("https://api.resend.com/emails", headers={
                            "Authorization": f"Bearer {settings.resend_api_key}", "Idempotency-Key": f"message/{message_id}"}, json=data)
                else:
                    data = {"To": recipient, "From": settings.twilio_from_number, "Body": body + "\nReply STOP to unsubscribe."}
                    if settings.messaging_public_base_url:
                        data["StatusCallback"] = f"{settings.messaging_public_base_url.rstrip('/')}/api/v1/messaging/webhooks/twilio/{organization_id}"
                    response = await client.post(f"https://api.twilio.com/2010-04-01/Accounts/{settings.twilio_account_sid}/Messages.json",
                        auth=(settings.twilio_account_sid, settings.twilio_auth_token), data=data)
                response.raise_for_status()
                payload = response.json()
                provider_id = payload.get("id") if channel == "email" else payload.get("sid")
                if not provider_id:
                    raise ValueError("Provider response did not contain an ID")
            status, error = "accepted", None
        except httpx.HTTPStatusError as exc:
            status = "failed" if 400 <= exc.response.status_code < 500 and exc.response.status_code != 429 else "unknown"
            if campaign_provider and exc.response.status_code == 429:
                status = "retryable"
            error, provider_id = "Provider rejected the message." if status == "failed" else "Delivery outcome is uncertain; check the provider before retrying.", None
            if status == "retryable":
                error = "Provider rate limit reached; retry after backoff."
        except (httpx.HTTPError, ValueError, KeyError):
            logger.warning("Message provider outcome unknown for %s", message_id)
            status, error, provider_id = "unknown", "Delivery outcome is uncertain; check the provider before retrying.", None
        async with sessions() as db:
            message = await db.scalar(select(OutboundMessage).where(OutboundMessage.id == message_id).with_for_update())
            if message and message.status == "sending":
                message.status, message.error_message, message.provider_id = status, error, provider_id
                if campaign_provider:
                    attempt = await db.scalar(select(CampaignDeliveryAttempt).where(CampaignDeliveryAttempt.message_id == message_id, CampaignDeliveryAttempt.attempt == attempt_number))
                    if attempt:
                        attempt.status, attempt.provider_id, attempt.error = status, provider_id, error
                await db.commit()
    finally:
        await engine.dispose()
