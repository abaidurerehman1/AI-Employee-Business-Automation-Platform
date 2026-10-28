import asyncio
import logging
import uuid
from datetime import UTC, datetime, timedelta

from celery import Celery
from celery.signals import after_setup_logger
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.document_processing import extract_text, split_text
from app.core.embeddings import embed_texts
from app.models.knowledge import KnowledgeChunk, KnowledgeDocument

logger = logging.getLogger(__name__)


@after_setup_logger.connect
def configure_worker_logging(**_kwargs):
    from app.core.observability import configure_logging
    configure_logging(settings.log_level)


celery_app = Celery("ai_employee", broker=settings.redis_url)
celery_app.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
    beat_schedule={"requeue-pending-messages": {"task": "messaging.requeue_pending", "schedule": 60.0}},
)


async def process_document(document_id: uuid.UUID) -> None:
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions() as db:
            document = await db.get(KnowledgeDocument, document_id)
            if not document or document.status == "ready":
                return
            document.status = "processing"
            document.error_message = None
            await db.commit()
            data, extension, organization_id = (
                document.file_bytes,
                document.media_type,
                document.organization_id,
            )
        try:
            chunks = split_text(extract_text(data, extension))
            vectors = await embed_texts(chunks)
            async with sessions() as db:
                document = await db.scalar(
                    select(KnowledgeDocument)
                    .where(KnowledgeDocument.id == document_id)
                    .with_for_update()
                )
                if (
                    not document
                    or document.organization_id != organization_id
                    or document.status == "ready"
                ):
                    return
                await db.execute(
                    delete(KnowledgeChunk).where(KnowledgeChunk.document_id == document_id)
                )
                db.add_all(
                    [
                        KnowledgeChunk(
                            document_id=document_id,
                            organization_id=organization_id,
                            chunk_index=index,
                            content=chunk,
                            embedding=vector,
                        )
                        for index, (chunk, vector) in enumerate(zip(chunks, vectors, strict=True))
                    ]
                )
                document.status = "ready"
                document.chunk_count = len(chunks)
                document.error_message = None
                await db.commit()
        except Exception:
            logger.exception("Document processing failed for %s", document_id)
            async with sessions() as db:
                document = await db.scalar(
                    select(KnowledgeDocument)
                    .where(KnowledgeDocument.id == document_id)
                    .with_for_update()
                )
                if document and document.status != "ready":
                    document.status = "failed"
                    document.error_message = (
                        "Unable to process this document. Check its format and retry."
                    )
                    await db.commit()
    finally:
        await engine.dispose()


@celery_app.task(name="knowledge.process_document", acks_late=True)
def process_document_task(document_id: str) -> None:
    asyncio.run(process_document(uuid.UUID(document_id)))


@celery_app.task(name="messaging.deliver_message", acks_late=True)
def deliver_message_task(message_id: str) -> None:
    from app.core.messaging_delivery import deliver_message
    asyncio.run(deliver_message(uuid.UUID(message_id)))


@celery_app.task(name="messaging.requeue_pending")
def requeue_pending_messages() -> None:
    from app.models.messaging import OutboundMessage
    from app.models.campaign import CampaignRecipient

    async def enqueue():
        engine = create_async_engine(settings.database_url, pool_pre_ping=True)
        try:
            async with async_sessionmaker(engine)() as db:
                await db.execute(update(OutboundMessage).where(OutboundMessage.status == "sending", OutboundMessage.started_at < datetime.now(UTC) - timedelta(minutes=5)).values(status="unknown", error_message="Worker interrupted; confirm delivery with the provider before retrying."))
                await db.commit()
                ids = (await db.scalars(select(OutboundMessage.id).where(OutboundMessage.status == "queued",
                    ~select(CampaignRecipient.id).where(CampaignRecipient.message_id == OutboundMessage.id).exists()).limit(100))).all()
            for message_id in ids:
                await asyncio.to_thread(deliver_message_task.delay, str(message_id))
        finally:
            await engine.dispose()
    asyncio.run(enqueue())
