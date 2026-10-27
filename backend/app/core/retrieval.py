import json
import re
import uuid
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.embeddings import embed_texts


@dataclass
class RetrievedChunk:
    document_id: uuid.UUID
    chunk_id: uuid.UUID
    filename: str
    chunk_index: int
    content: str
    score: float


def _normalize_query_for_search(query: str) -> str:
    """Keep only search-relevant tokens for tsquery and vector retrieval."""
    normalized = re.sub(r"[^\w\s-]", " ", (query or "").lower())
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


async def hybrid_search(
    db: AsyncSession, organization_id: uuid.UUID, query: str, limit: int = 5
) -> list[RetrievedChunk]:
    cleaned_query = _normalize_query_for_search(query)
    if not cleaned_query:
        return []

    vector = (await embed_texts([cleaned_query]))[0]
    sql = text(
        """
        WITH scoped AS MATERIALIZED (
            SELECT
                c.id,
                c.document_id,
                c.chunk_index,
                c.content,
                c.embedding,
                d.filename
            FROM knowledge_chunks c
            JOIN knowledge_documents d ON d.id = c.document_id
            WHERE c.organization_id = :org_id
              AND d.organization_id = :org_id
              AND d.status = 'ready'
        ),
        semantic AS (
            SELECT
                id,
                ROW_NUMBER() OVER (
                    ORDER BY embedding <=> CAST(:query_vector AS vector), id
                ) AS rank
            FROM scoped
            WHERE embedding <=> CAST(:query_vector AS vector) < 0.75
            ORDER BY embedding <=> CAST(:query_vector AS vector), id
            LIMIT 50
        ),
        keyword AS (
            SELECT
                id,
                ROW_NUMBER() OVER (
                    ORDER BY ts_rank_cd(
                        to_tsvector('simple', content),
                        websearch_to_tsquery('simple', :query)
                    ) DESC, id
                ) AS rank
            FROM scoped
            WHERE to_tsvector('simple', content) @@ websearch_to_tsquery('simple', :query)
            ORDER BY ts_rank_cd(
                to_tsvector('simple', content),
                websearch_to_tsquery('simple', :query)
            ) DESC, id
            LIMIT 50
        )
        SELECT
            s.id AS chunk_id,
            s.document_id,
            s.filename,
            s.chunk_index,
            s.content,
            (
                COALESCE(1.0 / (60 + semantic.rank), 0.0)
                + COALESCE(1.0 / (60 + keyword.rank), 0.0)
            ) AS score
        FROM scoped s
        LEFT JOIN semantic ON semantic.id = s.id
        LEFT JOIN keyword ON keyword.id = s.id
        WHERE semantic.id IS NOT NULL OR keyword.id IS NOT NULL
        ORDER BY score DESC, s.id
        LIMIT :limit
        """
    )
    rows = await db.execute(
        sql,
        {
            "org_id": organization_id,
            "query_vector": json.dumps(vector),
            "query": cleaned_query,
            "limit": max(1, min(limit, 10)),
        },
    )
    return [RetrievedChunk(**dict(row._mapping)) for row in rows]
