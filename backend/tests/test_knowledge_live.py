import os
from uuid import uuid4

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.embeddings import embed_texts
from app.core.retrieval import hybrid_search
from app.core.rag_graph import run_rag_agent
from app.models.auth import Organization, User
from app.models.knowledge import KnowledgeChunk, KnowledgeDocument
from app.worker import process_document


@pytest.mark.asyncio
@pytest.mark.skipif(
    os.getenv("RUN_LIVE_RAG") != "1", reason="Live PostgreSQL/OpenAI test is opt-in"
)
async def test_real_hybrid_retrieval_tenant_isolation_and_deletion():
    engine = create_async_engine(settings.database_url)
    async with engine.connect() as connection:
        transaction = await connection.begin()
        async with AsyncSession(bind=connection, expire_on_commit=False) as db:
            user = User(
                id=uuid4(),
                email=f"test-{uuid4()}@example.com",
                full_name="Test",
                password_hash="not-a-password",
            )
            first = Organization(id=uuid4(), name="Test first", slug=f"first-{uuid4()}")
            second = Organization(id=uuid4(), name="Test second", slug=f"second-{uuid4()}")
            db.add_all([user, first, second])
            await db.flush()
            doc1 = KnowledgeDocument(
                id=uuid4(),
                organization_id=first.id,
                uploaded_by=user.id,
                filename="pricing.txt",
                media_type="txt",
                file_bytes=b"synthetic",
                status="ready",
                chunk_count=1,
            )
            doc2 = KnowledgeDocument(
                id=uuid4(),
                organization_id=second.id,
                uploaded_by=user.id,
                filename="other.txt",
                media_type="txt",
                file_bytes=b"synthetic",
                status="ready",
                chunk_count=1,
            )
            db.add_all([doc1, doc2])
            await db.flush()
            texts = [
                "The Aurora plan costs 499 AED per month and includes website hosting.",
                "The Aurora plan costs 9999 AED in another company's private document.",
            ]
            vectors = await embed_texts(texts)
            db.add_all(
                [
                    KnowledgeChunk(
                        document_id=doc1.id,
                        organization_id=first.id,
                        chunk_index=0,
                        content=texts[0],
                        embedding=vectors[0],
                    ),
                    KnowledgeChunk(
                        document_id=doc2.id,
                        organization_id=second.id,
                        chunk_index=0,
                        content=texts[1],
                        embedding=vectors[1],
                    ),
                ]
            )
            await db.flush()
            matches = await hybrid_search(db, first.id, "What is the Aurora plan price?")
            assert matches and matches[0].document_id == doc1.id
            assert "499 AED" in matches[0].content
            assert all(result.document_id != doc2.id for result in matches)
            await db.delete(doc1)
            await db.flush()
            assert await hybrid_search(db, first.id, "Aurora plan price") == []
        await transaction.rollback()
    await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.skipif(
    os.getenv("RUN_LIVE_RAG") != "1", reason="Live PostgreSQL/OpenAI test is opt-in"
)
async def test_real_document_processing_retrieval_and_deletion():
    engine = create_async_engine(settings.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    user_id = uuid4()
    organization_id = uuid4()
    document_id = uuid4()
    try:
        async with sessions() as db:
            user = User(
                id=user_id,
                email=f"worker-{uuid4()}@example.com",
                full_name="Worker Test",
                password_hash="not-a-password",
            )
            organization = Organization(
                id=organization_id,
                name="Worker test",
                slug=f"worker-{uuid4()}",
            )
            document = KnowledgeDocument(
                id=document_id,
                organization_id=organization_id,
                uploaded_by=user_id,
                filename="aurora-pricing.txt",
                media_type="txt",
                file_bytes=b"The Aurora plan costs 499 AED per month.",
                status="queued",
                chunk_count=0,
            )
            db.add_all([user, organization, document])
            await db.commit()

        await process_document(document_id)

        async with sessions() as db:
            document = await db.get(KnowledgeDocument, document_id)
            assert document is not None
            assert document.status == "ready"
            assert document.chunk_count > 0
            matches = await hybrid_search(db, organization_id, "What is the Aurora plan price?")
            assert matches
            assert matches[0].document_id == document_id
            assert "499 AED" in matches[0].content
            async def unused_tool(name, arguments, call_id):
                raise AssertionError("No tool should be requested")

            answer, sources = await run_rag_agent(
                db=db, organization_id=organization_id,
                query="What is the Aurora plan price?",
                model=settings.openai_default_model,
                prompt="Answer the user's question accurately.",
                inputs=[{"role": "user", "content": "What is the Aurora plan price?"}],
                tool_names=[], tool_handler=unused_tool,
            )
            assert "499" in answer and "[1]" in answer
            assert sources and sources[0].document_id == document_id
            await db.delete(document)
            await db.commit()

        async with sessions() as db:
            assert await hybrid_search(db, organization_id, "Aurora plan price") == []
    finally:
        async with sessions() as db:
            await db.execute(delete(KnowledgeDocument).where(KnowledgeDocument.id == document_id))
            await db.execute(delete(Organization).where(Organization.id == organization_id))
            await db.execute(delete(User).where(User.id == user_id))
            await db.commit()
        await engine.dispose()
