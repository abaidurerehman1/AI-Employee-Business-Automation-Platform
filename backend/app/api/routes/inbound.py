import hashlib
import hmac
import secrets
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, EmailStr, Field, ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.api.dependencies import DbSession, TenantContext, require_csrf, require_permission
from app.core.embeddings import EmbeddingError
from app.core.inbound_rate import check_rate_limit
from app.core.openai_client import ProviderError
from app.core.rag_graph import run_rag_agent
from app.core.security import token_digest
from app.models.agent import Agent, AgentVersion
from app.models.auth import Membership, MembershipRole, User
from app.models.crm import Contact, Lead
from app.models.inbound import InboundSite, InboundWebhookEvent, VisitorConversation, VisitorMessage
from app.models.knowledge import KnowledgeDocument

router = APIRouter(tags=["inbound"])
Tenant = Annotated[TenantContext, Depends(require_permission("inbox.assigned"))]
Manager = Annotated[TenantContext, Depends(require_permission("inbox.manage"))]
Csrf = Annotated[User, Depends(require_csrf)]


class SiteInput(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    agent_id: uuid.UUID
    enabled: bool = True


class MessageInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    message: str = Field(min_length=1, max_length=4000)


class CaptureInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    name: str = Field(min_length=1, max_length=200)
    email: EmailStr
    enquiry: str = Field(min_length=1, max_length=4000)
    budget: str = Field(default="", max_length=200)
    timeline: str = Field(default="", max_length=200)


class AssignmentInput(BaseModel):
    assigned_to: uuid.UUID | None
    status: Literal["human", "closed", "ai"]


class WebhookInput(CaptureInput):
    event_id: str = Field(min_length=1, max_length=120)


def site_response(site):
    return {"id": site.id, "name": site.name, "agent_id": site.agent_id,
            "enabled": site.enabled, "webhook_secret": site.webhook_secret}


async def public_site(db, site_id):
    site = await db.get(InboundSite, site_id)
    if not site or not site.enabled:
        raise HTTPException(404, "Widget unavailable")
    agent = await db.scalar(select(Agent).where(Agent.id == site.agent_id,
        Agent.organization_id == site.organization_id, Agent.status == "published"))
    if not agent or not agent.published_version_id:
        raise HTTPException(404, "Widget unavailable")
    return site, agent


async def visitor(db, site, authorization, lock=False):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Visitor session required")
    token = authorization[7:]
    if len(token) > 128:
        raise HTTPException(401, "Invalid visitor session")
    query = select(VisitorConversation).where(VisitorConversation.site_id == site.id,
        VisitorConversation.organization_id == site.organization_id,
        VisitorConversation.token_hash == token_digest(token), VisitorConversation.expires_at > datetime.now(UTC))
    if lock:
        query = query.with_for_update()
    conversation = await db.scalar(query)
    if not conversation:
        raise HTTPException(401, "Invalid visitor session")
    return conversation


def render_message(message):
    return {"id": str(message.id), "role": message.role, "content": message.content,
            "citations": message.citations, "created_at": message.created_at}


async def next_message_time(db, conversation_id):
    latest = await db.scalar(select(func.max(VisitorMessage.created_at)).where(VisitorMessage.conversation_id == conversation_id))
    now = datetime.now(UTC)
    if latest and latest.tzinfo is None:
        latest = latest.replace(tzinfo=UTC)
    return max(now, latest + timedelta(microseconds=1)) if latest else now


async def capture_lead(db, organization_id, payload: CaptureInput):
    email = str(payload.email).lower()
    contact = await db.scalar(select(Contact).where(Contact.organization_id == organization_id, Contact.email == email))
    if not contact:
        contact = Contact(organization_id=organization_id, name=payload.name, email=email)
        db.add(contact)
        await db.flush()
    lead = Lead(organization_id=organization_id, contact_id=contact.id,
                title=payload.enquiry[:200], stage="new")
    db.add(lead)
    await db.flush()
    return lead


@router.get("/inbound/site")
async def get_site(db: DbSession, context: Manager):
    site = await db.scalar(select(InboundSite).where(InboundSite.organization_id == context.organization.id))
    return site_response(site) if site else None


@router.put("/inbound/site")
async def configure_site(payload: SiteInput, db: DbSession, context: Manager, _user: Csrf):
    agent = await db.scalar(select(Agent).where(Agent.id == payload.agent_id,
        Agent.organization_id == context.organization.id, Agent.status == "published"))
    if not agent or not agent.published_version_id:
        raise HTTPException(400, "Choose a published AI employee in your organization")
    site = await db.scalar(select(InboundSite).where(InboundSite.organization_id == context.organization.id))
    if not site:
        site = InboundSite(organization_id=context.organization.id, webhook_secret=secrets.token_urlsafe(32), **payload.model_dump())
        db.add(site)
    else:
        for key, value in payload.model_dump().items():
            setattr(site, key, value)
    await db.commit()
    await db.refresh(site)
    return site_response(site)


@router.get("/inbound/conversations")
async def list_inbound(db: DbSession, context: Tenant):
    query = select(VisitorConversation).where(VisitorConversation.organization_id == context.organization.id)
    if context.membership.role == MembershipRole.employee:
        query = query.where(VisitorConversation.assigned_to == context.user.id)
    rows = (await db.scalars(query.order_by(VisitorConversation.created_at.desc()).limit(100))).all()
    return [{"id": item.id, "name": item.visitor_name, "email": item.visitor_email,
             "status": item.status, "assigned_to": item.assigned_to, "lead_id": item.lead_id,
             "context": item.context, "created_at": item.created_at} for item in rows]


async def staff_conversation(db, org_id, conversation_id):
    conversation = await db.scalar(select(VisitorConversation).where(
        VisitorConversation.id == conversation_id, VisitorConversation.organization_id == org_id).with_for_update())
    if not conversation:
        raise HTTPException(404, "Conversation not found")
    return conversation


@router.get("/inbound/conversations/{conversation_id}")
async def read_inbound(conversation_id: uuid.UUID, db: DbSession, context: Tenant):
    conversation = await staff_conversation(db, context.organization.id, conversation_id)
    if context.membership.role == MembershipRole.employee and conversation.assigned_to != context.user.id:
        raise HTTPException(404, "Conversation not found")
    messages = (await db.scalars(select(VisitorMessage).where(VisitorMessage.conversation_id == conversation.id).order_by(VisitorMessage.created_at, VisitorMessage.id))).all()
    return {"status": conversation.status, "assigned_to": conversation.assigned_to, "context": conversation.context,
            "messages": [render_message(item) for item in messages]}


@router.post("/inbound/conversations/{conversation_id}/assign")
async def assign_inbound(conversation_id: uuid.UUID, payload: AssignmentInput, db: DbSession, context: Manager, _user: Csrf):
    conversation = await staff_conversation(db, context.organization.id, conversation_id)
    if payload.assigned_to:
        member = await db.scalar(select(Membership.id).join(User, User.id == Membership.user_id).where(
            Membership.organization_id == context.organization.id, Membership.user_id == payload.assigned_to, Membership.is_active.is_(True), User.is_active.is_(True)))
        if not member:
            raise HTTPException(400, "Assigned person must be an active member")
    conversation.assigned_to = payload.assigned_to
    conversation.status = payload.status
    if conversation.lead_id:
        lead = await db.scalar(select(Lead).where(Lead.id == conversation.lead_id, Lead.organization_id == context.organization.id))
        if lead:
            lead.owner_id = payload.assigned_to
    await db.commit()
    return {"status": conversation.status, "assigned_to": conversation.assigned_to}


@router.post("/inbound/conversations/{conversation_id}/reply")
async def reply_inbound(conversation_id: uuid.UUID, payload: MessageInput, db: DbSession, context: Tenant, _user: Csrf):
    conversation = await staff_conversation(db, context.organization.id, conversation_id)
    if conversation.status != "human":
        raise HTTPException(409, "Conversation is not awaiting a human reply")
    if context.membership.role == MembershipRole.employee and conversation.assigned_to != context.user.id:
        raise HTTPException(403, "Conversation is not assigned to you")
    message = VisitorMessage(conversation_id=conversation.id, role="staff", content=payload.message, citations=[], created_at=await next_message_time(db, conversation.id))
    db.add(message)
    await db.commit()
    await db.refresh(message)
    return render_message(message)


@router.get("/public/inbound/{site_id}/config")
async def public_config(site_id: uuid.UUID, request: Request, db: DbSession):
    await check_rate_limit(request, str(site_id), "config", 60)
    site, _ = await public_site(db, site_id)
    return {"name": site.name}


@router.post("/public/inbound/{site_id}/sessions", status_code=201)
async def start_visitor(site_id: uuid.UUID, request: Request, db: DbSession):
    await check_rate_limit(request, str(site_id), "session", 15)
    site, _ = await public_site(db, site_id)
    token = secrets.token_urlsafe(32)
    conversation = VisitorConversation(organization_id=site.organization_id, site_id=site.id,
        token_hash=token_digest(token), context={}, status="ai", expires_at=datetime.now(UTC) + timedelta(days=7))
    db.add(conversation)
    await db.commit()
    return {"token": token, "conversation_id": conversation.id}


@router.get("/public/inbound/{site_id}/messages")
async def visitor_messages(site_id: uuid.UUID, request: Request, db: DbSession, authorization: Annotated[str | None, Header()] = None):
    await check_rate_limit(request, str(site_id), "poll", 120)
    site, _ = await public_site(db, site_id)
    conversation = await visitor(db, site, authorization)
    messages = (await db.scalars(select(VisitorMessage).where(VisitorMessage.conversation_id == conversation.id).order_by(VisitorMessage.created_at, VisitorMessage.id).limit(200))).all()
    return {"status": conversation.status, "messages": [render_message(item) for item in messages]}


@router.post("/public/inbound/{site_id}/messages")
async def visitor_send(site_id: uuid.UUID, payload: MessageInput, request: Request, db: DbSession, authorization: Annotated[str | None, Header()] = None):
    await check_rate_limit(request, str(site_id), "message", 20)
    site, agent = await public_site(db, site_id)
    conversation = await visitor(db, site, authorization, lock=True)
    if conversation.status == "closed":
        raise HTTPException(409, "Conversation is closed")
    prior = list((await db.scalars(select(VisitorMessage).where(VisitorMessage.conversation_id == conversation.id)
        .order_by(VisitorMessage.created_at.desc(), VisitorMessage.id.desc()).limit(20))).all())
    prior.reverse()
    now = await next_message_time(db, conversation.id)
    db.add(VisitorMessage(conversation_id=conversation.id, role="user", content=payload.message, citations=[], created_at=now))
    if conversation.status == "human":
        await db.commit()
        return {"status": "human", "answer": None, "citations": []}
    version = await db.get(AgentVersion, agent.published_version_id)
    if not version or version.agent_id != agent.id:
        raise HTTPException(503, "Support agent is unavailable")
    ready = await db.scalar(select(func.count(KnowledgeDocument.id)).where(
        KnowledgeDocument.organization_id == site.organization_id, KnowledgeDocument.status == "ready"))
    inputs = [{"role": "assistant" if m.role in {"assistant", "staff"} else "user", "content": m.content} for m in prior]
    inputs.append({"role": "user", "content": payload.message})
    async def no_tools(name, arguments, call_id):
        raise ProviderError("Tools are unavailable in public chat")
    try:
        answer, sources = await run_rag_agent(db=db, organization_id=site.organization_id, query=payload.message,
            model=version.model, prompt=f"Role: {version.role}\nTone: {version.tone}\nLanguage: {version.language}\n{version.instructions}\nBe honest when information is unavailable. Never claim a human has replied unless they have.",
            inputs=inputs, tool_names=[], tool_handler=no_tools, use_knowledge=bool(ready))
    except (ProviderError, EmbeddingError) as exc:
        await db.rollback()
        raise HTTPException(503, "Support is temporarily unavailable. Please try again.") from exc
    citations = [{"number": index + 1, "filename": source.filename} for index, source in enumerate(sources)]
    db.add(VisitorMessage(conversation_id=conversation.id, role="assistant", content=answer,
        citations=citations, created_at=now + timedelta(microseconds=1)))
    await db.commit()
    return {"status": "ai", "answer": answer, "citations": citations}


@router.post("/public/inbound/{site_id}/lead", status_code=201)
async def visitor_capture(site_id: uuid.UUID, payload: CaptureInput, request: Request, db: DbSession, authorization: Annotated[str | None, Header()] = None):
    await check_rate_limit(request, str(site_id), "lead", 8)
    site, _ = await public_site(db, site_id)
    conversation = await visitor(db, site, authorization, lock=True)
    if conversation.lead_id:
        raise HTTPException(409, "Your enquiry has already been submitted")
    try:
        lead = await capture_lead(db, site.organization_id, payload)
        conversation.visitor_name, conversation.visitor_email = payload.name, str(payload.email).lower()
        conversation.context = {"source": "website", "enquiry": payload.enquiry, "budget": payload.budget, "timeline": payload.timeline}
        conversation.lead_id = lead.id
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(409, "Please retry your enquiry") from exc
    return {"message": "Your enquiry has been received."}


@router.post("/public/inbound/{site_id}/handoff")
async def visitor_handoff(site_id: uuid.UUID, request: Request, db: DbSession, authorization: Annotated[str | None, Header()] = None):
    await check_rate_limit(request, str(site_id), "handoff", 10)
    site, _ = await public_site(db, site_id)
    conversation = await visitor(db, site, authorization, lock=True)
    if conversation.status == "closed":
        raise HTTPException(409, "Conversation is closed")
    conversation.status = "human"
    await db.commit()
    return {"message": "Your request has been sent to the team."}


@router.post("/public/inbound/{site_id}/webhook")
async def inbound_webhook(site_id: uuid.UUID, request: Request, db: DbSession,
    x_timestamp: Annotated[str | None, Header()] = None, x_signature: Annotated[str | None, Header()] = None):
    await check_rate_limit(request, str(site_id), "webhook", 60)
    site, _ = await public_site(db, site_id)
    body = await request.body()
    if len(body) > 16384:
        raise HTTPException(413, "Payload too large")
    try:
        timestamp = int(x_timestamp or "")
    except ValueError:
        raise HTTPException(401, "Invalid webhook signature")
    if abs(time.time() - timestamp) > 300 or not x_signature:
        raise HTTPException(401, "Invalid webhook signature")
    expected = hmac.new(site.webhook_secret.encode(), str(timestamp).encode() + b"." + body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, x_signature):
        raise HTTPException(401, "Invalid webhook signature")
    try:
        payload = WebhookInput.model_validate_json(body)
    except ValidationError as exc:
        raise HTTPException(422, "Invalid webhook payload") from exc
    existing = await db.scalar(select(InboundWebhookEvent).where(InboundWebhookEvent.site_id == site.id, InboundWebhookEvent.event_id == payload.event_id))
    if existing:
        return {"status": "already_received"}
    try:
        lead = await capture_lead(db, site.organization_id, payload)
        db.add(InboundWebhookEvent(site_id=site.id, event_id=payload.event_id, lead_id=lead.id))
        db.add(VisitorConversation(organization_id=site.organization_id, site_id=site.id,
            token_hash=token_digest(secrets.token_urlsafe(32)), visitor_name=payload.name,
            visitor_email=str(payload.email).lower(), status="human", lead_id=lead.id,
            expires_at=datetime.now(UTC) + timedelta(days=7),
            context={"source": "webhook", "enquiry": payload.enquiry, "budget": payload.budget, "timeline": payload.timeline}))
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(409, "Event already received or contact changed; retry") from exc
    return {"status": "received"}
