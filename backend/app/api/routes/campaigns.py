import csv
import io
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select

from app.api.dependencies import DbSession, TenantContext, require_csrf, require_permission
from app.core.campaigns import VARIABLES, audience, audit, configuration, digest, render_text, sender_identity, utc
from app.core.config import settings
from app.core.openai_client import ProviderError, generate_response
from app.core.temporal_client import TemporalUnavailable, start_campaign_workflow
from app.models.agent import Agent, AgentVersion
from app.models.auth import User
from app.models.campaign import AudienceSegment, Campaign, CampaignApproval, CampaignAudit, CampaignDeliveryAttempt, CampaignRecipient, MarketingConsent
from app.models.crm import Contact
from app.models.messaging import MessageEvent, MessageTemplate, OutboundMessage
from app.schemas.campaign import AudienceFilters, AudienceInput, CampaignInput, ConsentInput, GenerateInput, SegmentInput

router = APIRouter(prefix="/campaigns", tags=["campaigns"])
Tenant = Annotated[TenantContext, Depends(require_permission("campaigns.manage"))]
Manager = Annotated[TenantContext, Depends(require_permission("campaigns.manage"))]
Admin = Annotated[TenantContext, Depends(require_permission("campaigns.approve"))]
Csrf = Annotated[User, Depends(require_csrf)]


def record(item):
    return {column.name: getattr(item, column.name) for column in item.__table__.columns}


async def get_campaign(db, context, campaign_id, lock=False):
    query = select(Campaign).where(Campaign.id == campaign_id, Campaign.organization_id == context.organization.id)
    item = await db.scalar(query.with_for_update() if lock else query)
    if not item:
        raise HTTPException(404, "Campaign not found")
    return item


async def validate_links(db, context, payload):
    if payload.agent_id and not await db.scalar(select(Agent.id).where(Agent.id == payload.agent_id, Agent.organization_id == context.organization.id)):
        raise HTTPException(404, "AI employee not found")
    if payload.template_id and not await db.scalar(select(MessageTemplate.id).where(MessageTemplate.id == payload.template_id,
        MessageTemplate.organization_id == context.organization.id, MessageTemplate.channel == payload.channel)):
        raise HTTPException(404, "Matching template not found")
    try:
        render_text(payload.subject + payload.body, {key: "preview" for key in VARIABLES})
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if payload.scheduled_at and utc(payload.scheduled_at) > datetime.now(UTC) + timedelta(days=365):
        raise HTTPException(422, "Schedule must be within one year")


@router.get("")
async def list_campaigns(db: DbSession, context: Tenant, q: str = Query(default="", max_length=160), status: str = "", page: int = Query(default=1, ge=1), page_size: int = Query(default=20, ge=1, le=100)):
    query = select(Campaign).where(Campaign.organization_id == context.organization.id)
    if q:
        term = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        query = query.where(Campaign.name.ilike(f"%{term}%", escape="\\"))
    if status:
        query = query.where(Campaign.status == status)
    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    items = (await db.scalars(query.order_by(Campaign.created_at.desc(), Campaign.id).offset((page - 1) * page_size).limit(page_size))).all()
    return {"items": [record(item) for item in items], "total": total}


@router.post("", status_code=201)
async def create_campaign(payload: CampaignInput, db: DbSession, context: Manager, _csrf: Csrf):
    await validate_links(db, context, payload)
    values = payload.model_dump()
    values["audience"] = payload.audience.model_dump(mode="json")
    item = Campaign(organization_id=context.organization.id, created_by=context.user.id, **values)
    db.add(item)
    await db.flush()
    audit(db, context.organization.id, "created", context.user.id, item.id)
    await db.commit()
    await db.refresh(item)
    return record(item)


@router.post("/audience/preview")
async def preview_audience(payload: AudienceInput, db: DbSession, context: Manager, _csrf: Csrf):
    try:
        return await audience(db, context.organization.id, payload.channel, payload.filters)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/segments")
async def list_segments(db: DbSession, context: Tenant):
    return [record(row) for row in (await db.scalars(select(AudienceSegment).where(AudienceSegment.organization_id == context.organization.id).order_by(AudienceSegment.name))).all()]


@router.post("/segments", status_code=201)
async def save_segment(payload: SegmentInput, db: DbSession, context: Manager, _csrf: Csrf):
    item = AudienceSegment(organization_id=context.organization.id, name=payload.name, filters=payload.filters.model_dump(mode="json"))
    db.add(item)
    audit(db, context.organization.id, "segment_created", context.user.id, name=payload.name)
    await db.commit()
    await db.refresh(item)
    return record(item)


@router.delete("/segments/{segment_id}", status_code=204)
async def delete_segment(segment_id: uuid.UUID, db: DbSession, context: Manager, _csrf: Csrf):
    item = await db.scalar(select(AudienceSegment).where(AudienceSegment.id == segment_id, AudienceSegment.organization_id == context.organization.id))
    if not item:
        raise HTTPException(404, "Segment not found")
    await db.delete(item)
    await db.commit()


@router.put("/segments/{segment_id}")
async def edit_segment(segment_id: uuid.UUID, payload: SegmentInput, db: DbSession, context: Manager, _csrf: Csrf):
    item = await db.scalar(select(AudienceSegment).where(AudienceSegment.id == segment_id, AudienceSegment.organization_id == context.organization.id).with_for_update())
    if not item:
        raise HTTPException(404, "Segment not found")
    item.name, item.filters = payload.name, payload.filters.model_dump(mode="json")
    audit(db, context.organization.id, "segment_updated", context.user.id, segment_id=str(item.id))
    await db.commit()
    await db.refresh(item)
    return record(item)


@router.get("/consents")
async def list_consents(db: DbSession, context: Manager, page: int = Query(default=1, ge=1)):
    return [record(row) for row in (await db.scalars(select(MarketingConsent).where(MarketingConsent.organization_id == context.organization.id).order_by(MarketingConsent.updated_at.desc()).offset((page-1)*50).limit(50))).all()]


@router.get("/consents/history")
async def consent_history(db: DbSession, context: Manager, page: int = Query(default=1, ge=1)):
    rows = (await db.scalars(select(CampaignAudit).where(CampaignAudit.organization_id == context.organization.id,
        CampaignAudit.action.in_(["consent_granted", "consent_revoked", "contact_opt_out"])).order_by(CampaignAudit.created_at.desc()).offset((page-1)*50).limit(50))).all()
    return [record(row) for row in rows]


@router.post("/consents")
async def save_consent(payload: ConsentInput, db: DbSession, context: Manager, _csrf: Csrf):
    from app.api.routes.messaging import normalize
    contact = await db.scalar(select(Contact).where(Contact.id == payload.contact_id, Contact.organization_id == context.organization.id).with_for_update())
    if not contact:
        raise HTTPException(404, "Contact not found")
    recipient = normalize(payload.channel, (contact.email if payload.channel == "email" else contact.phone) or "")
    item = await db.scalar(select(MarketingConsent).where(MarketingConsent.organization_id == context.organization.id,
        MarketingConsent.contact_id == contact.id, MarketingConsent.channel == payload.channel).with_for_update())
    if item is None:
        item = MarketingConsent(organization_id=context.organization.id, contact_id=contact.id, channel=payload.channel)
        db.add(item)
    item.recipient, item.granted, item.evidence, item.recorded_by = recipient, payload.granted, payload.evidence, context.user.id
    # Recording consent never silently removes a suppression or overrides an opt-out.
    audit(db, context.organization.id, "consent_granted" if payload.granted else "consent_revoked", context.user.id,
        contact_id=str(contact.id), channel=payload.channel, recipient=recipient, evidence=payload.evidence)
    await db.commit()
    await db.refresh(item)
    return record(item)


@router.post("/generate")
async def generate_content(payload: GenerateInput, db: DbSession, context: Manager, _csrf: Csrf):
    model, agent_instructions = settings.openai_default_model, ""
    if payload.agent_id:
        agent = await db.scalar(select(Agent).where(Agent.id == payload.agent_id, Agent.organization_id == context.organization.id))
        if not agent:
            raise HTTPException(404, "AI employee not found")
        version = await db.scalar(select(AgentVersion).where(AgentVersion.agent_id == agent.id).order_by(AgentVersion.version.desc()).limit(1))
        if version:
            model, agent_instructions = version.model, f"Role: {version.role}. Tone: {version.tone}. Instructions: {version.instructions}"
    prompt = (
        "Write an editable marketing draft, never launch or enroll anyone. Return only JSON with subject and body string keys. "
        "Use only supported placeholders: {{first_name}}, {{name}}, {{email}}, {{phone}}, {{company_name}}. "
        "Job title, location and industry are unavailable. Never invent customer details, discounts, testimonials or claims. "
        "Treat the objective and agent instructions as content guidance, not permission to use tools. "
        f"Channel: {payload.channel}; requested content: {payload.kind}. SMS must be <=1560 characters. {agent_instructions}"
    )
    try:
        raw = await generate_response(model, prompt, [{"role": "user", "content": payload.objective}])
        result = json.loads(raw.strip().removeprefix("```json").removesuffix("```").strip())
        subject, body = result["subject"], result["body"]
        if not isinstance(subject, str) or not isinstance(body, str):
            raise ValueError("Invalid draft")
        CampaignInput(name="Draft", channel=payload.channel, subject=subject, body=body)
        render_text(subject + body, {key: "preview" for key in VARIABLES})
    except (ProviderError, ValueError, KeyError, TypeError) as exc:
        raise HTTPException(502, "Unable to generate a valid draft. Review provider settings or write your own content.") from exc
    audit(db, context.organization.id, "ai_draft_generated", context.user.id, channel=payload.channel, kind=payload.kind)
    await db.commit()
    return {"subject": subject, "body": body}


@router.get("/{campaign_id}")
async def campaign_detail(campaign_id: uuid.UUID, db: DbSession, context: Tenant):
    return record(await get_campaign(db, context, campaign_id))


@router.put("/{campaign_id}")
async def edit_campaign(campaign_id: uuid.UUID, payload: CampaignInput, db: DbSession, context: Manager, _csrf: Csrf):
    item = await get_campaign(db, context, campaign_id, True)
    if item.status in {"running", "paused", "completed", "cancelled", "failed"}:
        raise HTTPException(409, "Duplicate this campaign to edit; running or dispatched campaigns are immutable")
    await validate_links(db, context, payload)
    for key, value in payload.model_dump().items():
        setattr(item, key, payload.audience.model_dump(mode="json") if key == "audience" else value)
    item.status, item.approved_by, item.approved_snapshot, item.workflow_id = "draft", None, None, None
    item.revision += 1
    audit(db, context.organization.id, "edited_reapproval_required", context.user.id, item.id, revision=item.revision)
    await db.commit()
    await db.refresh(item)
    return record(item)


@router.delete("/{campaign_id}", status_code=204)
async def delete_campaign(campaign_id: uuid.UUID, db: DbSession, context: Manager, _csrf: Csrf):
    item = await get_campaign(db, context, campaign_id, True)
    if item.status != "draft":
        raise HTTPException(409, "Only drafts may be deleted")
    # Audit/approval snapshots survive edits; draft removal retains an audit trail.
    audit(db, context.organization.id, "draft_deleted", context.user.id, deleted_campaign_id=str(item.id))
    for model in [CampaignRecipient, CampaignApproval]:
        await db.execute(delete(model).where(model.campaign_id == item.id))
    await db.delete(item)
    await db.commit()


@router.post("/{campaign_id}/duplicate", status_code=201)
async def duplicate_campaign(campaign_id: uuid.UUID, db: DbSession, context: Manager, _csrf: Csrf):
    original = await get_campaign(db, context, campaign_id)
    payload = CampaignInput.model_validate(configuration(original))
    payload.name = f"{payload.name[:145]} (copy)"
    payload.scheduled_at = None
    return await create_campaign(payload, db, context, _csrf)


@router.post("/{campaign_id}/submit")
async def submit_campaign(campaign_id: uuid.UUID, db: DbSession, context: Manager, _csrf: Csrf):
    item = await get_campaign(db, context, campaign_id, True)
    if item.status != "draft":
        raise HTTPException(409, "Only drafts can be submitted")
    try:
        preview = await audience(db, context.organization.id, item.channel, AudienceFilters.model_validate(item.audience))
        if not preview["contacts"]:
            raise ValueError("No eligible recipients. Record marketing consent and review suppressions first.")
        for row in preview["contacts"]:
            render_text(item.subject, row["personalization"])
            render_text(item.body, row["personalization"])
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    item.status = "pending_approval"
    audit(db, context.organization.id, "approval_requested", context.user.id, item.id)
    await db.commit()
    await db.refresh(item)
    return record(item)


@router.post("/{campaign_id}/approve")
async def approve_campaign(campaign_id: uuid.UUID, db: DbSession, context: Admin, _csrf: Csrf):
    item = await get_campaign(db, context, campaign_id, True)
    if item.status != "pending_approval":
        raise HTTPException(409, "Campaign must be pending approval")
    try:
        preview = await audience(db, context.organization.id, item.channel, AudienceFilters.model_validate(item.audience))
        if not preview["contacts"]:
            raise ValueError("No eligible audience")
        sender = await sender_identity(db, context.organization.id, item.channel, item.provider,
            recipients=[row["recipient"] for row in preview["contacts"]])
        recipients = []
        for row in preview["contacts"]:
            subject, body = render_text(item.subject, row["personalization"]), render_text(item.body, row["personalization"])
            if len(subject) > 200 or len(body) > (1560 if item.channel == "sms" else 10000) or "\n" in subject or "\r" in subject:
                raise ValueError("Rendered message exceeds channel limits")
            recipients.append({**row, "subject": subject, "body": body})
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    snapshot = {"configuration": configuration(item), "sender": sender, "revision": item.revision, "recipients": recipients}
    snapshot["digest"] = digest(snapshot)
    item.approved_snapshot, item.approved_by, item.status = snapshot, context.user.id, "approved"
    for row in recipients:
        db.add(CampaignRecipient(campaign_id=item.id, organization_id=context.organization.id, revision=item.revision,
            contact_id=uuid.UUID(row["contact_id"]), recipient=row["recipient"], personalization=row["personalization"], subject=row["subject"], body=row["body"]))
    db.add(CampaignApproval(campaign_id=item.id, organization_id=context.organization.id, decided_by=context.user.id, decision="approved", snapshot=snapshot))
    audit(db, context.organization.id, "approved", context.user.id, item.id, digest=snapshot["digest"], recipients=len(recipients))
    await db.commit()
    await db.refresh(item)
    return record(item)


@router.post("/{campaign_id}/reject")
async def reject_campaign(campaign_id: uuid.UUID, db: DbSession, context: Admin, _csrf: Csrf):
    item = await get_campaign(db, context, campaign_id, True)
    if item.status != "pending_approval":
        raise HTTPException(409, "Campaign is not pending approval")
    db.add(CampaignApproval(campaign_id=item.id, organization_id=context.organization.id, decided_by=context.user.id, decision="rejected", snapshot={"configuration": configuration(item), "revision": item.revision}))
    item.status = "draft"
    audit(db, context.organization.id, "rejected", context.user.id, item.id)
    await db.commit()
    await db.refresh(item)
    return record(item)


@router.post("/{campaign_id}/draft")
async def return_draft(campaign_id: uuid.UUID, db: DbSession, context: Manager, _csrf: Csrf):
    item = await get_campaign(db, context, campaign_id, True)
    if item.status not in {"pending_approval", "approved", "scheduled"}:
        raise HTTPException(409, "Campaign cannot be returned to draft")
    payload = CampaignInput.model_validate(configuration(item))
    return await edit_campaign(campaign_id, payload, db, context, _csrf)


@router.post("/{campaign_id}/start")
async def start_campaign(campaign_id: uuid.UUID, db: DbSession, context: Manager, _csrf: Csrf):
    item = await get_campaign(db, context, campaign_id, True)
    if item.status not in {"approved", "scheduled", "running"} or not item.approved_snapshot:
        raise HTTPException(409, "Human approval is required before starting")
    approved = item.approved_snapshot
    if approved["configuration"] != configuration(item):
        raise HTTPException(409, "Campaign configuration changed; obtain approval again")
    item.workflow_id = f"campaign-{item.id}-v{item.revision}"
    item.status = "scheduled" if item.scheduled_at and utc(item.scheduled_at) > datetime.now(UTC) else "running"
    audit(db, context.organization.id, "start_requested", context.user.id, item.id, workflow_id=item.workflow_id)
    await db.commit()
    try:
        await start_campaign_workflow(item.workflow_id, {"campaign_id": str(item.id), "revision": item.revision})
    except TemporalUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
    await db.refresh(item)
    return record(item)


@router.post("/{campaign_id}/{action}")
async def control_campaign(campaign_id: uuid.UUID, action: Literal["pause", "resume", "cancel"], db: DbSession, context: Manager, _csrf: Csrf):
    item = await get_campaign(db, context, campaign_id, True)
    allowed = {"pause": {"running", "scheduled"}, "resume": {"paused"}, "cancel": {"draft", "pending_approval", "approved", "scheduled", "running", "paused", "failed"}}
    if item.status not in allowed[action]:
        raise HTTPException(409, "Invalid campaign transition")
    item.status = {"pause": "paused", "resume": "running", "cancel": "cancelled"}[action]
    if action == "cancel":
        recipients = (await db.scalars(select(CampaignRecipient).where(CampaignRecipient.campaign_id == item.id,
            CampaignRecipient.revision == item.revision, CampaignRecipient.status.in_(["pending", "queued"])))).all()
        for recipient in recipients:
            message = await db.get(OutboundMessage, recipient.message_id) if recipient.message_id else None
            if message and message.status in {"queued", "retryable"}:
                message.status = "cancelled"
            if not message or message.status == "cancelled":
                recipient.status = "cancelled"
    audit(db, context.organization.id, action, context.user.id, item.id)
    await db.commit()
    await db.refresh(item)
    return record(item)


@router.get("/{campaign_id}/recipients")
async def list_recipients(campaign_id: uuid.UUID, db: DbSession, context: Tenant, page: int = Query(default=1, ge=1)):
    item = await get_campaign(db, context, campaign_id)
    query = select(CampaignRecipient, OutboundMessage).outerjoin(OutboundMessage, CampaignRecipient.message_id == OutboundMessage.id).where(
        CampaignRecipient.campaign_id == item.id, CampaignRecipient.organization_id == context.organization.id, CampaignRecipient.revision == item.revision)
    rows = (await db.execute(query.order_by(CampaignRecipient.id).offset((page-1)*25).limit(25))).all()
    return {"items": [{**record(row), "delivery_status": message.status if message else row.status,
        "provider_id": message.provider_id if message else None, "error": message.error_message if message else None} for row, message in rows],
        "total": await db.scalar(select(func.count(CampaignRecipient.id)).where(CampaignRecipient.campaign_id == item.id, CampaignRecipient.revision == item.revision))}


@router.get("/{campaign_id}/analytics")
async def analytics(campaign_id: uuid.UUID, db: DbSession, context: Tenant, since: datetime | None = None, until: datetime | None = None):
    item = await get_campaign(db, context, campaign_id)
    recipients = (await db.execute(select(CampaignRecipient, OutboundMessage).outerjoin(OutboundMessage, CampaignRecipient.message_id == OutboundMessage.id).where(
        CampaignRecipient.campaign_id == item.id, CampaignRecipient.revision == item.revision))).all()
    statuses = {}
    ids = []
    for recipient, message in recipients:
        state = message.status if message else recipient.status
        statuses[state] = statuses.get(state, 0) + 1
        if message:
            ids.append(message.id)
    query = select(MessageEvent).where(MessageEvent.organization_id == context.organization.id, MessageEvent.message_id.in_(ids))
    if since:
        query = query.where(MessageEvent.created_at >= utc(since))
    if until:
        query = query.where(MessageEvent.created_at <= utc(until))
    counts = dict((await db.execute(query.with_only_columns(MessageEvent.kind, func.count(func.distinct(MessageEvent.message_id))).group_by(MessageEvent.kind))).all())
    events = (await db.scalars(query.order_by(MessageEvent.created_at.desc()).limit(100))).all()
    provider = (item.approved_snapshot or {}).get("sender", {}).get("provider")
    supported = provider == "resend"
    audits = (await db.scalars(select(CampaignAudit).where(CampaignAudit.campaign_id == item.id, CampaignAudit.organization_id == context.organization.id).order_by(CampaignAudit.created_at.desc()).limit(100))).all()
    attempts = (await db.scalars(select(CampaignDeliveryAttempt).where(CampaignDeliveryAttempt.organization_id == context.organization.id, CampaignDeliveryAttempt.message_id.in_(ids)).order_by(CampaignDeliveryAttempt.created_at.desc()).limit(100))).all()
    return {"total": len(recipients), "statuses": statuses, "events": counts,
        "delivery_tracking_available": provider in {"resend", "twilio"},
        "opens": counts.get("email.opened", 0) if supported else None,
        "clicks": counts.get("email.clicked", 0) if supported else None,
        "replies": counts.get("reply", 0) if provider in {"resend", "twilio"} else None,
        "tracking_note": "Engagement reflects recorded provider events only. Zero means no recorded event; tracking may be unavailable or affected by privacy settings.",
        "timeline": [record(row) for row in events], "audit": [record(row) for row in audits], "attempts": [record(row) for row in attempts]}


@router.get("/{campaign_id}/export")
async def export_campaign(campaign_id: uuid.UUID, db: DbSession, context: Manager):
    item = await get_campaign(db, context, campaign_id)
    rows = (await db.execute(select(CampaignRecipient, OutboundMessage).outerjoin(OutboundMessage, CampaignRecipient.message_id == OutboundMessage.id).where(
        CampaignRecipient.campaign_id == item.id, CampaignRecipient.revision == item.revision))).all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["recipient", "status", "provider_id", "error"])
    def safe(value):
        value = str(value or "")
        return "'" + value if value.startswith(("=", "+", "-", "@", "\t", "\r")) else value
    for recipient, message in rows:
        writer.writerow([safe(recipient.recipient), message.status if message else recipient.status,
            safe(message.provider_id if message else ""), safe(message.error_message if message else "")])
    return Response(output.getvalue(), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="campaign-{item.id}.csv"'})


class ReconcileInput(BaseModel):
    outcome: Literal["accepted", "not_sent"]
    evidence: str = Field(min_length=10, max_length=2000)
    provider_id: str | None = Field(default=None, max_length=200)


@router.post("/{campaign_id}/recipients/{recipient_id}/reconcile")
async def reconcile_delivery(campaign_id: uuid.UUID, recipient_id: uuid.UUID, payload: ReconcileInput, db: DbSession, context: Admin, _csrf: Csrf):
    item = await get_campaign(db, context, campaign_id, True)
    recipient = await db.scalar(select(CampaignRecipient).where(CampaignRecipient.id == recipient_id, CampaignRecipient.campaign_id == item.id,
        CampaignRecipient.organization_id == context.organization.id))
    if not recipient or not recipient.message_id:
        raise HTTPException(404, "Delivery not found")
    message = await db.scalar(select(OutboundMessage).where(OutboundMessage.id == recipient.message_id).with_for_update())
    if message.status != "unknown":
        raise HTTPException(409, "Only uncertain deliveries require reconciliation")
    if payload.outcome == "accepted" and not payload.provider_id:
        raise HTTPException(422, "An accepted delivery requires the provider message ID")
    if payload.outcome == "not_sent" and (message.provider_id or message.attempt_count >= 3 or item.status != "paused"):
        raise HTTPException(409, "Pause the campaign before confirming a retry; accepted deliveries and exhausted retry budgets cannot be retried")
    message.status = "accepted" if payload.outcome == "accepted" else "queued"
    message.provider_id = payload.provider_id if payload.outcome == "accepted" else None
    message.error_message = None
    recipient.status = message.status
    audit(db, context.organization.id, "delivery_reconciled", context.user.id, item.id, recipient_id=str(recipient.id), outcome=payload.outcome, evidence=payload.evidence)
    await db.commit()
    return record(message)
