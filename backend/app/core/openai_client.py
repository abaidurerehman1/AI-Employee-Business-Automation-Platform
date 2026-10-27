import json
from collections.abc import Awaitable, Callable

import httpx

from app.core.config import settings


class ProviderError(Exception):
    pass


async def generate_response(
    model: str,
    instructions: str,
    messages: list[dict[str, str]],
    tool_names: list[str] | None = None,
    tool_handler: Callable[[str], Awaitable[str]] | None = None,
) -> str:
    if not settings.openai_api_key:
        raise ProviderError("OpenAI API key is not configured")
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            body = {
                "model": model,
                "instructions": instructions,
                "input": list(messages),
                "store": False,
            }
            if tool_names:
                body["tools"] = [
                    {
                        "type": "function",
                        "name": name,
                        "description": "Read the current UTC date and time.",
                        "parameters": {
                            "type": "object",
                            "properties": {},
                            "required": [],
                            "additionalProperties": False,
                        },
                        "strict": True,
                    }
                    for name in tool_names
                    if name == "get_current_utc_time"
                ]
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
                if not tool_handler or len(calls) > 3:
                    raise ProviderError("OpenAI requested unsupported tools")
                continuation = list(messages) + payload["output"]
                for call in calls:
                    name = call.get("name", "")
                    if (
                        name not in (tool_names or [])
                        or json.loads(call.get("arguments", "{}")) != {}
                    ):
                        raise ProviderError("OpenAI requested an unavailable tool")
                    result = await tool_handler(name)
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
