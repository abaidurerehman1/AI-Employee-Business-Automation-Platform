import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Cookie, Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import token_digest
from app.db.session import get_db
from app.models.auth import AuthSession, Membership, MembershipRole, Organization, User

DbSession = Annotated[AsyncSession, Depends(get_db)]


async def get_current_session(
    db: DbSession,
    session_token: Annotated[str | None, Cookie(alias=settings.session_cookie_name)] = None,
) -> tuple[User, AuthSession]:
    if not session_token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Authentication required")
    row = await db.execute(
        select(User, AuthSession)
        .join(AuthSession, AuthSession.user_id == User.id)
        .where(
            AuthSession.token_hash == token_digest(session_token),
            AuthSession.expires_at > datetime.now(UTC),
            User.is_active.is_(True),
        )
    )
    result = row.first()
    if not result:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired session")
    return result


async def get_current_user(
    current: Annotated[tuple[User, AuthSession], Depends(get_current_session)],
) -> User:
    return current[0]


async def require_csrf(
    request: Request,
    current: Annotated[tuple[User, AuthSession], Depends(get_current_session)],
    csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> User:
    if request.method not in {"GET", "HEAD", "OPTIONS"} and not (
        csrf_token and secrets.compare_digest(csrf_token, current[1].csrf_token)
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Invalid CSRF token")
    return current[0]


@dataclass
class TenantContext:
    user: User
    organization: Organization
    membership: Membership


async def get_tenant_context(
    db: DbSession,
    user: Annotated[User, Depends(get_current_user)],
    organization_id: Annotated[str | None, Header(alias="X-Organization-ID")] = None,
) -> TenantContext:
    if not organization_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "X-Organization-ID header is required")
    try:
        parsed_id = uuid.UUID(organization_id)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid organization ID") from exc
    row = await db.execute(
        select(Organization, Membership)
        .join(Membership, Membership.organization_id == Organization.id)
        .where(Organization.id == parsed_id, Membership.user_id == user.id)
    )
    result = row.first()
    if not result:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organization not found")
    return TenantContext(user=user, organization=result[0], membership=result[1])


def require_roles(*roles: MembershipRole):
    async def role_dependency(
        context: Annotated[TenantContext, Depends(get_tenant_context)],
    ) -> TenantContext:
        if context.membership.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient permissions")
        return context

    return role_dependency
