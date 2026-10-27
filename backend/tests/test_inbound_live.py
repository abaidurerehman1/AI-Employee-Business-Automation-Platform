import os
import shutil
import subprocess
from pathlib import Path
from uuid import uuid4
import httpx
import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from app.core.config import settings
from app.db.session import get_db
from app.main import app
from app.models.agent import Agent, AgentVersion
from app.models.auth import Organization, User
from app.models.inbound import InboundSite
from app.models.crm import Contact, Lead
from app.models.knowledge import KnowledgeDocument
from app.worker import process_document


@pytest.mark.asyncio
@pytest.mark.skipif(os.getenv("RUN_LIVE_INBOUND") != "1", reason="Requires PostgreSQL, Redis and OpenAI")
async def test_live_public_chat_uses_tenant_knowledge_and_rate_limits():
    engine = create_async_engine(settings.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    user_id, org_id, agent_id, version_id, site_id, document_id = (uuid4() for _ in range(6))
    async def test_db():
        async with sessions() as session:
            yield session
    app.dependency_overrides[get_db] = test_db
    try:
        async with sessions() as db:
            db.add_all([User(id=user_id, email=f"inbound-live-{user_id}@example.com", full_name="Test", password_hash="unused"), Organization(id=org_id, name="Test", slug=f"inbound-live-{org_id}")])
            await db.flush()
            db.add(Agent(id=agent_id, organization_id=org_id, name="Support", status="published", published_version_id=version_id))
            await db.flush()
            db.add(AgentVersion(id=version_id, agent_id=agent_id, version=1, role="Support", instructions="Answer questions about the company.", tone="Friendly", language="English", model=settings.openai_default_model, tools=[], approval_rules={}))
            db.add(InboundSite(id=site_id, organization_id=org_id, agent_id=agent_id, name="Support", enabled=True, webhook_secret="temporary"))
            db.add(KnowledgeDocument(id=document_id, organization_id=org_id, uploaded_by=user_id, filename="price.txt", media_type="txt", file_bytes=b"The Aurora plan costs 499 AED per month.", status="queued", chunk_count=0))
            await db.commit()
        await process_document(document_id)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test", timeout=120) as client:
            root = f"/api/v1/public/inbound/{site_id}"
            session = await client.post(root + "/sessions")
            assert session.status_code == 201, session.text
            headers = {"Authorization": f"Bearer {session.json()['token']}"}
            answer = await client.post(root + "/messages", headers=headers, json={"message": "What is the Aurora plan price?"})
            assert answer.status_code == 200, answer.text
            assert "499" in answer.json()["answer"]
            assert answer.json()["citations"][0]["filename"] == "price.txt"
            assert len((await client.get(root + "/messages", headers=headers)).json()["messages"]) == 2
            for _ in range(16):
                limited = await client.post(root + "/sessions")
            assert limited.status_code == 429
        if os.getenv("RUN_LIVE_INBOUND_BROWSER") == "1":
            frontend = Path(__file__).resolve().parents[2] / "frontend"
            environment = dict(os.environ, INBOUND_LIVE_SITE=str(site_id))
            result = subprocess.run([shutil.which("node"), "./node_modules/@playwright/test/cli.js", "test", "inbound-live.spec.ts"], cwd=frontend, env=environment, capture_output=True, text=True, timeout=90)
            assert result.returncode == 0, result.stdout + result.stderr
            async with sessions() as db:
                assert await db.scalar(select(func.count(Lead.id)).where(Lead.organization_id == org_id)) == 1
    finally:
        app.dependency_overrides.pop(get_db, None)
        async with sessions() as db:
            await db.execute(delete(InboundSite).where(InboundSite.id == site_id))
            await db.execute(delete(KnowledgeDocument).where(KnowledgeDocument.id == document_id))
            await db.execute(delete(Lead).where(Lead.organization_id == org_id))
            await db.execute(delete(Contact).where(Contact.organization_id == org_id))
            await db.execute(delete(AgentVersion).where(AgentVersion.id == version_id))
            await db.execute(delete(Agent).where(Agent.id == agent_id))
            await db.execute(delete(Organization).where(Organization.id == org_id))
            await db.execute(delete(User).where(User.id == user_id))
            await db.commit()
        await engine.dispose()
