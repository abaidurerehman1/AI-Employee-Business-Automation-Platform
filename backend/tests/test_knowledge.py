import io
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from docx import Document
from fastapi.testclient import TestClient
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from app.core.document_processing import extract_text, split_text
from tests.test_auth import login, register_and_verify


def test_text_extraction_and_chunking() -> None:
    assert extract_text(b"Hello\t world\n\n\nNext", "txt") == "Hello world\n\nNext"
    document = Document()
    document.add_paragraph("Company policy: breakfast starts at 8.")
    document.add_table(rows=1, cols=2).rows[0].cells[0].text = "Room price"
    docx = io.BytesIO()
    document.save(docx)
    assert "breakfast starts at 8" in extract_text(docx.getvalue(), "docx")

    writer = PdfWriter()
    page = writer.add_blank_page(width=300, height=300)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
    )
    stream = DecodedStreamObject()
    stream.set_data(b"BT /F1 14 Tf 20 200 Td (Hotel check-in starts at 3pm.) Tj ET")
    page[NameObject("/Contents")] = writer._add_object(stream)
    pdf = io.BytesIO()
    writer.write(pdf)
    assert "check-in starts at 3pm" in extract_text(pdf.getvalue(), "pdf")
    chunks = split_text("Sentence about booking. " * 300)
    assert len(chunks) > 1
    assert all(len(chunk) <= 1200 for chunk in chunks)
    with pytest.raises(ValueError):
        extract_text(b"   ", "txt")


def test_upload_limits_tenant_isolation_and_delete(client: TestClient) -> None:
    register_and_verify(client, "owner@example.com", "One")
    user = login(client, "owner@example.com")
    headers = {
        "X-Organization-ID": user["organizations"][0]["id"],
        "X-CSRF-Token": user["csrf_token"],
    }
    with patch("app.api.routes.knowledge.process_document_task.delay") as enqueue:
        result = client.post(
            "/api/v1/knowledge/documents",
            headers=headers,
            files={"file": ("info.txt", b"Company policy", "text/plain")},
        )
    assert result.status_code == 202, result.text
    document_id = result.json()["id"]
    assert result.json()["status"] == "queued"
    enqueue.assert_called_once_with(document_id)
    assert (
        client.post(
            "/api/v1/knowledge/documents",
            headers=headers,
            files={"file": ("bad.exe", b"payload", "text/plain")},
        ).status_code
        == 415
    )
    assert (
        client.post(
            "/api/v1/knowledge/documents",
            headers=headers,
            files={"file": ("bad.pdf", b"not a pdf", "application/pdf")},
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/api/v1/knowledge/documents",
            headers=headers,
            files={"file": ("bad.txt", b"\xff", "text/plain")},
        ).status_code
        == 400
    )
    client.cookies.clear()
    register_and_verify(client, "other@example.com", "Two")
    other = login(client, "other@example.com")
    other_headers = {
        "X-Organization-ID": other["organizations"][0]["id"],
        "X-CSRF-Token": other["csrf_token"],
    }
    assert client.get("/api/v1/knowledge/documents", headers=other_headers).json() == []
    assert (
        client.delete(
            f"/api/v1/knowledge/documents/{document_id}", headers=other_headers
        ).status_code
        == 404
    )
    client.cookies.clear()
    owner = login(client, "owner@example.com")
    headers["X-CSRF-Token"] = owner["csrf_token"]
    assert (
        client.delete(f"/api/v1/knowledge/documents/{document_id}", headers=headers).status_code
        == 204
    )
    assert client.get("/api/v1/knowledge/documents", headers=headers).json() == []


def test_agent_response_keeps_citation_metadata(client: TestClient) -> None:
    from app.core.retrieval import RetrievedChunk

    register_and_verify(client, "owner@example.com", "One")
    session = login(client, "owner@example.com")
    headers = {
        "X-Organization-ID": session["organizations"][0]["id"],
        "X-CSRF-Token": session["csrf_token"],
    }
    with patch("app.api.routes.knowledge.process_document_task.delay"):
        doc = client.post(
            "/api/v1/knowledge/documents",
            headers=headers,
            files={"file": ("policy.txt", b"Check-in is 3pm", "text/plain")},
        ).json()
    agent = client.post(
        "/api/v1/agents",
        headers=headers,
        json={"name": "Host", "role": "Support", "instructions": "Help guests"},
    ).json()
    source = RetrievedChunk(
        document_id=uuid4(),
        chunk_id=uuid4(),
        filename="policy.txt",
        chunk_index=0,
        content="Check-in is 3pm",
        score=0.1,
    )
    # Treat the uploaded document as indexed without invoking a worker in this isolated test.
    import asyncio

    from app.db.session import get_db
    from app.main import app
    from app.models.knowledge import KnowledgeDocument

    async def mark_ready():
        async for db in app.dependency_overrides[get_db]():
            document = await db.get(KnowledgeDocument, UUID(doc["id"]))
            document.status = "ready"
            await db.commit()

    asyncio.run(mark_ready())
    from unittest.mock import AsyncMock

    with (
        patch("app.core.rag_graph.hybrid_search", new=AsyncMock(return_value=[source])),
        patch(
            "app.core.rag_graph.generate_response",
            new=AsyncMock(return_value="Check-in is at 3pm [1]."),
        ),
    ):
        result = client.post(
            f"/api/v1/agents/{agent['id']}/playground",
            headers=headers,
            json={"message": "When is check-in?"},
        )
    assert result.status_code == 200, result.text
    assert result.json()["messages"][-1]["citations"][0]["filename"] == "policy.txt"
    restored = client.get(
        f"/api/v1/agents/{agent['id']}/conversations/{result.json()['conversation_id']}",
        headers=headers,
    )
    assert restored.json()["messages"][-1]["citations"][0]["filename"] == "policy.txt"


def test_hybrid_search_prefers_exact_document_matches_for_tenant_queries() -> None:
    from app.core.retrieval import _normalize_query_for_search

    assert (
        _normalize_query_for_search("What is the Aurora plan price? ")
        == "what is the aurora plan price"
    )
    assert _normalize_query_for_search("$500 / pricing") == "500 pricing"
