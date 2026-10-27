from datetime import UTC, datetime

TOOL_REGISTRY = {
    "get_current_utc_time": {
        "name": "get_current_utc_time",
        "description": "Read the current UTC date and time.",
    }
}


def execute_tool(name: str) -> str:
    if name == "get_current_utc_time":
        return datetime.now(UTC).isoformat()
    raise ValueError("Unknown tool")
