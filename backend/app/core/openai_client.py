import json
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from app.core.agent_tools import get_tool_schemas, validate_tool_arguments
from app.core.config import settings


class ProviderError(Exception):
    pass


async def generate_response(
    model: str,
    instructions: str,
    messages: list[dict[str, str]],
    tool_names: list[str] | None = None,
    tool_handler: Callable[[str, dict[str, Any], str], Awaitable[str]] | None = None,
) -> str:
    if not settings.openai_api_key:
        raise ProviderError("OpenAI API key is not configured")
    if sum(len(item.get("content", "")) for item in messages) + len(instructions) > settings.agent_max_input_characters:
        raise ProviderError("The conversation exceeds the input budget. Start a new conversation.")
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            body = {
                "model": model,
                "instructions": instructions,
                "input": list(messages),
                "store": False,
                "max_output_tokens": settings.agent_max_output_tokens,
            }
            if tool_names:
                body["tools"] = get_tool_schemas(tool_names)
            response = await client.post(
                "https://api.openai.com/v1/responses",
                headers={"Authorization": f"Bearer {settings.openai_api_key}"},
                json=body,
            )
            response.raise_for_status()
            payload = response.json()
            calls = [
                item for item in payload.get("output", []) if item.get("type") == "function_call"
            ]
            if calls:
                if not tool_handler or len(calls) > settings.agent_max_tool_calls:
                    raise ProviderError("Tool call budget exceeded or tools are unavailable")
                continuation = list(messages) + payload["output"]
                for call in calls:
                    name = call.get("name", "")
                    if name not in (tool_names or []):
                        raise ProviderError("OpenAI requested an unavailable tool")
                    arguments = validate_tool_arguments(name, call.get("arguments", "{}"))
                    result = await tool_handler(name, arguments, call.get("call_id", ""))
                    continuation.append(
                        {
                            "type": "function_call_output",
                            "call_id": call["call_id"],
                            "output": result,
                        }
                    )
                body["input"] = continuation
                body["tool_choice"] = "none"
                response = await client.post(
                    "https://api.openai.com/v1/responses",
                    headers={"Authorization": f"Bearer {settings.openai_api_key}"},
                    json=body,
                )
                response.raise_for_status()
                payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise ProviderError(
            "OpenAI request failed. Check provider configuration and try again."
        ) from exc
    output = [
        item.get("text", "")
        for message in payload.get("output", [])
        if message.get("type") == "message"
        for item in message.get("content", [])
        if item.get("type") == "output_text"
    ]
    if not output:
        raise ProviderError("OpenAI returned no text response")
    return "\n".join(output)
