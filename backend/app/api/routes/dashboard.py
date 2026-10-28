from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

from app.api.dependencies import DbSession, TenantContext, require_csrf, require_permission
from app.core.audit import record_audit
from app.core.dashboard import MODULES, WIDGETS, activity_source, event_payload, notification_source
from app.core.permissions import has_permission
from app.models.agent import Agent, AgentToolRequest
from app.models.auth import Invitation, Membership, User
from app.models.campaign import Campaign
from app.models.crm import Company, Contact, Deal, Lead
from app.models.dashboard import DashboardConfiguration, NotificationReceipt
from app.models.inbound import VisitorConversation
from app.models.knowledge import KnowledgeDocument
from app.models.messaging import MessageEvent, OutboundMessage

router = APIRouter(prefix="/dashboard", tags=["dashboard"])
Tenant = Annotated[TenantContext, Depends(require_permission("workspace.read"))]
Admin = Annotated[TenantContext, Depends(require_permission("organization.manage"))]
Csrf = Annotated[User, Depends(require_csrf)]


class LayoutInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    industry: Literal["general", "real_estate", "holiday_homes", "clinic", "services"] = "general"
    widgets: list[str] = Field(default_factory=lambda: list(WIDGETS), min_length=1, max_length=6)
    visible_modules: list[str] = Field(default_factory=lambda: list(MODULES), max_length=7)

    @field_validator("widgets", "visible_modules")
    @classmethod
    def known_values(cls, values, info):
        allowed = WIDGETS if info.field_name == "widgets" else MODULES
        if len(set(values)) != len(values) or any(value not in allowed for value in values):
            raise ValueError("Unknown or duplicate dashboard option")
        return values


async def layout(db, context):
    item = await db.get(DashboardConfiguration, context.organization.id)
    return (
        LayoutInput.model_validate(
            {
                "industry": item.industry,
                "widgets": item.widgets,
                "visible_modules": item.visible_modules,
            }
        )
        if item
        else LayoutInput()
    )


async def notifications_page(db, context, page=1, page_size=20, state="all"):
    source = notification_source(context)
    receipt = NotificationReceipt
    joined = source.outerjoin(
        receipt,
        (receipt.organization_id == context.organization.id)
        & (receipt.user_id == context.user.id)
        & (receipt.notification_key == source.c.id),
    )
    unread = await db.scalar(select(func.count()).select_from(joined).where(receipt.id.is_(None)))
    query = select(*source.c, receipt.read_at).select_from(joined)
    if state == "unread":
        query = query.where(receipt.id.is_(None))
    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    rows = (
        (
            await db.execute(
                query.order_by(source.c.occurred_at.desc(), source.c.id)
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        .mappings()
        .all()
    )
    return {
        "items": [event_payload(row) for row in rows],
        "total": total,
        "unread_count": unread,
        "page": page,
        "page_size": page_size,
    }


@router.get("")
async def dashboard(db: DbSession, context: Tenant, days: int = Query(30, ge=1, le=90)):
    org, role = context.organization.id, context.membership.role
    now = datetime.now(UTC)
    since = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days - 1)

    async def count(model, *conditions, period=False):
        filters = [model.organization_id == org, *conditions]
        if period:
            filters.extend([model.created_at >= since, model.created_at <= now])
        return await db.scalar(select(func.count()).select_from(model).where(*filters)) or 0

    metrics = {
        "active_agents": await count(
            Agent, Agent.status == "published", Agent.published_version_id.is_not(None)
        ),
        "contacts": await count(Contact, period=True),
        "leads": await count(Lead, period=True),
        "deals": await count(Deal, period=True),
        "documents_ready": await count(KnowledgeDocument, KnowledgeDocument.status == "ready"),
        "documents_processing": await count(
            KnowledgeDocument, KnowledgeDocument.status.in_(["queued", "processing"])
        ),
        "documents_failed": await count(KnowledgeDocument, KnowledgeDocument.status == "failed"),
    }
    inbox_filters = (
        []
        if has_permission(role, "inbox.manage")
        else [VisitorConversation.assigned_to == context.user.id]
    )
    metrics["human_conversations"] = await count(
        VisitorConversation, VisitorConversation.status == "human", *inbox_filters
    )
    if has_permission(role, "agents.manage"):
        metrics["pending_tool_approvals"] = await count(
            AgentToolRequest, AgentToolRequest.status == "pending"
        )
        metrics["failed_actions"] = await count(
            AgentToolRequest, AgentToolRequest.status.in_(["failed", "resume_failed", "timed_out"])
        )
    if has_permission(role, "campaigns.manage"):
        metrics["campaigns"] = await count(Campaign, period=True)
        metrics["recorded_replies"] = await count(
            MessageEvent, MessageEvent.kind == "reply", period=True
        )
        metrics["campaign_approvals"] = await count(Campaign, Campaign.status == "pending_approval")
        metrics["messages_sent"] = await count(
            OutboundMessage,
            OutboundMessage.status.in_(["accepted", "sent", "delivered"]),
            period=True,
        )
        metrics["messages_failed"] = await count(
            OutboundMessage, OutboundMessage.status.in_(["failed", "unknown"]), period=True
        )
    stages = (
        await db.execute(
            select(Lead.stage, func.count())
            .where(Lead.organization_id == org, Lead.created_at >= since, Lead.created_at <= now)
            .group_by(Lead.stage)
        )
    ).all()
    trend_rows = (
        await db.execute(
            select(func.date(Lead.created_at), func.count())
            .where(Lead.organization_id == org, Lead.created_at >= since, Lead.created_at <= now)
            .group_by(func.date(Lead.created_at))
        )
    ).all()
    trend = {str(day): count for day, count in trend_rows}
    pipeline = (
        await db.execute(
            select(Deal.currency, func.count(), func.sum(Deal.amount_minor))
            .where(
                Deal.organization_id == org,
                Deal.created_at >= since,
                Deal.created_at <= now,
                Deal.stage.notin_(["won", "lost"]),
            )
            .group_by(Deal.currency)
        )
    ).all()
    source = activity_source(context)
    activity = (
        (
            await db.execute(
                select(source)
                .where(source.c.occurred_at >= since, source.c.occurred_at <= now)
                .order_by(source.c.occurred_at.desc(), source.c.id)
                .limit(20)
            )
        )
        .mappings()
        .all()
    )
    alerts = await notifications_page(db, context, page_size=10)
    pending = (
        await count(
            Invitation,
            Invitation.accepted_at.is_(None),
            Invitation.revoked_at.is_(None),
            Invitation.expires_at > now,
        )
        if has_permission(role, "invitations.manage")
        else None
    )
    member_count = await db.scalar(
        select(func.count(Membership.id))
        .join(User, User.id == Membership.user_id)
        .where(
            Membership.organization_id == org,
            Membership.is_active.is_(True),
            User.is_active.is_(True),
        )
    )
    return {
        "member_count": member_count or 0,
        "pending_invitation_count": pending,
        "activity": [event_payload(row) for row in activity],
        "notifications": alerts["items"],
        "unread_count": alerts["unread_count"],
        "notification_total": alerts["total"],
        "metrics": metrics,
        "lead_stages": [{"stage": stage, "count": count} for stage, count in stages],
        "lead_trend": [
            {
                "date": (since + timedelta(days=i)).date().isoformat(),
                "count": trend.get((since + timedelta(days=i)).date().isoformat(), 0),
            }
            for i in range(days)
        ],
        "pipeline": [
            {"currency": currency, "count": count, "amount_minor": amount}
            for currency, count, amount in pipeline
        ],
        "configuration": await layout(db, context),
        "period": {"days": days, "since": since, "through": now},
        "updated_at": now,
        "unavailable": ["calling", "appointments", "properties", "tasks", "finance"],
    }


@router.put("/configuration")
async def update_layout(payload: LayoutInput, db: DbSession, context: Admin, _csrf: Csrf):
    from app.api.routes.organizations import lock_organization

    await lock_organization(db, context, "organization.manage")
    item = await db.get(DashboardConfiguration, context.organization.id)
    if not item:
        item = DashboardConfiguration(organization_id=context.organization.id)
        db.add(item)
    item.industry, item.widgets, item.visible_modules = (
        payload.industry,
        payload.widgets,
        payload.visible_modules,
    )
    record_audit(
        db, context.organization.id, "dashboard_configured", context.user.id, module="dashboard"
    )
    await db.commit()
    return payload


@router.get("/notifications")
async def notifications(
    db: DbSession,
    context: Tenant,
    page: int = Query(1, ge=1, le=10000),
    page_size: int = Query(20, ge=1, le=50),
    state: Literal["all", "unread"] = "all",
):
    return await notifications_page(db, context, page, page_size, state)


class ReadInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    read: bool


@router.put("/notifications/{notification_key}/read", status_code=204)
async def mark_read(
    notification_key: str, payload: ReadInput, db: DbSession, context: Tenant, _csrf: Csrf
):
    if len(notification_key) > 120:
        raise HTTPException(404, "Notification not found")
    source = notification_source(context)
    if not await db.scalar(select(source.c.id).where(source.c.id == notification_key)):
        raise HTTPException(404, "Notification not found")
    filters = [
        NotificationReceipt.organization_id == context.organization.id,
        NotificationReceipt.user_id == context.user.id,
        NotificationReceipt.notification_key == notification_key,
    ]
    existing = await db.scalar(select(NotificationReceipt).where(*filters))
    if payload.read and not existing:
        db.add(
            NotificationReceipt(
                organization_id=context.organization.id,
                user_id=context.user.id,
                notification_key=notification_key,
            )
        )
    elif not payload.read:
        await db.execute(delete(NotificationReceipt).where(*filters))
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()  # A simultaneous idempotent read already inserted the receipt.


@router.get("/search")
async def search(db: DbSession, context: Tenant, q: str = Query(min_length=2, max_length=100)):
    term = q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    if len(q.strip()) < 2:
        return {"items": []}
    sources = [
        (Contact, Contact.name, "crm", "contacts"),
        (Company, Company.name, "crm", "companies"),
        (Lead, Lead.title, "crm", "leads"),
        (Deal, Deal.title, "crm", "deals"),
        (Agent, Agent.name, "agents", "agents"),
        (KnowledgeDocument, KnowledgeDocument.filename, "knowledge", "documents"),
    ]
    if has_permission(context.membership.role, "campaigns.manage"):
        sources.append((Campaign, Campaign.name, "campaigns", "campaigns"))
    items = []
    for model, label, view, kind in sources:
        query = select(model.id, label).where(
            model.organization_id == context.organization.id, label.ilike(f"%{term}%", escape="\\")
        )
        if model == Agent and not has_permission(context.membership.role, "agents.manage"):
            query = query.where(
                Agent.status == "published", Agent.published_version_id.is_not(None)
            )
        rows = (await db.execute(query.order_by(label, model.id).limit(5))).all()
        items.extend(
            {"id": str(id), "label": name, "view": view, "kind": kind} for id, name in rows
        )
    return {"items": items}
