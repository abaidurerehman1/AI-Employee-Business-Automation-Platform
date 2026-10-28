"""Request metadata only: never log bodies, query strings, tokens or credentials."""

import json
import logging
import time
import uuid
from datetime import UTC, datetime

from starlette.types import ASGIApp, Receive, Scope, Send


class JsonFormatter(logging.Formatter):
    def format(self, record):
        return json.dumps(
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "level": record.levelname,
                "logger": record.name,
                "event": record.getMessage(),
                **getattr(record, "metadata", {}),
            },
            default=str,
        )


def configure_logging(level="INFO"):
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger("app")
    logger.handlers = [handler]
    logger.setLevel(level)
    logger.propagate = False


class RequestMetadataMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        request_id = uuid.uuid4().hex
        scope.setdefault("state", {})["request_id"] = request_id
        started, status = time.monotonic(), 500

        async def send_response(event):
            nonlocal status
            if event["type"] == "http.response.start":
                status = event["status"]
                event.setdefault("headers", []).extend(
                    [
                        (b"x-request-id", request_id.encode()),
                        (b"x-content-type-options", b"nosniff"),
                        (b"referrer-policy", b"no-referrer"),
                        (b"cache-control", b"no-store"),
                    ]
                )
            await send(event)

        try:
            await self.app(scope, receive, send_response)
        finally:
            route = scope.get("route")
            logging.getLogger("app.http").info(
                "request_completed",
                extra={
                    "metadata": {
                        "request_id": request_id,
                        "method": scope["method"],
                        "route": getattr(route, "path", "unmatched"),
                        "status": status,
                        "duration_ms": round((time.monotonic() - started) * 1000, 2),
                    }
                },
            )
