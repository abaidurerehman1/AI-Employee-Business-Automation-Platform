import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response, status
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import DbSession, get_current_session, require_csrf
from app.core.audit import record_audit
from app.core.config import settings
from app.core.email import send_reset_email, send_verification_email
from app.core.security import DUMMY_HASH, hash_password, new_token, token_digest, verify_password
from app.models.auth import (
    AuthSession,
    EmailToken,
    Membership,
    MembershipRole,
    Organization,
    TokenPurpose,
    User,
)
from app.schemas.auth import (
    ForgotPasswordRequest,
    LoginRequest,
    MessageResponse,
    OrganizationSummary,
    PasswordInput,
    ProfileInput,
    RegisterRequest,
    ResetPasswordRequest,
    SessionResponse,
    TokenRequest,
    UserResponse,
)


async def protect_authentication(request: Request):
    if request.method == "POST" and settings.app_env in {"production", "staging"}:
        from app.core.inbound_rate import check_rate_limit

        await check_rate_limit(
            request,
            "authentication",
            request.url.path.rsplit("/", 1)[-1],
            settings.auth_requests_per_minute,
        )


router = APIRouter(
    prefix="/auth", tags=["authentication"], dependencies=[Depends(protect_authentication)]
)


def normalize_email(email: str) -> str:
    return email.strip().lower()


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "organization"


async def create_email_token(
    db: AsyncSession, user_id, purpose: TokenPurpose, lifetime: timedelta
) -> str:
    await db.scalar(select(User).where(User.id == user_id).with_for_update())
    raw_token = new_token()
    await db.execute(
        delete(EmailToken).where(
            EmailToken.user_id == user_id,
            EmailToken.purpose == purpose,
            EmailToken.used_at.is_(None),
        )
    )
    db.add(
        EmailToken(
            user_id=user_id,
            token_hash=token_digest(raw_token),
            purpose=purpose,
            expires_at=datetime.now(UTC) + lifetime,
        )
    )
    return raw_token


async def session_payload(db: AsyncSession, user: User, session: AuthSession) -> SessionResponse:
    rows = await db.execute(
        select(Organization, Membership.role)
        .join(Membership, Membership.organization_id == Organization.id)
        .where(Membership.user_id == user.id, Membership.is_active.is_(True))
        .order_by(Organization.name)
    )
    organizations = [
        OrganizationSummary(
            id=org.id, name=org.name, slug=org.slug, role=role, owner_user_id=org.owner_user_id
        )
        for org, role in rows.all()
    ]
    return SessionResponse(
        user=UserResponse.model_validate(user),
        organizations=organizations,
        csrf_token=session.csrf_token,
    )


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        settings.session_cookie_name,
        token,
        max_age=settings.session_days * 86400,
        httponly=True,
        secure=settings.secure_cookies,
        samesite="lax",
        path="/",
    )


@router.post("/register", response_model=MessageResponse, status_code=status.HTTP_201_CREATED)
async def register(
    payload: RegisterRequest,
    db: DbSession,
    background_tasks: BackgroundTasks,
) -> MessageResponse:
    email = normalize_email(str(payload.email))
    existing = await db.scalar(select(User).where(User.email == email))
    if existing:
        hash_password(payload.password)
        return MessageResponse(
            message="Registration successful. Check your email to verify your account."
        )

    suffix = new_token()[:8].lower()
    organization = Organization(
        name=payload.organization_name.strip(),
        slug=f"{slugify(payload.organization_name)}-{suffix}",
    )
    user = User(
        email=email,
        full_name=payload.full_name.strip(),
        password_hash=hash_password(payload.password),
    )
    try:
        db.add_all([organization, user])
        await db.flush()
        organization.owner_user_id = user.id
        db.add(
            Membership(user_id=user.id, organization_id=organization.id, role=MembershipRole.admin)
        )
        record_audit(db, organization.id, "registered", user.id, module="identity")
        token = await create_email_token(
            db, user.id, TokenPurpose.verify_email, timedelta(hours=24)
        )
        await db.commit()
    except IntegrityError:
        await db.rollback()
        return MessageResponse(
            message="Registration successful. Check your email to verify your account."
        )
    background_tasks.add_task(send_verification_email, email, token)
    return MessageResponse(
        message="Registration successful. Check your email to verify your account."
    )


@router.post("/verify-email", response_model=MessageResponse)
async def verify_email(payload: TokenRequest, db: DbSession) -> MessageResponse:
    token, user = await consume_email_token(db, payload.token, TokenPurpose.verify_email)
    user.is_email_verified = True
    token.used_at = datetime.now(UTC)
    await audit_identity(db, user, "email_verified")
    await db.commit()
    return MessageResponse(message="Email verified. You can now sign in.")


@router.post("/resend-verification", response_model=MessageResponse)
async def resend_verification(
    payload: ForgotPasswordRequest,
    db: DbSession,
    background_tasks: BackgroundTasks,
) -> MessageResponse:
    user = await db.scalar(
        select(User).where(User.email == normalize_email(str(payload.email))).with_for_update()
    )
    if user and user.is_active and not user.is_email_verified:
        token = await create_email_token(
            db, user.id, TokenPurpose.verify_email, timedelta(hours=24)
        )
        await db.commit()
        background_tasks.add_task(send_verification_email, user.email, token)
    return MessageResponse(
        message="If the account is awaiting verification, a new link has been sent."
    )


@router.post("/login", response_model=SessionResponse)
async def login(
    payload: LoginRequest, response: Response, request: Request, db: DbSession
) -> SessionResponse:
    user = await db.scalar(
        select(User).where(User.email == normalize_email(str(payload.email))).with_for_update()
    )
    if not user:
        verify_password(payload.password, DUMMY_HASH)
    if not user or not verify_password(payload.password, user.password_hash) or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")
    if not user.is_email_verified:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Verify your email before signing in")
    raw_token = new_token()
    previous = request.cookies.get(settings.session_cookie_name)
    if previous:
        await db.execute(
            delete(AuthSession).where(
                AuthSession.user_id == user.id, AuthSession.token_hash == token_digest(previous)
            )
        )
    session = AuthSession(
        user_id=user.id,
        token_hash=token_digest(raw_token),
        csrf_token=new_token(),
        expires_at=datetime.now(UTC) + timedelta(days=settings.session_days),
    )
    db.add(session)
    await audit_identity(db, user, "signed_in")
    await db.commit()
    set_session_cookie(response, raw_token)
    return await session_payload(db, user, session)


@router.get("/session", response_model=SessionResponse)
async def read_session(
    db: DbSession,
    current: Annotated[tuple[User, AuthSession], Depends(get_current_session)],
) -> SessionResponse:
    return await session_payload(db, current[0], current[1])


@router.post("/logout", response_model=MessageResponse)
async def logout(
    response: Response,
    db: DbSession,
    current: Annotated[tuple[User, AuthSession], Depends(get_current_session)],
    _csrf_user: Annotated[User, Depends(require_csrf)],
) -> MessageResponse:
    await db.delete(current[1])
    await audit_identity(db, current[0], "signed_out")
    await db.commit()
    response.delete_cookie(settings.session_cookie_name, path="/")
    return MessageResponse(message="Signed out")


@router.post("/forgot-password", response_model=MessageResponse)
async def forgot_password(
    payload: ForgotPasswordRequest,
    db: DbSession,
    background_tasks: BackgroundTasks,
) -> MessageResponse:
    user = await db.scalar(select(User).where(User.email == normalize_email(str(payload.email))))
    if user and user.is_active:
        token = await create_email_token(
            db, user.id, TokenPurpose.reset_password, timedelta(hours=1)
        )
        await audit_identity(db, user, "password_reset_requested")
        await db.commit()
        background_tasks.add_task(send_reset_email, user.email, token)
    return MessageResponse(message="If that account exists, a reset link has been sent.")


@router.post("/reset-password", response_model=MessageResponse)
async def reset_password(payload: ResetPasswordRequest, db: DbSession) -> MessageResponse:
    token, user = await consume_email_token(db, payload.token, TokenPurpose.reset_password)
    user.password_hash = hash_password(payload.password)
    token.used_at = datetime.now(UTC)
    await db.execute(delete(AuthSession).where(AuthSession.user_id == user.id))
    await audit_identity(db, user, "password_reset_completed")
    await db.commit()
    return MessageResponse(message="Password updated. Sign in with your new password.")


async def consume_email_token(db: AsyncSession, raw: str, purpose: TokenPurpose):
    # All issuance and consumption paths lock the user before the token. Recheck
    # after acquiring the lock so simultaneous requests cannot replay a link.
    query = select(EmailToken).where(
        EmailToken.token_hash == token_digest(raw),
        EmailToken.purpose == purpose,
        EmailToken.used_at.is_(None),
        EmailToken.expires_at > datetime.now(UTC),
    )
    candidate = await db.scalar(query)
    if not candidate:
        raise HTTPException(400, "Invalid or expired link")
    user = await db.scalar(
        select(User)
        .where(User.id == candidate.user_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    token = await db.scalar(query.with_for_update().execution_options(populate_existing=True))
    if not user or not user.is_active or not token:
        raise HTTPException(400, "Invalid or expired link")
    return token, user


async def audit_identity(db, user, action, **detail):
    organizations = (
        await db.scalars(select(Membership.organization_id).where(Membership.user_id == user.id))
    ).all()
    for organization_id in organizations:
        record_audit(db, organization_id, action, user.id, module="identity", detail=detail)


Current = Annotated[tuple[User, AuthSession], Depends(get_current_session)]
Csrf = Annotated[User, Depends(require_csrf)]


async def rotate_session(db, current, request, response):
    raw = request.cookies.get(settings.session_cookie_name, "")
    session = await db.scalar(
        select(AuthSession)
        .where(AuthSession.id == current[1].id, AuthSession.token_hash == token_digest(raw))
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if not session:
        raise HTTPException(401, "Invalid or expired session")
    token = new_token()
    session.token_hash, session.csrf_token = token_digest(token), new_token()
    # Keep the original absolute expiry; rotating never extends account access indefinitely.
    await audit_identity(db, current[0], "session_rotated", session_id=str(session.id))
    await db.commit()
    remaining = max(
        0,
        int(
            (
                session.expires_at.replace(tzinfo=UTC)
                if session.expires_at.tzinfo is None
                else session.expires_at
            ).timestamp()
            - datetime.now(UTC).timestamp()
        ),
    )
    response.set_cookie(
        settings.session_cookie_name,
        token,
        max_age=remaining,
        httponly=True,
        secure=settings.secure_cookies,
        samesite="lax",
        path="/",
    )
    return await session_payload(db, current[0], session)


@router.post("/session/rotate", response_model=SessionResponse)
async def refresh_session(
    request: Request, response: Response, db: DbSession, current: Current, _csrf: Csrf
):
    return await rotate_session(db, current, request, response)


@router.put("/account", response_model=SessionResponse)
async def update_account(payload: ProfileInput, db: DbSession, current: Current, _csrf: Csrf):
    current[0].full_name = payload.full_name
    await audit_identity(db, current[0], "profile_updated")
    await db.commit()
    return await session_payload(db, current[0], current[1])


@router.post("/password", response_model=SessionResponse)
async def change_password(
    payload: PasswordInput,
    request: Request,
    response: Response,
    db: DbSession,
    current: Current,
    _csrf: Csrf,
):
    user = await db.scalar(
        select(User)
        .where(User.id == current[0].id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(400, "Unable to update password. Check your current password.")
    user.password_hash = hash_password(payload.password)
    await db.execute(
        delete(AuthSession).where(AuthSession.user_id == user.id, AuthSession.id != current[1].id)
    )
    await db.execute(
        delete(EmailToken).where(
            EmailToken.user_id == user.id, EmailToken.purpose == TokenPurpose.reset_password
        )
    )
    await audit_identity(db, user, "password_changed")
    return await rotate_session(db, current, request, response)


@router.get("/sessions")
async def list_sessions(db: DbSession, current: Current):
    sessions = (
        await db.scalars(
            select(AuthSession)
            .where(AuthSession.user_id == current[0].id, AuthSession.expires_at > datetime.now(UTC))
            .order_by(AuthSession.created_at.desc())
        )
    ).all()
    return [
        {
            "id": item.id,
            "created_at": item.created_at,
            "expires_at": item.expires_at,
            "current": item.id == current[1].id,
        }
        for item in sessions
    ]


@router.delete("/sessions/{session_id}", status_code=204)
async def revoke_session(
    session_id: uuid.UUID, response: Response, db: DbSession, current: Current, _csrf: Csrf
):
    item = await db.scalar(
        select(AuthSession)
        .where(AuthSession.id == session_id, AuthSession.user_id == current[0].id)
        .with_for_update()
    )
    if not item:
        raise HTTPException(404, "Session not found")
    await db.delete(item)
    await audit_identity(db, current[0], "session_revoked", session_id=str(session_id))
    await db.commit()
    if session_id == current[1].id:
        response.delete_cookie(settings.session_cookie_name, path="/")
