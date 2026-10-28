"""Synthetic local-browser fixture. Never sends email or invokes an AI/provider."""

import asyncio
import json
import secrets
import sys
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.security import hash_password, token_digest
from app.models.agent import Agent, AgentVersion
from app.models.auth import Invitation, Membership, MembershipRole, Organization, User
from app.models.crm import Contact, Deal, Lead
from app.models.knowledge import KnowledgeDocument
from app.models.messaging import OutboundMessage


async def main():
    engine = create_async_engine(settings.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions() as db:
            if sys.argv[1] == "seed":
                org_id, user_id, agent_id, version_id = [uuid.uuid4() for _ in range(4)]
                password = secrets.token_urlsafe(24)
                email = f"dashboard-live-{user_id}@example.com"
                db.add(
                    User(
                        id=user_id,
                        email=email,
                        full_name="Dashboard Test Owner",
                        password_hash=hash_password(password),
                        is_email_verified=True,
                    )
                )
                await db.flush()
                db.add(
                    Organization(
                        id=org_id,
                        name="Controlled Dashboard Test",
                        slug=f"dashboard-live-{org_id}",
                        owner_user_id=user_id,
                    )
                )
                await db.flush()
                db.add_all(
                    [
                        Membership(
                            user_id=user_id, organization_id=org_id, role=MembershipRole.admin
                        ),
                        Contact(
                            organization_id=org_id,
                            name="Controlled Dashboard Contact",
                            email="controlled-contact@example.com",
                        ),
                        Lead(
                            organization_id=org_id,
                            title="Controlled Dashboard Lead",
                            stage="qualified",
                        ),
                        Deal(
                            organization_id=org_id,
                            title="Controlled Dashboard Deal",
                            currency="USD",
                            amount_minor=125000,
                            stage="open",
                        ),
                        KnowledgeDocument(
                            organization_id=org_id,
                            uploaded_by=user_id,
                            filename="Controlled test FAQ.txt",
                            media_type="txt",
                            file_bytes=b"Test company knowledge",
                            status="ready",
                        ),
                        OutboundMessage(
                            organization_id=org_id,
                            created_by=user_id,
                            channel="email",
                            recipient="not-sent@example.com",
                            subject="Controlled failure",
                            body="Synthetic test; no provider call",
                            status="failed",
                            idempotency_key=f"dashboard-{org_id}",
                        ),
                        Invitation(
                            organization_id=org_id,
                            invited_by_user_id=user_id,
                            email="controlled-invite@example.com",
                            role=MembershipRole.employee,
                            token_hash=token_digest(secrets.token_urlsafe(32)),
                            expires_at=datetime.now(UTC) + timedelta(hours=1),
                        ),
                        Agent(
                            id=agent_id,
                            organization_id=org_id,
                            name="Controlled Dashboard Employee",
                            status="published",
                            published_version_id=version_id,
                        ),
                    ]
                )
                await db.flush()
                db.add(
                    AgentVersion(
                        id=version_id,
                        agent_id=agent_id,
                        version=1,
                        role="Support",
                        instructions="Answer from approved knowledge",
                        tone="Professional",
                        language="English",
                        model="test",
                        tools=[],
                        approval_rules={},
                    )
                )
                await db.commit()
                print(
                    json.dumps(
                        {
                            "organization_id": str(org_id),
                            "user_id": str(user_id),
                            "email": email,
                            "password": password,
                        }
                    )
                )
            elif sys.argv[1] == "cleanup":
                org_id, user_id = uuid.UUID(sys.argv[2]), uuid.UUID(sys.argv[3])
                organization = await db.get(Organization, org_id)
                if (
                    not organization
                    or organization.slug != f"dashboard-live-{org_id}"
                    or organization.owner_user_id != user_id
                ):
                    raise ValueError(
                        "Refusing to remove an organization outside this synthetic fixture"
                    )
                await db.execute(delete(Organization).where(Organization.id == org_id))
                await db.execute(
                    delete(User).where(
                        User.id == user_id, User.email == f"dashboard-live-{user_id}@example.com"
                    )
                )
                await db.commit()
            else:
                raise ValueError("Unknown fixture action")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
