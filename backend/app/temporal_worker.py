import asyncio
import logging

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

logger = logging.getLogger(__name__)


async def run_worker() -> None:
    while True:
        try:
            client = await Client.connect(
                settings.temporal_address,
                namespace=settings.temporal_namespace,
            )
            break
        except Exception:
            logger.exception("Temporal is not ready; retrying worker connection")
            await asyncio.sleep(3)

    worker = Worker(
        client,
        task_queue=settings.temporal_task_queue,
        workflows=[AgentToolExecutionWorkflow],
        activities=[execute_agent_tool, read_tool_decision, resume_agent_conversation],
    )
    await worker.run()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_worker())
