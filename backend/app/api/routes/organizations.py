import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import func, select, update

from app.api.dependencies import (
    DbSession,
    TenantContext,
    get_current_user,
    get_tenant_context,
    require_csrf,
    require_permission,
)
from app.core.audit import record_audit
from app.core.email import send_invitation_email
from app.core.permissions import has_permission
from app.core.security import new_token, token_digest, verify_password
from app.models.auth import Invitation, Membership, MembershipRole, Organization, User
from app.schemas.auth import (
    InvitationResponse,
    InviteRequest,
    MemberInput,
    MemberResponse,
    MessageResponse,
    OrganizationInput,
    OwnershipInput,
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
        MemberResponse(
            id=user.id,
            email=user.email,
            full_name=user.full_name,
            role=member.role,
            is_active=member.is_active,
        )
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
        Depends(require_permission("invitations.manage")),
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
    await lock_organization(db, context, "invitations.manage")
    if context.membership.role == MembershipRole.manager and payload.role == MembershipRole.admin:
        raise HTTPException(403, "Managers cannot invite administrators")
    await db.execute(
        update(Invitation)
        .where(
            Invitation.organization_id == context.organization.id,
            Invitation.email == email,
            Invitation.accepted_at.is_(None),
            Invitation.revoked_at.is_(None),
        )
        .values(revoked_at=datetime.now(UTC))
    )
    invitation = Invitation(
        organization_id=context.organization.id,
        email=email,
        role=payload.role,
        token_hash=token_digest(raw_token),
        invited_by_user_id=context.user.id,
        expires_at=datetime.now(UTC) + timedelta(days=7),
    )
    db.add(invitation)
    record_audit(
        db,
        context.organization.id,
        "invitation_created",
        context.user.id,
        module="identity",
        detail={"role": payload.role.value},
    )
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
    query = select(Invitation).where(
        Invitation.token_hash == token_digest(payload.token),
        Invitation.accepted_at.is_(None),
        Invitation.revoked_at.is_(None),
        Invitation.expires_at > datetime.now(UTC),
    )
    candidate = await db.scalar(query)
    if not candidate:
        raise HTTPException(400, "Invalid or expired invitation")
    await db.scalar(
        select(Organization).where(Organization.id == candidate.organization_id).with_for_update()
    )
    invitation = await db.scalar(query.with_for_update().execution_options(populate_existing=True))
    if not invitation or invitation.email != user.email:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid or expired invitation")
    inviter = await db.scalar(
        select(Membership)
        .join(User, User.id == Membership.user_id)
        .where(
            Membership.user_id == invitation.invited_by_user_id,
            Membership.organization_id == invitation.organization_id,
            Membership.is_active.is_(True),
            User.is_active.is_(True),
        )
    )
    if (
        not inviter
        or inviter.role not in {MembershipRole.admin, MembershipRole.manager}
        or (invitation.role == MembershipRole.admin and inviter.role != MembershipRole.admin)
    ):
        raise HTTPException(400, "Invalid or expired invitation")
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
    record_audit(db, invitation.organization_id, "invitation_accepted", user.id, module="identity")
    await db.commit()
    return MessageResponse(message="Invitation accepted")


Tenant = Annotated[TenantContext, Depends(get_tenant_context)]
Admin = Annotated[TenantContext, Depends(require_permission("members.manage"))]
Manager = Annotated[TenantContext, Depends(require_permission("invitations.manage"))]
Csrf = Annotated[User, Depends(require_csrf)]


@router.post("", status_code=201)
async def create_organization(
    payload: OrganizationInput,
    db: DbSession,
    user: Annotated[User, Depends(get_current_user)],
    _csrf: Csrf,
):
    from app.api.routes.auth import slugify

    item = Organization(
        name=payload.name,
        slug=f"{slugify(payload.name)}-{new_token()[:8].lower()}",
        owner_user_id=user.id,
    )
    db.add(item)
    await db.flush()
    db.add(Membership(user_id=user.id, organization_id=item.id, role=MembershipRole.admin))
    record_audit(db, item.id, "organization_created", user.id, module="identity")
    await db.commit()
    return {"id": item.id, "name": item.name, "owner_user_id": item.owner_user_id}


@router.get("/current")
async def organization_profile(context: Tenant):
    item = context.organization
    return {
        "id": item.id,
        "name": item.name,
        "slug": item.slug,
        "owner_user_id": item.owner_user_id,
    }


@router.put("/current")
async def update_organization(
    payload: OrganizationInput, db: DbSession, context: Admin, _csrf: Csrf
):
    item = await lock_organization(db, context, "organization.manage")
    item.name = payload.name
    record_audit(db, item.id, "organization_updated", context.user.id, module="identity")
    await db.commit()
    return {"id": item.id, "name": item.name, "owner_user_id": item.owner_user_id}


@router.get("/current/invitations")
async def list_invitations(db: DbSession, context: Manager):
    rows = (
        await db.scalars(
            select(Invitation)
            .where(Invitation.organization_id == context.organization.id)
            .order_by(Invitation.created_at.desc())
            .limit(100)
        )
    ).all()
    return [
        {
            "id": row.id,
            "email": row.email,
            "role": row.role,
            "expires_at": row.expires_at,
            "accepted_at": row.accepted_at,
            "revoked_at": row.revoked_at,
        }
        for row in rows
    ]


@router.delete("/current/invitations/{invitation_id}", status_code=204)
async def revoke_invitation(invitation_id: uuid.UUID, db: DbSession, context: Manager, _csrf: Csrf):
    await lock_organization(db, context, "invitations.manage")
    item = await db.scalar(
        select(Invitation)
        .where(
            Invitation.id == invitation_id, Invitation.organization_id == context.organization.id
        )
        .with_for_update()
    )
    if not item:
        raise HTTPException(404, "Invitation not found")
    if context.membership.role != MembershipRole.admin and item.role == MembershipRole.admin:
        raise HTTPException(403, "Only administrators can revoke administrator invitations")
    item.revoked_at = datetime.now(UTC)
    record_audit(
        db,
        context.organization.id,
        "invitation_revoked",
        context.user.id,
        module="identity",
        detail={"invitation_id": str(item.id)},
    )
    await db.commit()


async def lock_organization(db, context, permission):
    organization = await db.scalar(
        select(Organization)
        .where(Organization.id == context.organization.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    member = await db.scalar(
        select(Membership)
        .join(User, User.id == Membership.user_id)
        .where(
            Membership.organization_id == organization.id,
            Membership.user_id == context.user.id,
            Membership.is_active.is_(True),
            User.is_active.is_(True),
        )
        .execution_options(populate_existing=True)
    )
    if not member or not has_permission(member.role, permission):
        raise HTTPException(403, "Insufficient permissions")
    context.membership = member
    return organization


async def guarded_member(db, context, user_id, role=None, active=False):
    organization = await lock_organization(db, context, "members.manage")
    member = await db.scalar(
        select(Membership)
        .where(Membership.organization_id == organization.id, Membership.user_id == user_id)
        .with_for_update()
    )
    if not member:
        raise HTTPException(404, "Member not found")
    if organization.owner_user_id == user_id and (role != MembershipRole.admin or not active):
        raise HTTPException(409, "Transfer ownership before changing or removing the owner")
    if (
        member.role == MembershipRole.admin
        and member.is_active
        and (role != MembershipRole.admin or not active)
    ):
        admins = await db.scalar(
            select(func.count(Membership.id))
            .join(User, User.id == Membership.user_id)
            .where(
                Membership.organization_id == organization.id,
                Membership.role == MembershipRole.admin,
                Membership.is_active.is_(True),
                User.is_active.is_(True),
            )
        )
        if admins <= 1:
            raise HTTPException(409, "The last active administrator cannot be removed or demoted")
    return member


@router.put("/current/members/{user_id}")
async def update_member(
    user_id: uuid.UUID, payload: MemberInput, db: DbSession, context: Admin, _csrf: Csrf
):
    member = await guarded_member(db, context, user_id, payload.role, payload.is_active)
    member.role, member.is_active = payload.role, payload.is_active
    record_audit(
        db,
        context.organization.id,
        "membership_updated",
        context.user.id,
        module="identity",
        detail={"user_id": str(user_id), "role": payload.role.value, "active": payload.is_active},
    )
    await db.commit()
    return {"id": user_id, "role": member.role, "is_active": member.is_active}


@router.delete("/current/members/{user_id}", status_code=204)
async def remove_member(user_id: uuid.UUID, db: DbSession, context: Admin, _csrf: Csrf):
    member = await guarded_member(db, context, user_id)
    await db.delete(member)
    record_audit(
        db,
        context.organization.id,
        "membership_removed",
        context.user.id,
        module="identity",
        detail={"user_id": str(user_id)},
    )
    await db.commit()


@router.post("/current/ownership")
async def transfer_ownership(payload: OwnershipInput, db: DbSession, context: Admin, _csrf: Csrf):
    organization = await lock_organization(db, context, "members.manage")
    if organization.owner_user_id != context.user.id or not verify_password(
        payload.current_password, context.user.password_hash
    ):
        raise HTTPException(
            403, "Ownership transfer requires the current owner and correct password"
        )
    target = await db.scalar(
        select(Membership)
        .join(User, User.id == Membership.user_id)
        .where(
            Membership.organization_id == organization.id,
            Membership.user_id == payload.user_id,
            Membership.is_active.is_(True),
            User.is_active.is_(True),
        )
        .with_for_update()
    )
    if not target:
        raise HTTPException(404, "Active member not found")
    target.role = MembershipRole.admin
    organization.owner_user_id = target.user_id
    record_audit(
        db,
        organization.id,
        "ownership_transferred",
        context.user.id,
        module="identity",
        detail={"new_owner_id": str(target.user_id)},
    )
    await db.commit()
    return {"owner_user_id": organization.owner_user_id}


@router.get("/current/security-events")
async def security_events(db: DbSession, context: Admin):
    from app.models.campaign import CampaignAudit

    rows = (
        await db.scalars(
            select(CampaignAudit)
            .where(
                CampaignAudit.organization_id == context.organization.id,
                CampaignAudit.detail["module"].as_string() == "identity",
            )
            .order_by(CampaignAudit.created_at.desc())
            .limit(100)
        )
    ).all()
    return [
        {
            "id": row.id,
            "action": row.action,
            "user_id": row.user_id,
            "detail": row.detail,
            "created_at": row.created_at,
        }
        for row in rows
    ]
