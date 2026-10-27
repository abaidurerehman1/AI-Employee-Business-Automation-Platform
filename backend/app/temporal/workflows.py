from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy


@workflow.defn(name="agent_tool_execution")
class AgentToolExecutionWorkflow:
    def __init__(self) -> None:
        self._decision: str | None = None
        self._status = "queued"

    @workflow.signal
    def decide(self, decision: str) -> None:
        if self._decision is None and decision in {"approve", "reject"}:
            self._decision = decision

    @workflow.query
    def status(self) -> str:
        return self._status

    @workflow.run
    async def run(self, payload: dict[str, Any]) -> dict[str, str | None]:
        request_id = payload["request_id"]
        if payload.get("resume_only"):
            await workflow.execute_activity(
                "resume_agent_conversation", request_id,
                start_to_close_timeout=timedelta(seconds=60),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            self._status = "completed"
            return {"status": self._status, "result": None}
        if payload["requires_approval"]:
            self._status = "pending"
            deadline = workflow.now() + timedelta(hours=24)
            while self._decision is None:
                expired = workflow.now() >= deadline
                saved_decision = await workflow.execute_activity(
                    "read_tool_decision", args=[request_id, expired],
                    start_to_close_timeout=timedelta(seconds=10),
                    retry_policy=RetryPolicy(maximum_attempts=3),
                )
                if self._decision is None:
                    self._decision = saved_decision
                if self._decision is None:
                    try:
                        await workflow.wait_condition(
                            lambda: self._decision is not None,
                            timeout=min(timedelta(seconds=30), deadline - workflow.now()),
                        )
                    except TimeoutError:
                        pass
            if self._decision == "timeout":
                self._status = "timed_out"
                await workflow.execute_activity(
                    "resume_agent_conversation",
                    request_id,
                    start_to_close_timeout=timedelta(seconds=30),
                    retry_policy=RetryPolicy(maximum_attempts=3),
                )
                return {"status": self._status, "result": None}
            if self._decision == "reject":
                self._status = "rejected"
                await workflow.execute_activity(
                    "resume_agent_conversation",
                    request_id,
                    start_to_close_timeout=timedelta(seconds=30),
                    retry_policy=RetryPolicy(maximum_attempts=3),
                )
                return {"status": self._status, "result": None}

        self._status = "running"
        try:
            result = await workflow.execute_activity(
                "execute_agent_tool",
                payload,
                start_to_close_timeout=timedelta(seconds=15),
                schedule_to_close_timeout=timedelta(seconds=50),
                retry_policy=RetryPolicy(
                    initial_interval=timedelta(seconds=1),
                    backoff_coefficient=2,
                    maximum_interval=timedelta(seconds=8),
                    maximum_attempts=3,
                ),
            )
        except Exception:
            self._status = "failed"
            raise
        self._status = "completed"
        if payload["requires_approval"] or payload.get("resume_after_execution"):
            await workflow.execute_activity(
                "resume_agent_conversation",
                request_id,
                start_to_close_timeout=timedelta(seconds=60),
                schedule_to_close_timeout=timedelta(minutes=3),
                retry_policy=RetryPolicy(
                    initial_interval=timedelta(seconds=2),
                    backoff_coefficient=2,
                    maximum_interval=timedelta(seconds=10),
                    maximum_attempts=3,
                ),
            )
        return {"status": self._status, "result": result}
