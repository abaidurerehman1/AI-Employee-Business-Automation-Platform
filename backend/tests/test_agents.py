import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from tests.test_auth import login, register_and_verify


@pytest.mark.asyncio
async def test_agent_input_and_tool_budgets():
    from app.core.openai_client import ProviderError, generate_response

    with patch("app.core.openai_client.settings.openai_api_key", "test"), patch(
        "app.core.openai_client.settings.agent_max_input_characters", 10
    ):
        with pytest.raises(ProviderError, match="input budget"):
            await generate_response("test", "instructions too long", [{"role": "user", "content": "hello"}])

    response = MagicMock()
    response.json.return_value = {"output": [
        {"type": "function_call", "name": "get_current_utc_time", "arguments": "{}", "call_id": str(i)}
        for i in range(4)
    ]}
    provider = AsyncMock()
    provider.post.return_value = response
    provider.__aenter__.return_value = provider
    handler = AsyncMock()
    with patch("app.core.openai_client.settings.openai_api_key", "test"), patch(
        "app.core.openai_client.httpx.AsyncClient", return_value=provider
    ):
        with pytest.raises(ProviderError, match="budget"):
            await generate_response("test", "help", [{"role": "user", "content": "time"}],
                                    tool_names=["get_current_utc_time"], tool_handler=handler)
    handler.assert_not_awaited()
    assert provider.post.await_args.kwargs["json"]["max_output_tokens"] > 0


def test_tool_schemas_validate_arguments() -> None:
    from app.core.agent_tools import ToolInputError, get_tool_schemas, validate_tool_arguments

    schema = get_tool_schemas(["get_current_utc_time"])[0]
    assert schema["name"] == "get_current_utc_time"
    assert schema["parameters"]["additionalProperties"] is False
    assert validate_tool_arguments("get_current_utc_time", "{}") == {}
    with pytest.raises(ToolInputError):
        validate_tool_arguments("get_current_utc_time", '{"unexpected": true}')


def test_handoff_copies_context_and_enforces_tenant(client: TestClient) -> None:
    register_and_verify(client, "handoff@example.com", "First")
    first = login(client, "handoff@example.com")
    headers = {"X-Organization-ID": first["organizations"][0]["id"], "X-CSRF-Token": first["csrf_token"]}
    config = {"name": "First agent", "role": "Sales", "instructions": "Help"}
    source = client.post("/api/v1/agents", json=config, headers=headers).json()
    target = client.post("/api/v1/agents", json={**config, "name": "Support"}, headers=headers).json()
    client.post(f"/api/v1/agents/{source['id']}/publish", headers=headers)
    client.post(f"/api/v1/agents/{target['id']}/publish", headers=headers)
    with patch("app.core.rag_graph.generate_response", new=AsyncMock(return_value="Hello from sales")):
        chat = client.post(f"/api/v1/agents/{source['id']}/chat", json={"message": "I need help"}, headers=headers)
    assert chat.status_code == 200, chat.text
    url = f"/api/v1/agents/{source['id']}/conversations/{chat.json()['conversation_id']}/handoff"
    assert client.post(url, json={"target_agent_id": source["id"]}, headers=headers).status_code == 400
    result = client.post(url, json={"target_agent_id": target["id"]}, headers=headers)
    assert result.status_code == 201, result.text
    assert result.json()["agent_id"] == target["id"]
    assert [item["content"] for item in result.json()["messages"][:2]] == ["I need help", "Hello from sales"]
    register_and_verify(client, "other-handoff@example.com", "Second")
    other = login(client, "other-handoff@example.com")
    other_headers = {"X-Organization-ID": other["organizations"][0]["id"], "X-CSRF-Token": other["csrf_token"]}
    foreign = client.post("/api/v1/agents", json=config, headers=other_headers).json()
    client.post(f"/api/v1/agents/{foreign['id']}/publish", headers=other_headers)
    headers["X-CSRF-Token"] = login(client, "handoff@example.com")["csrf_token"]
    assert client.post(url, json={"target_agent_id": foreign["id"]}, headers=headers).status_code == 404


def test_failed_workflow_can_be_retried(client: TestClient) -> None:
    from app.core.temporal_client import TemporalUnavailable
    register_and_verify(client, "retry@example.com", "Team")
    user = login(client, "retry@example.com")
    headers = {"X-Organization-ID": user["organizations"][0]["id"], "X-CSRF-Token": user["csrf_token"]}
    agent = client.post("/api/v1/agents", headers=headers, json={
        "name": "Assistant", "role": "Helper", "instructions": "Help",
        "tools": ["get_current_utc_time"], "approval_rules": {"get_current_utc_time": True},
    }).json()
    url = f"/api/v1/agents/{agent['id']}/tool-requests"
    with patch("app.api.routes.agents.start_tool_workflow", new=AsyncMock(side_effect=TemporalUnavailable("offline"))):
        response = client.post(url, headers=headers, json={"tool_name": "get_current_utc_time"})
    assert response.status_code == 503
    request = client.get(url, headers=headers).json()[0]
    assert request["status"] == "failed"
    with patch("app.api.routes.agents.start_tool_workflow", new=AsyncMock()) as start:
        retried = client.post(f"{url}/{request['id']}/retry", headers=headers)
    assert retried.status_code == 200, retried.text
    assert retried.json()["status"] == "pending"
    assert start.await_args.args[1]["requires_approval"] is True


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
    with patch("app.core.rag_graph.generate_response", new=AsyncMock(return_value="Hello!")):
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
    with patch("app.core.rag_graph.generate_response", new=model):
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
    with patch("app.api.routes.agents.start_tool_workflow", new=AsyncMock()):
        pending = client.post(
            f"/api/v1/agents/{agent_id}/tool-requests",
            json={"tool_name": "get_current_utc_time"},
            headers=headers,
        )
    assert pending.status_code == 201
    assert pending.json()["status"] == "pending"
    assert pending.json()["result"] is None
    request_id = pending.json()["id"]
    with patch("app.api.routes.agents.signal_tool_workflow", new=AsyncMock()) as signal:
        approved = client.post(
            f"/api/v1/agents/{agent_id}/tool-requests/{request_id}/approve",
            headers=headers,
        )
    assert approved.json()["status"] == "approved"
    assert approved.json()["result"] is None
    signal.assert_awaited_once_with(pending.json()["workflow_id"], "approve")
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
        patch("app.api.routes.agents.start_tool_workflow", new=AsyncMock()) as start_workflow,
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
    with patch("app.api.routes.agents.signal_tool_workflow", new=AsyncMock()) as signal:
        decided = client.post(
            f"/api/v1/agents/{agent['id']}/tool-requests/{requests[0]['id']}/{decision}",
            headers=headers,
        )
    assert decided.status_code == 200
    assert decided.json()["status"] == ("approved" if decision == "approve" else "rejected")
    signal.assert_awaited_once_with(requests[0]["workflow_id"], decision)
    start_workflow.assert_awaited_once()
    restored = client.get(
        f"/api/v1/agents/{agent['id']}/conversations/{conversation_id}",
        headers=headers,
    )
    if decision == "approve":
        assert decided.json()["result"] is None
        assert restored.json()["messages"][-1]["content"] == "Please approve the request."
    else:
        assert decided.json()["result"] is None
        assert restored.json()["messages"][-1]["content"] == "Please approve the request."
    assert (
        client.post(
            f"/api/v1/agents/{agent['id']}/tool-requests/{requests[0]['id']}/approve",
            headers=headers,
        ).status_code
        == 409
    )
    continuation = provider.post.await_args_list[1].kwargs["json"]
    assert continuation["tool_choice"] == "none"
