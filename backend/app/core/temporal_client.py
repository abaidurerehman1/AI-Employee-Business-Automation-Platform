import asyncio
from datetime import timedelta
from typing import Any

from temporalio.client import Client
from temporalio.common import WorkflowIDConflictPolicy

from app.core.config import settings
from app.temporal.workflows import AgentToolExecutionWorkflow


class TemporalUnavailable(Exception):
    pass


async def start_campaign_workflow(workflow_id: str, payload: dict) -> None:
    from app.temporal.campaigns import CampaignWorkflow
    from temporalio.common import WorkflowIDReusePolicy
    client = await _connect()
    try:
        await client.start_workflow(CampaignWorkflow.run, payload, id=workflow_id,
            task_queue=settings.temporal_task_queue, id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
            id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE)
    except Exception as exc:
        raise TemporalUnavailable("Unable to start campaign; retry Start to reconcile the same workflow ID") from exc


async def _connect() -> Client:
    try:
        return await asyncio.wait_for(
            Client.connect(
                settings.temporal_address,
                namespace=settings.temporal_namespace,
                tls=settings.temporal_tls,
                api_key=settings.temporal_api_key or None,
            ),
            timeout=5,
        )
    except Exception as exc:
        raise TemporalUnavailable("Workflow service is unavailable; retry shortly") from exc


async def start_tool_workflow(workflow_id: str, payload: dict[str, Any]) -> None:
    client = await _connect()
    try:
        await client.start_workflow(
            AgentToolExecutionWorkflow.run,
            payload,
            id=workflow_id,
            task_queue=settings.temporal_task_queue,
            execution_timeout=timedelta(hours=25),
            id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
        )
    except Exception as exc:
        raise TemporalUnavailable("Could not start tool workflow") from exc


async def signal_tool_workflow(workflow_id: str, decision: str) -> None:
    client = await _connect()
    try:
        handle = client.get_workflow_handle(workflow_id)
        await handle.signal(AgentToolExecutionWorkflow.decide, decision)
    except Exception as exc:
        raise TemporalUnavailable("Could not signal tool workflow") from exc


async def wait_tool_workflow(workflow_id: str, timeout_seconds: float = 50) -> dict[str, Any]:
    client = await _connect()
    try:
        handle = client.get_workflow_handle(workflow_id)
        return await asyncio.wait_for(handle.result(), timeout=timeout_seconds)
    except Exception as exc:
        raise TemporalUnavailable("Tool workflow did not complete in time") from exc
