import asyncio
import logging
from contextlib import suppress

from temporalio import activity
from temporalio.client import Client
from temporalio.worker import Worker

from app.core.config import settings
from app.temporal.activities import (
    execute_agent_tool,
    read_tool_decision,
    resume_agent_conversation,
)
from app.temporal.workflows import AgentToolExecutionWorkflow
from app.temporal.campaigns import CampaignWorkflow, campaign_tick
from app.core.worker_health import heartbeat
from app.core.observability import configure_logging

logger = logging.getLogger(__name__)


async def run_worker() -> None:
    while True:
        try:
            client = await Client.connect(
                settings.temporal_address,
                namespace=settings.temporal_namespace,
                tls=settings.temporal_tls,
                api_key=settings.temporal_api_key or None,
            )
            break
        except Exception:
            logger.exception("Temporal is not ready; retrying worker connection")
            await asyncio.sleep(3)

    worker = Worker(
        client,
        task_queue=settings.temporal_task_queue,
        workflows=[AgentToolExecutionWorkflow, CampaignWorkflow],
        activities=[execute_agent_tool, read_tool_decision, resume_agent_conversation, campaign_tick],
    )
    pulse = asyncio.create_task(heartbeat())
    try:
        await worker.run()
    finally:
        pulse.cancel()
        with suppress(asyncio.CancelledError):
            await pulse


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    configure_logging(settings.log_level)
    asyncio.run(run_worker())
