import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from tests.test_auth import login, register_and_verify


@pytest.mark.skipif(os.getenv("RUN_LIVE_OPENAI") != "1", reason="Live OpenAI test is opt-in")
def test_live_openai_playground(client: TestClient) -> None:
    register_and_verify(client, "live-test@example.com", "Test workspace")
    user = login(client, "live-test@example.com")
    headers = {
        "X-Organization-ID": user["organizations"][0]["id"],
        "X-CSRF-Token": user["csrf_token"],
    }
    agent = client.post(
        "/api/v1/agents",
        headers=headers,
        json={"name": "Test", "role": "Assistant", "instructions": "Respond briefly."},
    )
    assert agent.status_code == 201
    response = client.post(
        f"/api/v1/agents/{agent.json()['id']}/playground",
        headers=headers,
        json={"message": "Say hello."},
    )
    assert response.status_code == 200, response.text
    assert response.json()["messages"][-1]["content"]
    restored = client.get(
        f"/api/v1/agents/{agent.json()['id']}/conversations/{response.json()['conversation_id']}",
        headers=headers,
    )
    assert restored.status_code == 200
    assert restored.json()["messages"] == response.json()["messages"]


@pytest.mark.skipif(os.getenv("RUN_LIVE_OPENAI") != "1", reason="Live OpenAI test is opt-in")
def test_live_model_tool_approval(client: TestClient) -> None:
    register_and_verify(client, "live-tool@example.com", "Test workspace")
    user = login(client, "live-tool@example.com")
    headers = {
        "X-Organization-ID": user["organizations"][0]["id"],
        "X-CSRF-Token": user["csrf_token"],
    }
    agent = client.post(
        "/api/v1/agents",
        headers=headers,
        json={
            "name": "Clock",
            "role": "Assistant",
            "instructions": "Always call the current UTC time tool when asked for time.",
            "tools": ["get_current_utc_time"],
            "approval_rules": {"get_current_utc_time": True},
        },
    ).json()
    response = client.post(
        f"/api/v1/agents/{agent['id']}/playground",
        headers=headers,
        json={"message": "Use the current UTC time tool to tell me the time."},
    )
    assert response.status_code == 200, response.text
    requests = client.get(f"/api/v1/agents/{agent['id']}/tool-requests", headers=headers).json()
    assert len(requests) == 1
    assert requests[0]["status"] == "pending" and requests[0]["result"] is None
    approved = client.post(
        f"/api/v1/agents/{agent['id']}/tool-requests/{requests[0]['id']}/approve", headers=headers
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "completed"
    assert approved.json()["conversation_id"] == response.json()["conversation_id"]
    restored = client.get(
        f"/api/v1/agents/{agent['id']}/conversations/{response.json()['conversation_id']}",
        headers=headers,
    )
    assert approved.json()["result"] in restored.json()["messages"][-1]["content"]


def test_agent_versions_chat_and_tenant_isolation(client: TestClient) -> None:
    register_and_verify(client, "owner@example.com", "First")
    owner = login(client, "owner@example.com")
    org = owner["organizations"][0]["id"]
    headers = {"X-Organization-ID": org, "X-CSRF-Token": owner["csrf_token"]}
    config = {
        "name": "Sales",
        "role": "Sales assistant",
        "instructions": "Be helpful",
        "tone": "Friendly",
        "language": "English",
        "model": "gpt-4.1-mini",
    }
    created = client.post("/api/v1/agents", json=config, headers=headers)
    assert created.status_code == 201, created.text
    agent_id = created.json()["id"]
    assert (
        client.post(
            f"/api/v1/agents/{agent_id}/chat", json={"message": "Hi"}, headers=headers
        ).status_code
        == 409
    )
    with patch("app.api.routes.agents.generate_response", new=AsyncMock(return_value="Hello!")):
        chat = client.post(
            f"/api/v1/agents/{agent_id}/playground", json={"message": "Hi"}, headers=headers
        )
        assert chat.status_code == 200, chat.text
        assert [item["content"] for item in chat.json()["messages"]] == ["Hi", "Hello!"]
        follow_up = client.post(
            f"/api/v1/agents/{agent_id}/playground",
            json={"message": "Continue", "conversation_id": chat.json()["conversation_id"]},
            headers=headers,
        )
        assert [item["content"] for item in follow_up.json()["messages"]] == [
            "Hi",
            "Hello!",
            "Continue",
            "Hello!",
        ]
    assert (
        client.post(f"/api/v1/agents/{agent_id}/publish", headers=headers).json()["status"]
        == "published"
    )
    config["instructions"] = "Updated"
    assert (
        client.put(f"/api/v1/agents/{agent_id}", json=config, headers=headers).json()[
            "latest_version"
        ]["version"]
        == 2
    )
    versions = client.get(f"/api/v1/agents/{agent_id}/versions", headers=headers).json()
    assert [item["instructions"] for item in versions] == ["Updated", "Be helpful"]
    model = AsyncMock(return_value="Hello!")
    with patch("app.api.routes.agents.generate_response", new=model):
        published_chat = client.post(
            f"/api/v1/agents/{agent_id}/chat", json={"message": "Hi"}, headers=headers
        )
    assert published_chat.status_code == 200
    assert "Be helpful" in model.await_args.args[1]
    assert "Updated" not in model.await_args.args[1]
    assert (
        client.post(f"/api/v1/agents/{agent_id}/pause", headers=headers).json()["status"]
        == "paused"
    )
    assert (
        client.post(
            f"/api/v1/agents/{agent_id}/chat", json={"message": "Hi"}, headers=headers
        ).status_code
        == 409
    )
    client.cookies.clear()
    register_and_verify(client, "other@example.com", "Other")
    other = login(client, "other@example.com")
    other_headers = {
        "X-Organization-ID": other["organizations"][0]["id"],
        "X-CSRF-Token": other["csrf_token"],
    }
    assert (
        client.get(f"/api/v1/agents/{agent_id}/versions", headers=other_headers).status_code == 404
    )
    assert client.get("/api/v1/agents", headers=other_headers).json() == []


def test_tools_require_permission_and_approval(client: TestClient) -> None:
    register_and_verify(client, "owner@example.com", "Team")
    owner = login(client, "owner@example.com")
    headers = {
        "X-Organization-ID": owner["organizations"][0]["id"],
        "X-CSRF-Token": owner["csrf_token"],
    }
    config = {
        "name": "Assistant",
        "role": "Assistant",
        "instructions": "Help",
        "tools": ["get_current_utc_time"],
        "approval_rules": {"get_current_utc_time": True},
    }
    agent = client.post("/api/v1/agents", json=config, headers=headers).json()
    agent_id = agent["id"]
    rejected = client.post(
        f"/api/v1/agents/{agent_id}/tool-requests",
        json={"tool_name": "unknown"},
        headers=headers,
    )
    assert rejected.status_code == 403
    pending = client.post(
        f"/api/v1/agents/{agent_id}/tool-requests",
        json={"tool_name": "get_current_utc_time"},
        headers=headers,
    )
    assert pending.status_code == 201
    assert pending.json()["status"] == "pending"
    assert pending.json()["result"] is None
    request_id = pending.json()["id"]
    approved = client.post(
        f"/api/v1/agents/{agent_id}/tool-requests/{request_id}/approve",
        headers=headers,
    )
    assert approved.json()["status"] == "completed"
    assert approved.json()["result"] is not None
    assert (
        client.post(
            f"/api/v1/agents/{agent_id}/tool-requests/{request_id}/approve",
            headers=headers,
        ).status_code
        == 409
    )


@pytest.mark.parametrize("decision", ["approve", "reject"])
def test_model_tool_call_creates_pending_approval(client: TestClient, decision: str) -> None:
    register_and_verify(client, "owner@example.com", "Team")
    owner = login(client, "owner@example.com")
    headers = {
        "X-Organization-ID": owner["organizations"][0]["id"],
        "X-CSRF-Token": owner["csrf_token"],
    }
    agent = client.post(
        "/api/v1/agents",
        headers=headers,
        json={
            "name": "Assistant",
            "role": "Helper",
            "instructions": "Help",
            "tools": ["get_current_utc_time"],
            "approval_rules": {"get_current_utc_time": True},
        },
    ).json()
    call_response = MagicMock()
    call_response.json.return_value = {
        "output": [
            {
                "type": "function_call",
                "name": "get_current_utc_time",
                "arguments": "{}",
                "call_id": "call-1",
            }
        ]
    }
    final_response = MagicMock()
    final_response.json.return_value = {
        "output": [
            {
                "type": "message",
                "content": [{"type": "output_text", "text": "Please approve the request."}],
            }
        ]
    }
    provider = AsyncMock()
    provider.post.side_effect = [call_response, final_response]
    provider.__aenter__.return_value = provider
    with (
        patch("app.core.openai_client.settings.openai_api_key", "test-key"),
        patch("app.core.openai_client.httpx.AsyncClient", return_value=provider),
    ):
        response = client.post(
            f"/api/v1/agents/{agent['id']}/playground",
            json={"message": "What time is it?"},
            headers=headers,
        )
    assert response.status_code == 200, response.text
    assert response.json()["messages"][-1]["content"] == "Please approve the request."
    requests = client.get(f"/api/v1/agents/{agent['id']}/tool-requests", headers=headers).json()
    assert len(requests) == 1
    assert requests[0]["status"] == "pending"
    assert requests[0]["result"] is None
    conversation_id = response.json()["conversation_id"]
    assert requests[0]["conversation_id"] == conversation_id
    blocked = client.post(
        f"/api/v1/agents/{agent['id']}/playground",
        json={"message": "yes", "conversation_id": conversation_id},
        headers=headers,
    )
    assert blocked.status_code == 409
    decided = client.post(
        f"/api/v1/agents/{agent['id']}/tool-requests/{requests[0]['id']}/{decision}",
        headers=headers,
    )
    assert decided.status_code == 200
    restored = client.get(
        f"/api/v1/agents/{agent['id']}/conversations/{conversation_id}",
        headers=headers,
    )
    if decision == "approve":
        assert decided.json()["result"]
        assert restored.json()["messages"][-1]["content"] == (
            f"The current UTC time is {decided.json()['result']}."
        )
    else:
        assert decided.json()["result"] is None
        assert "rejected" in restored.json()["messages"][-1]["content"]
    assert (
        client.post(
            f"/api/v1/agents/{agent['id']}/tool-requests/{requests[0]['id']}/approve",
            headers=headers,
        ).status_code
        == 409
    )
    continuation = provider.post.await_args_list[1].kwargs["json"]
    assert continuation["tool_choice"] == "none"
