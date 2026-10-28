"""Campaign policy and queries. Provider calls stay in the Phase 9 delivery service."""
import hashlib
import json
import re
import uuid
from datetime import UTC, datetime, timedelta
from email.utils import parseaddr
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import exists, func, select

from app.core.config import settings
from app.models.agent import Agent
from app.models.auth import Organization
from app.models.campaign import Campaign, CampaignAudit, CampaignRecipient, MarketingConsent
from app.models.crm import Company, Contact, Lead
from app.models.messaging import GmailConnection, MessageEvent, OutboundMessage, Suppression
from app.schemas.campaign import AudienceFilters, CampaignInput

VARIABLE = re.compile(r"{{\s*([a-z_]+)\s*}}")
VARIABLES = {"first_name", "name", "email", "phone", "company_name"}
TERMINAL = {"completed", "cancelled", "failed"}


def utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def audit(db, organization_id, action, user_id=None, campaign_id=None, **detail):
    from app.core.audit import record_audit
    record_audit(db, organization_id, action, user_id, module="campaigns", campaign_id=campaign_id, detail=detail)


def render_text(text: str, values: dict) -> str:
    names = set(VARIABLE.findall(text))
    if names - VARIABLES or "{{" in VARIABLE.sub("", text) or "}}" in VARIABLE.sub("", text):
        raise ValueError("Unsupported template variable. Use first_name, name, email, phone or company_name.")
    if any(not values.get(name) for name in names):
        raise ValueError("A required personalization value is missing for an audience contact")
    return VARIABLE.sub(lambda match: str(values[match.group(1)]), text)


def configuration(campaign: Campaign) -> dict:
    result = {key: getattr(campaign, key) for key in CampaignInput.model_fields}
    result["scheduled_at"] = utc(campaign.scheduled_at).isoformat() if campaign.scheduled_at else None
    return json.loads(json.dumps(result, default=str))


async def record_optout(db, organization_id, channel, recipient, reason, message_id=None):
    from sqlalchemy import update
    from app.models.messaging import MessageEvent
    if message_id and await db.scalar(select(MessageEvent.id).where(MessageEvent.provider == "internal", MessageEvent.event_id == f"unsubscribe:{message_id}")):
        return
    await db.execute(update(MarketingConsent).where(MarketingConsent.organization_id == organization_id,
        MarketingConsent.channel == channel, MarketingConsent.recipient == recipient).values(granted=False))
    audit(db, organization_id, "contact_opt_out", recipient=recipient, channel=channel, reason=reason)
    if message_id and not await db.scalar(select(MessageEvent.id).where(MessageEvent.provider == "internal", MessageEvent.event_id == f"unsubscribe:{message_id}")):
        db.add(MessageEvent(organization_id=organization_id, message_id=message_id, provider="internal", event_id=f"unsubscribe:{message_id}", kind="unsubscribe"))


async def record_crm_event(db, message, kind):
    from app.models.crm import CRMActivity
    recipient = await db.scalar(select(CampaignRecipient).where(CampaignRecipient.message_id == message.id,
        CampaignRecipient.organization_id == message.organization_id))
    if not recipient:
        return
    campaign = await db.get(Campaign, recipient.campaign_id)
    leads = (await db.scalars(select(Lead).where(Lead.organization_id == message.organization_id, Lead.contact_id == recipient.contact_id))).all()
    for lead in leads:
        db.add(CRMActivity(organization_id=message.organization_id, lead_id=lead.id, created_by=campaign.created_by,
            kind="email" if message.channel == "email" else "activity", content=f"Campaign {campaign.name}: {kind} ({message.recipient})"))


def digest(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def public_unsubscribe_url() -> bool:
    url = urlparse(settings.messaging_public_base_url)
    return bool(url.scheme == "https" and url.hostname and url.hostname not in {"localhost", "127.0.0.1", "::1"})


def local_gmail_self_test(identity: dict, recipients: list[str]) -> bool:
    """Opt-in development exception for the connected account's own mailbox only."""
    url = urlparse(settings.messaging_public_base_url)
    return bool(
        settings.campaign_allow_local_gmail_self_test
        and settings.app_env == "development"
        and identity.get("provider") == "gmail"
        and identity.get("sender")
        and url.scheme in {"http", "https"}
        and url.hostname in {"localhost", "127.0.0.1", "::1"}
        and not url.username and not url.password
        and settings.messaging_unsubscribe_secret
        and recipients
        and all(address.lower() == identity["sender"].lower() for address in recipients)
    )


async def sender_identity(db, organization_id, channel, provider="auto", validate=True, recipients=None):
    gmail = await db.scalar(select(GmailConnection).where(GmailConnection.organization_id == organization_id))
    chosen = ("gmail" if gmail else "resend") if channel == "email" and provider == "auto" else ("twilio" if channel == "sms" else provider)
    if chosen == "gmail":
        if not gmail or not all([settings.google_client_id, settings.google_client_secret, settings.oauth_encryption_key]):
            raise ValueError("Connect Gmail before approving this campaign")
        identity = {"provider": chosen, "sender": gmail.email, "connection_id": str(gmail.id)}
    elif chosen == "resend":
        if not settings.resend_api_key or not settings.resend_from_email:
            raise ValueError("Configure a verified Resend sender before approval")
        identity = {"provider": chosen, "sender": settings.resend_from_email}
    elif chosen == "twilio":
        if not all([settings.twilio_account_sid, settings.twilio_auth_token, settings.twilio_from_number]):
            raise ValueError("Configure the Twilio account and sender before approval")
        identity = {"provider": chosen, "sender": settings.twilio_from_number, "account": settings.twilio_account_sid}
    else:
        raise ValueError("Invalid provider for this channel")
    identity["unsubscribe_base"] = settings.messaging_public_base_url
    if validate and channel == "email":
        if not settings.messaging_unsubscribe_secret or not (
            public_unsubscribe_url() or local_gmail_self_test(identity, recipients or [])
        ):
            raise ValueError("Marketing campaigns require a public HTTPS unsubscribe URL. Local development self-tests must send only to the connected Gmail address.")
        if chosen == "resend":
            import httpx
            try:
                async with httpx.AsyncClient(timeout=8) as client:
                    response = await client.get("https://api.resend.com/domains", headers={"Authorization": f"Bearer {settings.resend_api_key}"})
                    response.raise_for_status()
                    domains = response.json().get("data", [])
                domain = parseaddr(settings.resend_from_email)[1].rsplit("@", 1)[-1].lower()
                if not any(item.get("name", "").lower() == domain and item.get("status") == "verified" for item in domains):
                    raise ValueError("Resend sending domain is not verified")
            except httpx.HTTPError as exc:
                raise ValueError("Unable to verify the Resend sender") from exc
    return identity


async def audience(db, organization_id, channel, filters: AudienceFilters):
    from app.api.routes.messaging import normalize
    query = select(Contact).where(Contact.organization_id == organization_id)
    if filters.query:
        term = filters.query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        query = query.where(Contact.name.ilike(f"%{term}%", escape="\\"))
    if filters.contact_ids:
        query = query.where(Contact.id.in_(filters.contact_ids))
    if filters.company_id:
        query = query.where(Contact.company_id == filters.company_id)
    if filters.lead_stage or filters.owner_id:
        lead = select(Lead.id).where(Lead.organization_id == organization_id, Lead.contact_id == Contact.id)
        if filters.lead_stage:
            lead = lead.where(Lead.stage == filters.lead_stage)
        if filters.owner_id:
            lead = lead.where(Lead.owner_id == filters.owner_id)
        query = query.where(exists(lead))
    if filters.engagement:
        event = select(MessageEvent.id).join(OutboundMessage, MessageEvent.message_id == OutboundMessage.id).where(
            MessageEvent.organization_id == organization_id, OutboundMessage.organization_id == organization_id,
            OutboundMessage.channel == channel, OutboundMessage.recipient == (Contact.email if channel == "email" else Contact.phone),
            MessageEvent.kind.in_([filters.engagement, f"email.{filters.engagement}"]))
        query = query.where(exists(event))
    contacts = (await db.scalars(query.order_by(Contact.id).limit(settings.campaign_max_recipients + 1))).all()
    if len(contacts) > settings.campaign_max_recipients:
        raise ValueError(f"Narrow the audience to at most {settings.campaign_max_recipients} contacts")
    consents = {(row.contact_id, row.recipient) for row in (await db.scalars(select(MarketingConsent).where(
        MarketingConsent.organization_id == organization_id, MarketingConsent.channel == channel, MarketingConsent.granted.is_(True)))).all()}
    suppressed = set((await db.scalars(select(Suppression.recipient).where(Suppression.organization_id == organization_id, Suppression.channel == channel))).all())
    companies = {row.id: row.name for row in (await db.scalars(select(Company).where(Company.organization_id == organization_id))).all()}
    exclusions = {"invalid": 0, "no_consent": 0, "suppressed": 0, "duplicate": 0, "country": 0}
    seen, eligible = set(), []
    for contact in contacts:
        try:
            recipient = normalize(channel, (contact.email if channel == "email" else contact.phone) or "")
        except HTTPException:
            exclusions["invalid"] += 1
            continue
        if channel == "sms" and settings.campaign_allowed_sms_prefixes and not any(recipient.startswith(prefix) for prefix in settings.campaign_allowed_sms_prefixes):
            exclusions["country"] += 1
        elif recipient in suppressed:
            exclusions["suppressed"] += 1
        elif (contact.id, recipient) not in consents:
            exclusions["no_consent"] += 1
        elif recipient in seen:
            exclusions["duplicate"] += 1
        else:
            seen.add(recipient)
            values = {"first_name": contact.name.split()[0] if contact.name.split() else "", "name": contact.name,
                "email": contact.email or "", "phone": contact.phone or "", "company_name": companies.get(contact.company_id, "")}
            eligible.append({"contact_id": str(contact.id), "recipient": recipient, "personalization": values})
    return {"matched": len(contacts), "eligible_count": len(eligible), "excluded": exclusions, "contacts": eligible}


def window_delay(campaign, now=None):
    now = now or datetime.now(UTC)
    if campaign.scheduled_at and utc(campaign.scheduled_at) > now:
        return (utc(campaign.scheduled_at) - now).total_seconds()
    local = now.astimezone(ZoneInfo(campaign.timezone))
    if campaign.window_start <= local.hour < campaign.window_end:
        return 0.0
    next_start = local.replace(hour=campaign.window_start, minute=0, second=0, microsecond=0)
    if local.hour >= campaign.window_end:
        next_start += timedelta(days=1)
    return max(1, (next_start.astimezone(UTC) - now).total_seconds())


async def contact_allowed(db, recipient: CampaignRecipient, channel):
    from app.api.routes.messaging import normalize
    contact = await db.scalar(select(Contact).where(Contact.id == recipient.contact_id, Contact.organization_id == recipient.organization_id))
    if not contact:
        return False
    try:
        current = normalize(channel, (contact.email if channel == "email" else contact.phone) or "")
    except HTTPException:
        return False
    if current != recipient.recipient:
        return False
    consent = await db.scalar(select(MarketingConsent).where(MarketingConsent.organization_id == recipient.organization_id,
        MarketingConsent.contact_id == contact.id, MarketingConsent.channel == channel).with_for_update())
    blocked = await db.scalar(select(Suppression.id).where(Suppression.organization_id == recipient.organization_id,
        Suppression.channel == channel, Suppression.recipient == current))
    return bool(consent and consent.granted and consent.recipient == current and not blocked)


async def delivery_guard(db, message_id):
    """Claim under the campaign lock shared with pause/cancel. No network calls here."""
    recipient = await db.scalar(select(CampaignRecipient).where(CampaignRecipient.message_id == message_id))
    if not recipient:
        return True, None
    campaign = await db.scalar(select(Campaign).where(Campaign.id == recipient.campaign_id).with_for_update())
    if not campaign or campaign.status != "running" or recipient.revision != campaign.revision or not campaign.approved_snapshot:
        return False, None
    if window_delay(campaign):
        return False, None
    from app.models.auth import Membership, MembershipRole, User
    for user_id, roles in [(campaign.created_by, [MembershipRole.admin, MembershipRole.manager]),
                           (campaign.approved_by, [MembershipRole.admin])]:
        allowed = await db.scalar(select(Membership.id).join(User, User.id == Membership.user_id).where(
            Membership.organization_id == campaign.organization_id, Membership.user_id == user_id,
            Membership.is_active.is_(True), Membership.role.in_(roles), User.is_active.is_(True)))
        if not allowed:
            campaign.status, campaign.error_message = "failed", "Campaign authorization changed. Obtain fresh approval from active workspace administrators."
            await db.commit()
            return False, None
    if not await contact_allowed(db, recipient, campaign.channel):
        message = await db.get(OutboundMessage, message_id)
        if message and message.status == "queued":
            message.status = "suppressed"
            recipient.status = "suppressed"
            audit(db, campaign.organization_id, "recipient_suppressed", campaign_id=campaign.id, recipient_id=str(recipient.id))
        await db.commit()
        return False, None
    if campaign.channel == "sms" and settings.campaign_allowed_sms_prefixes and not any(recipient.recipient.startswith(prefix) for prefix in settings.campaign_allowed_sms_prefixes):
        message = await db.get(OutboundMessage, message_id)
        message.status, recipient.status = "suppressed", "suppressed"
        await db.commit()
        return False, None
    try:
        identity = await sender_identity(db, campaign.organization_id, campaign.channel, campaign.provider, validate=False)
    except ValueError:
        identity = None
    if identity != campaign.approved_snapshot.get("sender"):
        campaign.status, campaign.error_message = "failed", "Sender configuration changed. Duplicate the campaign and obtain approval again."
        await db.commit()
        return False, None
    if campaign.channel == "email" and not public_unsubscribe_url() and not local_gmail_self_test(identity, [recipient.recipient]):
        campaign.status, campaign.error_message = "failed", "Local Gmail self-test is unavailable or the recipient is not the connected Gmail address. Configure a public HTTPS unsubscribe URL and obtain approval again."
        await db.commit()
        return False, None
    await db.scalar(select(Organization).where(Organization.id == campaign.organization_id).with_for_update())
    now = datetime.now(UTC)
    interval = settings.campaign_email_interval_seconds if campaign.channel == "email" else settings.campaign_sms_interval_seconds
    last = await db.scalar(select(func.max(OutboundMessage.started_at)).where(OutboundMessage.organization_id == campaign.organization_id, OutboundMessage.channel == campaign.channel))
    count = await db.scalar(select(func.count(OutboundMessage.id)).where(OutboundMessage.organization_id == campaign.organization_id, OutboundMessage.started_at >= now - timedelta(hours=1)))
    if (last and (now - utc(last)).total_seconds() < interval) or count >= settings.messaging_hourly_limit:
        return False, None
    return True, identity["provider"]
