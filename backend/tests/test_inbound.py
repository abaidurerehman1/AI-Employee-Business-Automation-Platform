import hashlib
import hmac
import json
import time
from uuid import UUID
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from tests.test_auth import login, register_and_verify


@pytest.fixture(autouse=True)
def fake_limiter():
    with patch("app.api.routes.inbound.check_rate_limit", new=AsyncMock()):
        yield


def setup_site(client, email="inbound@example.com"):
    register_and_verify(client, email, "Inbound team")
    session = login(client, email)
    headers = {"X-Organization-ID": session["organizations"][0]["id"], "X-CSRF-Token": session["csrf_token"]}
    agent = client.post("/api/v1/agents", headers=headers, json={"name": "Support", "role": "Support", "instructions": "Help"}).json()
    assert client.post(f"/api/v1/agents/{agent['id']}/publish", headers=headers).status_code == 200
    site = client.put("/api/v1/inbound/site", headers=headers, json={"name": "Support chat", "agent_id": agent["id"], "enabled": True})
    assert site.status_code == 200, site.text
    return headers, session, site.json()


def test_public_capture_chat_handoff_and_assignment(client: TestClient):
    headers, session, site = setup_site(client)
    root = f"/api/v1/public/inbound/{site['id']}"
    assert client.get(root + "/config").json() == {"name": "Support chat"}
    visitor = client.post(root + "/sessions").json()
    visitor_headers = {"Authorization": f"Bearer {visitor['token']}"}
    assert client.get(root + "/messages", headers={"Authorization": "Bearer invalid"}).status_code == 401
    with patch("app.api.routes.inbound.run_rag_agent", new=AsyncMock(return_value=("We offer web design.", []))) as agent:
        answer = client.post(root + "/messages", headers=visitor_headers, json={"message": "What do you offer?"})
    assert answer.status_code == 200, answer.text
    assert answer.json()["answer"] == "We offer web design."
    assert agent.await_args.kwargs["organization_id"] == UUID(headers["X-Organization-ID"])
    assert agent.await_args.kwargs["tool_names"] == []
    lead = {"name": "Sara", "email": "SARA@example.com", "enquiry": "Need a website", "budget": "$500", "timeline": "soon"}
    assert client.post(root + "/lead", headers=visitor_headers, json=lead).status_code == 201
    assert client.post(root + "/lead", headers=visitor_headers, json=lead).status_code == 409
    assert client.get("/api/v1/crm/leads", headers=headers).json()["total"] == 1
    assert client.post(root + "/handoff", headers=visitor_headers).status_code == 200
    assert client.post(root + "/messages", headers=visitor_headers, json={"message": "I need help"}).json()["answer"] is None
    conversation_id = visitor["conversation_id"]
    assignment = client.post(f"/api/v1/inbound/conversations/{conversation_id}/assign", headers=headers,
        json={"assigned_to": session["user"]["id"], "status": "human"})
    assert assignment.status_code == 200, assignment.text
    reply = client.post(f"/api/v1/inbound/conversations/{conversation_id}/reply", headers=headers, json={"message": "Hello Sara"})
    assert reply.status_code == 200
    messages = client.get(root + "/messages", headers=visitor_headers).json()["messages"]
    assert messages[-1]["content"] == "Hello Sara"
    assert client.get(f"/api/v1/inbound/conversations/{conversation_id}", headers=headers).json()["context"]["budget"] == "$500"
    register_and_verify(client, "other-inbound@example.com", "Other")
    other = login(client, "other-inbound@example.com")
    other_headers = {"X-Organization-ID": other["organizations"][0]["id"], "X-CSRF-Token": other["csrf_token"]}
    assert client.get(f"/api/v1/inbound/conversations/{conversation_id}", headers=other_headers).status_code == 404
    assert client.post(f"/api/v1/inbound/conversations/{conversation_id}/reply", headers=other_headers, json={"message": "Unauthorized"}).status_code == 404
    assert client.post(f"/api/v1/inbound/conversations/{conversation_id}/assign", headers=other_headers, json={"assigned_to": other["user"]["id"], "status": "human"}).status_code == 404
    assert client.get("/api/v1/inbound/conversations", headers=other_headers).json() == []


def test_signed_webhook_rejects_invalid_and_deduplicates(client: TestClient):
    headers, _, site = setup_site(client)
    url = f"/api/v1/public/inbound/{site['id']}/webhook"
    body = json.dumps({"event_id": "event-1", "name": "Jane", "email": "jane@example.com", "enquiry": "Need support"}).encode()
    stamp = str(int(time.time()))
    signature = hmac.new(site["webhook_secret"].encode(), stamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    assert client.post(url, content=body, headers={"X-Timestamp": stamp, "X-Signature": "invalid"}).status_code == 401
    old = str(int(time.time()) - 301)
    stale_signature = hmac.new(site["webhook_secret"].encode(), old.encode() + b"." + body, hashlib.sha256).hexdigest()
    assert client.post(url, content=body, headers={"X-Timestamp": old, "X-Signature": stale_signature}).status_code == 401
    signed = {"X-Timestamp": stamp, "X-Signature": signature}
    assert client.post(url, content=body, headers=signed).json()["status"] == "received"
    assert client.post(url, content=body, headers=signed).json()["status"] == "already_received"
    assert client.get("/api/v1/crm/leads", headers=headers).json()["total"] == 1
    assert client.get("/api/v1/inbound/conversations", headers=headers).json()[0]["context"]["source"] == "webhook"
