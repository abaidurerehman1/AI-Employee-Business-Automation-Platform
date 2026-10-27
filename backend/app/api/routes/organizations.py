from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import select

from app.api.dependencies import (
    DbSession,
    TenantContext,
    get_current_user,
    get_tenant_context,
    require_csrf,
    require_roles,
)
from app.core.email import send_invitation_email
from app.core.security import new_token, token_digest
from app.models.auth import Invitation, Membership, MembershipRole, User
from app.schemas.auth import (
    InvitationResponse,
    InviteRequest,
    MemberResponse,
    MessageResponse,
    TokenRequest,
)

router = APIRouter(prefix="/organizations", tags=["organizations"])


@router.get("/current/members", response_model=list[MemberResponse])
async def list_members(
    db: DbSession,
    context: Annotated[TenantContext, Depends(get_tenant_context)],
) -> list[MemberResponse]:
    rows = await db.execute(
        select(User, Membership)
        .join(Membership, Membership.user_id == User.id)
        .where(Membership.organization_id == context.organization.id)
        .order_by(User.full_name)
    )
    return [
        MemberResponse(id=user.id, email=user.email, full_name=user.full_name, role=member.role)
        for user, member in rows.all()
    ]


@router.post(
    "/current/invitations",
    response_model=InvitationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_invitation(
    payload: InviteRequest,
    db: DbSession,
    background_tasks: BackgroundTasks,
    context: Annotated[
        TenantContext,
        Depends(require_roles(MembershipRole.admin, MembershipRole.manager)),
    ],
    _csrf_user: Annotated[User, Depends(require_csrf)],
) -> InvitationResponse:
    if context.membership.role == MembershipRole.manager and payload.role == MembershipRole.admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Managers cannot invite administrators")
    email = str(payload.email).lower()
    existing = await db.scalar(
        select(Membership)
        .join(User, User.id == Membership.user_id)
        .where(User.email == email, Membership.organization_id == context.organization.id)
    )
    if existing:
        raise HTTPException(status.HTTP_409_CONFLICT, "User is already a member")
    raw_token = new_token()
    invitation = Invitation(
        organization_id=context.organization.id,
        email=email,
        role=payload.role,
        token_hash=token_digest(raw_token),
        invited_by_user_id=context.user.id,
        expires_at=datetime.now(UTC) + timedelta(days=7),
    )
    db.add(invitation)
    await db.commit()
    await db.refresh(invitation)
    background_tasks.add_task(send_invitation_email, email, context.organization.name, raw_token)
    return InvitationResponse(
        id=invitation.id,
        email=invitation.email,
        role=invitation.role,
        expires_at=invitation.expires_at,
    )


@router.post("/invitations/accept", response_model=MessageResponse)
async def accept_invitation(
    payload: TokenRequest,
    db: DbSession,
    user: Annotated[User, Depends(get_current_user)],
    _csrf_user: Annotated[User, Depends(require_csrf)],
) -> MessageResponse:
    invitation = await db.scalar(
        select(Invitation).where(
            Invitation.token_hash == token_digest(payload.token),
            Invitation.accepted_at.is_(None),
            Invitation.expires_at > datetime.now(UTC),
        )
    )
    if not invitation or invitation.email != user.email:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid or expired invitation")
    existing = await db.scalar(
        select(Membership).where(
            Membership.user_id == user.id,
            Membership.organization_id == invitation.organization_id,
        )
    )
    if not existing:
        db.add(
            Membership(
                user_id=user.id,
                organization_id=invitation.organization_id,
                role=invitation.role,
            )
        )
    invitation.accepted_at = datetime.now(UTC)
    await db.commit()
    return MessageResponse(message="Invitation accepted")
