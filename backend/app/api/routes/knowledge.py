import asyncio
import uuid
from pathlib import PurePath
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, select

from app.api.dependencies import (
    DbSession,
    TenantContext,
    get_tenant_context,
    require_csrf,
    require_roles,
)
from app.core.config import settings
from app.core.embeddings import EmbeddingError
from app.core.retrieval import hybrid_search
from app.models.auth import MembershipRole, User
from app.models.knowledge import KnowledgeChunk, KnowledgeDocument
from app.worker import process_document_task

router = APIRouter(prefix="/knowledge", tags=["knowledge"])
Manager = Annotated[
    TenantContext, Depends(require_roles(MembershipRole.admin, MembershipRole.manager))
]
Tenant = Annotated[TenantContext, Depends(get_tenant_context)]
CsrfUser = Annotated[User, Depends(require_csrf)]


class DocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    filename: str
    status: str
    error_message: str | None
    chunk_count: int


class SearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=2000)


class SearchResult(BaseModel):
    document_id: uuid.UUID
    chunk_id: uuid.UUID
    filename: str
    chunk_index: int
    content: str
    score: float


async def enqueue(document: KnowledgeDocument, db: DbSession) -> None:
    try:
        await asyncio.to_thread(process_document_task.delay, str(document.id))
    except Exception as exc:
        document.status = "failed"
        document.error_message = "Could not queue document processing. Please retry."
        await db.commit()
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, document.error_message) from exc


@router.get("/documents", response_model=list[DocumentResponse])
async def list_documents(db: DbSession, context: Tenant) -> list[KnowledgeDocument]:
    documents = await db.scalars(
        select(KnowledgeDocument)
        .where(KnowledgeDocument.organization_id == context.organization.id)
        .order_by(KnowledgeDocument.created_at.desc())
    )
    return list(documents.all())


@router.post("/documents", response_model=DocumentResponse, status_code=202)
async def upload_document(
    db: DbSession, context: Manager, _user: CsrfUser, file: Annotated[UploadFile, File()]
) -> KnowledgeDocument:
    filename = PurePath((file.filename or "").replace("\\", "/")).name.strip()
    if not filename or len(filename) > 255 or any(ord(char) < 32 for char in filename):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid filename")
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if extension not in {"pdf", "docx", "txt"}:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Only PDF, DOCX and TXT files are supported"
        )
    data = await file.read(settings.max_document_bytes + 1)
    await file.close()
    if not data or len(data) > settings.max_document_bytes:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE, "File is empty or exceeds the size limit"
        )
    if extension == "pdf" and not data.startswith(b"%PDF-"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid PDF file")
    if extension == "docx" and not data.startswith(b"PK\x03\x04"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid DOCX file")
    if extension == "txt":
        try:
            data.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "TXT files must be UTF-8") from exc
    document = KnowledgeDocument(
        organization_id=context.organization.id,
        uploaded_by=context.user.id,
        filename=filename,
        media_type=extension,
        file_bytes=data,
        status="queued",
        chunk_count=0,
    )
    db.add(document)
    await db.commit()
    await db.refresh(document)
    await enqueue(document, db)
    return document


@router.post("/documents/{document_id}/retry", response_model=DocumentResponse)
async def retry_document(
    document_id: uuid.UUID, db: DbSession, context: Manager, _user: CsrfUser
) -> KnowledgeDocument:
    document = await db.scalar(
        select(KnowledgeDocument)
        .where(
            KnowledgeDocument.id == document_id,
            KnowledgeDocument.organization_id == context.organization.id,
        )
        .with_for_update()
    )
    if not document:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    if document.status != "failed":
        raise HTTPException(status.HTTP_409_CONFLICT, "Only failed documents can be retried")
    document.status = "queued"
    document.error_message = None
    await db.commit()
    await enqueue(document, db)
    return document


@router.delete("/documents/{document_id}", status_code=204)
async def delete_document(
    document_id: uuid.UUID, db: DbSession, context: Manager, _user: CsrfUser
) -> None:
    document = await db.scalar(
        select(KnowledgeDocument)
        .where(
            KnowledgeDocument.id == document_id,
            KnowledgeDocument.organization_id == context.organization.id,
        )
        .with_for_update()
    )
    if not document:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    await db.execute(
        delete(KnowledgeChunk).where(
            KnowledgeChunk.document_id == document.id,
            KnowledgeChunk.organization_id == context.organization.id,
        )
    )
    await db.delete(document)
    await db.commit()


@router.post("/search", response_model=list[SearchResult])
async def search_knowledge(
    payload: SearchRequest, db: DbSession, context: Tenant, _user: CsrfUser
) -> list[SearchResult]:
    try:
        chunks = await hybrid_search(db, context.organization.id, payload.query)
    except EmbeddingError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    return [SearchResult(**vars(chunk)) for chunk in chunks]
