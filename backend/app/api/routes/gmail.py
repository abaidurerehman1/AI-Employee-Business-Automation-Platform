import base64
import hashlib
import json
import secrets
import uuid
from typing import Annotated
from urllib.parse import urlencode

import httpx
from cryptography.fernet import Fernet
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select

from app.api.dependencies import DbSession, TenantContext, get_current_session, require_csrf, require_permission
from app.core.config import settings
from app.db.session import redis_client
from app.models.auth import AuthSession, Membership, MembershipRole, User
from app.models.messaging import GmailConnection

router = APIRouter(prefix="/messaging/gmail", tags=["gmail"])
Manager = Annotated[TenantContext, Depends(require_permission("integrations.manage"))]
Csrf = Annotated[User, Depends(require_csrf)]
Current = Annotated[tuple[User, AuthSession], Depends(get_current_session)]


def cipher() -> Fernet:
    try:
        return Fernet(settings.oauth_encryption_key.encode())
    except (ValueError, TypeError) as exc:
        raise HTTPException(503, "Gmail encryption key is not configured") from exc


@router.post("/connect")
async def connect_gmail(context: Manager, _user: Csrf, current: Current):
    if not settings.google_client_id or not settings.google_client_secret:
        raise HTTPException(503, "Google client credentials are not configured")
    cipher()
    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    await redis_client.setex("gmail-oauth:" + hashlib.sha256(state.encode()).hexdigest(), 600,
        json.dumps({"user": str(context.user.id), "session": str(current[1].id), "organization": str(context.organization.id), "verifier": verifier}))
    params = {"client_id": settings.google_client_id, "redirect_uri": settings.google_redirect_uri,
        "response_type": "code", "scope": "openid email https://www.googleapis.com/auth/gmail.send",
        "access_type": "offline", "prompt": "consent", "state": state,
        "code_challenge": challenge, "code_challenge_method": "S256"}
    return {"authorization_url": "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params)}


@router.get("/callback")
async def gmail_callback(request: Request, db: DbSession, current: Current, code: str = "", state: str = "", error: str = ""):
    # Exclude OAuth query parameters from access logs.
    request.scope["query_string"] = b""
    if not state or len(state) > 128:
        raise HTTPException(400, "Invalid authorization state")
    raw = await redis_client.getdel("gmail-oauth:" + hashlib.sha256(state.encode()).hexdigest())
    if not raw:
        raise HTTPException(400, "Authorization state expired or already used")
    data = json.loads(raw)
    if data["user"] != str(current[0].id) or data["session"] != str(current[1].id):
        raise HTTPException(403, "Authorization belongs to another user")
    member = await db.scalar(select(Membership).where(Membership.user_id == current[0].id,
        Membership.organization_id == uuid.UUID(data["organization"]), Membership.is_active.is_(True), Membership.role.in_([MembershipRole.admin, MembershipRole.manager])))
    if not member:
        raise HTTPException(403, "Workspace access is no longer permitted")
    if error or not code:
        raise HTTPException(400, "Google authorization was not completed")
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            token_response = await client.post("https://oauth2.googleapis.com/token", data={
                "code": code, "client_id": settings.google_client_id, "client_secret": settings.google_client_secret,
                "redirect_uri": settings.google_redirect_uri, "grant_type": "authorization_code", "code_verifier": data["verifier"]})
            token_response.raise_for_status()
            tokens = token_response.json()
            if not tokens.get("refresh_token"):
                raise ValueError("Missing refresh token")
            profile = await client.get("https://openidconnect.googleapis.com/v1/userinfo", headers={"Authorization": f"Bearer {tokens['access_token']}"})
            profile.raise_for_status()
            identity = profile.json()
            if not identity.get("email") or not identity.get("email_verified"):
                raise ValueError("Google account email is not verified")
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        raise HTTPException(502, "Unable to connect Gmail; check the Google OAuth settings and try again") from exc
    connection = await db.scalar(select(GmailConnection).where(GmailConnection.organization_id == member.organization_id).with_for_update())
    encrypted = cipher().encrypt(tokens["refresh_token"].encode()).decode()
    if not connection:
        connection = GmailConnection(organization_id=member.organization_id, connected_by=current[0].id, email=identity["email"], encrypted_refresh_token=encrypted)
        db.add(connection)
    else:
        connection.connected_by, connection.email, connection.encrypted_refresh_token = current[0].id, identity["email"], encrypted
    await db.commit()
    return RedirectResponse(settings.frontend_url.rstrip("/") + "/app?gmail=connected", status_code=303)


@router.delete("/connection", status_code=204)
async def disconnect_gmail(db: DbSession, context: Manager, _user: Csrf):
    connection = await db.scalar(select(GmailConnection).where(GmailConnection.organization_id == context.organization.id))
    if connection:
        await db.delete(connection)
        await db.commit()
