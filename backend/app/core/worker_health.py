"""Container-local heartbeat for the Temporal poller process."""

import asyncio
import time
from pathlib import Path

HEARTBEAT = Path("/tmp/ai-employee-temporal.heartbeat")


async def heartbeat():
    try:
        while True:
            HEARTBEAT.write_text(str(time.time()), encoding="ascii")
            await asyncio.sleep(5)
    finally:
        HEARTBEAT.unlink(missing_ok=True)


def healthy():
    try:
        return 0 <= time.time() - float(HEARTBEAT.read_text(encoding="ascii")) < 30
    except (OSError, ValueError):
        return False


if __name__ == "__main__":
    raise SystemExit(0 if healthy() else 1)
