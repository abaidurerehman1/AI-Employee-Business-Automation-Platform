"""PostgreSQL concurrency tests with synthetic users; no emails or provider calls."""

import asyncio
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.security import hash_password, new_token, token_digest
from app.db.session import get_db
from app.main import app
from app.models.auth import EmailToken, Membership, MembershipRole, Organization, TokenPurpose, User


@pytest.mark.asyncio
@pytest.mark.skipif(
    os.getenv("RUN_LIVE_IDENTITY") != "1", reason="Requires migrated local PostgreSQL"
)
async def test_concurrent_reset_rotation_and_last_administrator():
    engine = create_async_engine(settings.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    organization_id = uuid4()
    user_ids = [uuid4(), uuid4()]
    emails = [f"identity-{item}@example.com" for item in user_ids]
    password = "SyntheticPassword123!"
    reset_token = new_token()

    async def test_db():
        async with sessions() as db:
            yield db

    app.dependency_overrides[get_db] = test_db
    try:
        async with sessions() as db:
            db.add(
                Organization(
                    id=organization_id, name="Identity test", slug=f"identity-{organization_id}"
                )
            )
            for user_id, email in zip(user_ids, emails, strict=True):
                db.add(
                    User(
                        id=user_id,
                        email=email,
                        full_name="Synthetic tester",
                        password_hash=hash_password(password),
                        is_email_verified=True,
                    )
                )
            await db.flush()
            for user_id in user_ids:
                db.add(
                    Membership(
                        user_id=user_id, organization_id=organization_id, role=MembershipRole.admin
                    )
                )
            db.add(
                EmailToken(
                    user_id=user_ids[0],
                    token_hash=token_digest(reset_token),
                    purpose=TokenPurpose.reset_password,
                    expires_at=datetime.now(UTC) + timedelta(minutes=5),
                )
            )
            await db.commit()
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            results = await asyncio.gather(
                *[
                    client.post(
                        "/api/v1/auth/reset-password",
                        json={"token": reset_token, "password": "ReplacementPassword123!"},
                    )
                    for _ in range(2)
                ]
            )
            assert sorted(item.status_code for item in results) == [200, 400]
            login = await client.post(
                "/api/v1/auth/login",
                json={"email": emails[0], "password": "ReplacementPassword123!"},
            )
            assert login.status_code == 200
            cookie = client.cookies.get(settings.session_cookie_name)
            auth = {
                "X-CSRF-Token": login.json()["csrf_token"],
                "Cookie": f"{settings.session_cookie_name}={cookie}",
            }
            results = await asyncio.gather(
                *[client.post("/api/v1/auth/session/rotate", headers=auth) for _ in range(2)]
            )
            assert sorted(item.status_code for item in results) == [200, 401]
        async with (
            httpx.AsyncClient(transport=transport, base_url="http://test") as first,
            httpx.AsyncClient(transport=transport, base_url="http://test") as second,
        ):
            one = await first.post(
                "/api/v1/auth/login",
                json={"email": emails[0], "password": "ReplacementPassword123!"},
            )
            two = await second.post(
                "/api/v1/auth/login", json={"email": emails[1], "password": password}
            )
            results = await asyncio.gather(
                *[
                    browser.put(
                        f"/api/v1/organizations/current/members/{user_id}",
                        headers={
                            "X-CSRF-Token": session.json()["csrf_token"],
                            "X-Organization-ID": str(organization_id),
                        },
                        json={"role": "employee", "is_active": True},
                    )
                    for browser, session, user_id in [
                        (first, one, user_ids[0]),
                        (second, two, user_ids[1]),
                    ]
                ]
            )
            assert sorted(item.status_code for item in results) == [200, 409]
    finally:
        app.dependency_overrides.pop(get_db, None)
        async with sessions() as db:
            await db.execute(delete(Organization).where(Organization.id == organization_id))
            await db.execute(delete(User).where(User.id.in_(user_ids)))
            await db.commit()
        await engine.dispose()
