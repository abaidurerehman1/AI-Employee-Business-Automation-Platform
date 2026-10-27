import re
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response, status
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import DbSession, get_current_session, require_csrf
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
    RegisterRequest,
    ResetPasswordRequest,
    SessionResponse,
    TokenRequest,
    UserResponse,
)

router = APIRouter(prefix="/auth", tags=["authentication"])


def normalize_email(email: str) -> str:
    return email.strip().lower()


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "organization"


async def create_email_token(
    db: AsyncSession, user_id, purpose: TokenPurpose, lifetime: timedelta
) -> str:
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
        .where(Membership.user_id == user.id)
        .order_by(Organization.name)
    )
    organizations = [
        OrganizationSummary(id=org.id, name=org.name, slug=org.slug, role=role)
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
        raise HTTPException(status.HTTP_409_CONFLICT, "An account with this email already exists")

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
    db.add_all([organization, user])
    await db.flush()
    db.add(Membership(user_id=user.id, organization_id=organization.id, role=MembershipRole.admin))
    token = await create_email_token(db, user.id, TokenPurpose.verify_email, timedelta(hours=24))
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Account could not be created") from exc
    background_tasks.add_task(send_verification_email, email, token)
    return MessageResponse(
        message="Registration successful. Check your email to verify your account."
    )


@router.post("/verify-email", response_model=MessageResponse)
async def verify_email(payload: TokenRequest, db: DbSession) -> MessageResponse:
    token = await db.scalar(
        select(EmailToken).where(
            EmailToken.token_hash == token_digest(payload.token),
            EmailToken.purpose == TokenPurpose.verify_email,
            EmailToken.used_at.is_(None),
            EmailToken.expires_at > datetime.now(UTC),
        )
    )
    if not token:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid or expired verification link")
    user = await db.get(User, token.user_id)
    if not user:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid verification link")
    user.is_email_verified = True
    token.used_at = datetime.now(UTC)
    await db.commit()
    return MessageResponse(message="Email verified. You can now sign in.")


@router.post("/resend-verification", response_model=MessageResponse)
async def resend_verification(
    payload: ForgotPasswordRequest,
    db: DbSession,
    background_tasks: BackgroundTasks,
) -> MessageResponse:
    user = await db.scalar(select(User).where(User.email == normalize_email(str(payload.email))))
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
async def login(payload: LoginRequest, response: Response, db: DbSession) -> SessionResponse:
    user = await db.scalar(select(User).where(User.email == normalize_email(str(payload.email))))
    if not user:
        verify_password(payload.password, DUMMY_HASH)
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")
    if not user.is_email_verified:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Verify your email before signing in")
    raw_token = new_token()
    session = AuthSession(
        user_id=user.id,
        token_hash=token_digest(raw_token),
        csrf_token=new_token(),
        expires_at=datetime.now(UTC) + timedelta(days=settings.session_days),
    )
    db.add(session)
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
        await db.commit()
        background_tasks.add_task(send_reset_email, user.email, token)
    return MessageResponse(message="If that account exists, a reset link has been sent.")


@router.post("/reset-password", response_model=MessageResponse)
async def reset_password(payload: ResetPasswordRequest, db: DbSession) -> MessageResponse:
    token = await db.scalar(
        select(EmailToken).where(
            EmailToken.token_hash == token_digest(payload.token),
            EmailToken.purpose == TokenPurpose.reset_password,
            EmailToken.used_at.is_(None),
            EmailToken.expires_at > datetime.now(UTC),
        )
    )
    if not token:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid or expired reset link")
    user = await db.get(User, token.user_id)
    if not user:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid reset link")
    user.password_hash = hash_password(payload.password)
    token.used_at = datetime.now(UTC)
    await db.execute(delete(AuthSession).where(AuthSession.user_id == user.id))
    await db.commit()
    return MessageResponse(message="Password updated. Sign in with your new password.")
