"""Permission-filtered projections over existing operational records."""

from datetime import UTC, datetime

from sqlalchemy import String, cast, func, literal, select, union_all

from app.core.permissions import has_permission
from app.models.agent import AgentToolRequest
from app.models.auth import Invitation, Membership, User
from app.models.campaign import Campaign, CampaignAudit
from app.models.crm import CRMActivity, Lead
from app.models.inbound import VisitorConversation
from app.models.knowledge import KnowledgeDocument
from app.models.messaging import OutboundMessage

WIDGETS = ["metrics", "leads", "pipeline", "knowledge", "activity", "approvals"]
MODULES = ["agents", "knowledge", "crm", "inbound", "messaging", "campaigns", "people"]


def event_query(
    model,
    prefix,
    title,
    detail,
    view,
    *filters,
    record=None,
    timestamp=None,
    status_key=False,
    severity="info",
):
    key = literal(prefix + "-") + func.replace(cast(model.id, String), "-", "")
    if status_key:
        key = key + literal("-") + model.status
    return select(
        key.label("id"),
        literal(title).label("title"),
        detail.label("detail"),
        (timestamp if timestamp is not None else model.created_at).label("occurred_at"),
        literal(view).label("view"),
        cast(record if record is not None else model.id, String).label("record_id"),
        literal(severity).label("severity"),
    ).where(*filters)


def notification_source(context):
    org, user, role = context.organization.id, context.user.id, context.membership.role
    queries = [
        event_query(
            KnowledgeDocument,
            "document",
            "Document processing failed",
            KnowledgeDocument.filename,
            "knowledge",
            KnowledgeDocument.organization_id == org,
            KnowledgeDocument.status == "failed",
            status_key=True,
            severity="warning",
        )
    ]
    tool_filters = [
        AgentToolRequest.organization_id == org,
        AgentToolRequest.status.in_(["pending", "failed", "resume_failed", "timed_out"]),
    ]
    if not has_permission(role, "agents.manage"):
        tool_filters.append(AgentToolRequest.requested_by == user)
    queries.append(
        event_query(
            AgentToolRequest,
            "tool",
            "AI employee action needs attention",
            AgentToolRequest.tool_name + literal(" · ") + AgentToolRequest.status,
            "agents",
            *tool_filters,
            record=AgentToolRequest.agent_id,
            timestamp=AgentToolRequest.updated_at,
            status_key=True,
            severity="warning",
        )
    )
    inbox_filters = [
        VisitorConversation.organization_id == org,
        VisitorConversation.status == "human",
    ]
    if not has_permission(role, "inbox.manage"):
        inbox_filters.append(VisitorConversation.assigned_to == user)
    queries.append(
        event_query(
            VisitorConversation,
            "inbound",
            "Visitor needs human support",
            func.coalesce(VisitorConversation.visitor_name, "Website visitor"),
            "inbound",
            *inbox_filters,
            status_key=True,
        )
    )
    if has_permission(role, "invitations.manage"):
        queries.append(
            event_query(
                Invitation,
                "invitation",
                "Invitation awaiting acceptance",
                Invitation.email + literal(" was invited to this workspace."),
                "people",
                Invitation.organization_id == org,
                Invitation.accepted_at.is_(None),
                Invitation.revoked_at.is_(None),
                Invitation.expires_at > datetime.now(UTC),
            )
        )
    if has_permission(role, "campaigns.manage"):
        queries.append(
            event_query(
                Campaign,
                "campaign",
                "Campaign needs attention",
                Campaign.name + literal(" · ") + Campaign.status,
                "campaigns",
                Campaign.organization_id == org,
                Campaign.status.in_(["failed", "pending_approval"]),
                timestamp=Campaign.updated_at,
                status_key=True,
            )
        )
    if has_permission(role, "integrations.manage"):
        queries.append(
            event_query(
                OutboundMessage,
                "message",
                "Message delivery needs review",
                OutboundMessage.channel + literal(" · ") + OutboundMessage.status,
                "messaging",
                OutboundMessage.organization_id == org,
                OutboundMessage.status.in_(["failed", "unknown"]),
                timestamp=func.coalesce(OutboundMessage.started_at, OutboundMessage.created_at),
                status_key=True,
                severity="warning",
            )
        )
    return union_all(*queries).subquery("visible_notifications")


def activity_source(context):
    org, user, role = context.organization.id, context.user.id, context.membership.role
    queries = [
        event_query(
            Membership,
            "member",
            "Member joined",
            User.full_name + literal(" joined this workspace."),
            "people" if has_permission(role, "invitations.manage") else "overview",
            Membership.organization_id == org,
        ).join(User, User.id == Membership.user_id),
        event_query(Lead, "lead", "Lead captured", Lead.title, "crm", Lead.organization_id == org),
        event_query(
            CRMActivity,
            "crm",
            "CRM activity recorded",
            CRMActivity.kind,
            "crm",
            CRMActivity.organization_id == org,
            record=CRMActivity.lead_id,
        ),
        event_query(
            KnowledgeDocument,
            "knowledge",
            "Knowledge document uploaded",
            KnowledgeDocument.filename,
            "knowledge",
            KnowledgeDocument.organization_id == org,
        ),
    ]
    conditions = [AgentToolRequest.organization_id == org]
    if not has_permission(role, "agents.manage"):
        conditions.append(AgentToolRequest.requested_by == user)
    queries.append(
        event_query(
            AgentToolRequest,
            "action",
            "AI employee action",
            AgentToolRequest.tool_name + literal(" · ") + AgentToolRequest.status,
            "agents",
            *conditions,
            record=AgentToolRequest.agent_id,
            timestamp=AgentToolRequest.updated_at,
            status_key=True,
        )
    )
    if has_permission(role, "campaigns.manage"):
        queries.append(
            event_query(
                Campaign,
                "campaign",
                "Campaign updated",
                Campaign.name + literal(" · ") + Campaign.status,
                "campaigns",
                Campaign.organization_id == org,
                timestamp=Campaign.updated_at,
                status_key=True,
            )
        )
        queries.append(
            event_query(
                CampaignAudit,
                "audit",
                "Campaign activity",
                func.replace(CampaignAudit.action, "_", " "),
                "campaigns",
                CampaignAudit.organization_id == org,
                CampaignAudit.campaign_id.is_not(None),
                record=CampaignAudit.campaign_id,
            )
        )
    return union_all(*queries).subquery("visible_activity")


def event_payload(row):
    item = dict(row)
    if item["occurred_at"].tzinfo is None:
        item["occurred_at"] = item["occurred_at"].replace(tzinfo=UTC)
    return item
