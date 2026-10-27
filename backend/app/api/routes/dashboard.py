from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select

from app.api.dependencies import DbSession, TenantContext, get_tenant_context
from app.models.auth import Invitation, Membership, MembershipRole, User

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


class ActivityItem(BaseModel):
    id: str
    title: str
    detail: str
    occurred_at: datetime


class DashboardResponse(BaseModel):
    member_count: int
    pending_invitation_count: int | None
    activity: list[ActivityItem]
    notifications: list[ActivityItem]


@router.get("", response_model=DashboardResponse)
async def dashboard(
    db: DbSession,
    context: Annotated[TenantContext, Depends(get_tenant_context)],
) -> DashboardResponse:
    organization_id = context.organization.id
    member_count = await db.scalar(
        select(func.count(Membership.id)).where(Membership.organization_id == organization_id)
    )
    members = (
        await db.execute(
            select(Membership, User)
            .join(User, User.id == Membership.user_id)
            .where(Membership.organization_id == organization_id)
            .order_by(Membership.created_at.desc(), Membership.id.desc())
            .limit(10)
        )
    ).all()
    activity = [
        ActivityItem(
            id=f"member-{membership.id}",
            title="Member joined",
            detail=f"{user.full_name} joined as {membership.role.value}.",
            occurred_at=membership.created_at,
        )
        for membership, user in members
    ]
    pending_count = None
    notifications = []
    if context.membership.role in {MembershipRole.admin, MembershipRole.manager}:
        now = datetime.now(UTC)
        pending_filter = (
            Invitation.organization_id == organization_id,
            Invitation.accepted_at.is_(None),
            Invitation.expires_at > now,
        )
        pending_count = await db.scalar(select(func.count(Invitation.id)).where(*pending_filter))
        invitations = (
            await db.scalars(
                select(Invitation)
                .where(*pending_filter)
                .order_by(Invitation.created_at.desc(), Invitation.id.desc())
                .limit(10)
            )
        ).all()
        notifications = [
            ActivityItem(
                id=f"invitation-{invitation.id}",
                title="Invitation awaiting acceptance",
                detail=f"{invitation.email} was invited as {invitation.role.value}.",
                occurred_at=invitation.created_at,
            )
            for invitation in invitations
        ]
    return DashboardResponse(
        member_count=member_count or 0,
        pending_invitation_count=pending_count,
        activity=activity,
        notifications=notifications,
    )
