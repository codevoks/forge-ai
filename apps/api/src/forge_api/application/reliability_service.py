from typing import Any

from forge_api.api.errors import ProblemError
from forge_api.application.agent_runtime import AgentRuntime, LangGraphAgentRuntime
from forge_api.application.multi_agent_runtime import SpecialistAgentRuntime, SynthesizerRuntime
from forge_api.application.tool_runtime import ToolRuntime
from forge_api.domain.approvals import ApprovalRequiredError
from forge_api.domain.reliability import JobEnvelope, RetryPolicy, sanitize_payload
from forge_api.infrastructure.database import Database
from forge_api.infrastructure.telemetry import NullTelemetry
from forge_api.infrastructure.workflow_repositories import (
    EventRepository,
    OutboxRepository,
    WorkerRepository,
    correlation_id_from_trace_context,
)
from forge_api.ports.queue import QueuePort
from forge_api.ports.telemetry import TelemetryPort


class OutboxDispatcher:
    def __init__(self, *, database: Database, queue: QueuePort, worker_id: str) -> None:
        self.database = database
        self.queue = queue
        self.worker_id = worker_id

    def dispatch_once(self, *, limit: int = 50) -> int:
        dispatched = 0
        with self.database.transaction(worker_id=self.worker_id) as conn:
            outbox = OutboxRepository(conn)
            envelopes = outbox.due_unpublished(limit=limit)
            for envelope in envelopes:
                try:
                    self.queue.publish(envelope)
                    outbox.mark_published(message_id=envelope.message_id)
                    dispatched += 1
                except Exception as exc:  # noqa: BLE001
                    outbox.mark_failed_publish(message_id=envelope.message_id, error=str(exc))
        return dispatched


class DeterministicTaskExecutor:
    def __init__(self, *, tool_runtime: ToolRuntime, agent_runtime: AgentRuntime) -> None:
        self.tool_runtime = tool_runtime
        self.agent_runtime = agent_runtime
        self.langgraph_agent_runtime = LangGraphAgentRuntime(database=agent_runtime.database)
        self.specialist_agent_runtime = SpecialistAgentRuntime(database=agent_runtime.database)
        self.synthesizer_runtime = SynthesizerRuntime(database=agent_runtime.database)

    def execute(self, claim: dict[str, Any]) -> dict[str, Any]:
        if claim.get("kind") == "agent":
            task_input = claim.get("input", {})
            is_specialist = isinstance(task_input, dict) and bool(task_input.get("agent_role"))
            if is_specialist:
                # Isolated parallel specialists (Phase 12) always run on the
                # custom engine; LangGraph specialist orchestration is a
                # documented future extension, not implemented here.
                return self.specialist_agent_runtime.invoke_for_claim(claim)
            if claim.get("engine_kind") == "langgraph":
                return self.langgraph_agent_runtime.invoke_for_claim(claim)
            return self.agent_runtime.invoke_for_claim(claim)
        if claim.get("kind") == "tool":
            return self.tool_runtime.invoke_for_claim(claim)
        task_input = claim.get("input", {})
        if isinstance(task_input, dict) and task_input.get("mode") == "multi_agent_synthesize":
            # Deterministic multi-agent synthesis (Phase 12) reuses the plain
            # 'deterministic' step kind, tagged by this explicit input marker,
            # rather than adding a new kind value (see migration 012 for why).
            return self.synthesizer_runtime.invoke_for_claim(claim)
        failure_mode = task_input.get("failure_mode") if isinstance(task_input, dict) else None
        attempt_number = int(claim["attempt_number"])
        if failure_mode == "fail_once" and attempt_number == 1:
            raise RetryableExecutionError("deterministic transient failure")
        if failure_mode == "always_fail":
            raise PermanentExecutionError("deterministic permanent failure")
        return {
            "mode": "deterministic_worker",
            "summary": f"Worker completed {claim['name']} without external side effects.",
            "attempt_number": attempt_number,
        }


class RetryableExecutionError(Exception):
    pass


class PermanentExecutionError(Exception):
    pass


class WorkerConsumer:
    def __init__(
        self,
        *,
        database: Database,
        queue: QueuePort,
        worker_id: str,
        lease_seconds: int,
        retry_policy: RetryPolicy,
        telemetry: TelemetryPort | None = None,
    ) -> None:
        self.database = database
        self.queue = queue
        self.worker_id = worker_id
        self.lease_seconds = lease_seconds
        self.retry_policy = retry_policy
        self.telemetry = telemetry or NullTelemetry()
        self.executor = DeterministicTaskExecutor(
            tool_runtime=ToolRuntime(database=database),
            agent_runtime=AgentRuntime(database=database),
        )

    def consume_once(self, *, block_ms: int = 1000) -> str:
        envelope = self.queue.consume(consumer_name=self.worker_id, block_ms=block_ms)
        if envelope is None:
            return "idle"
        actor_id = str(envelope.payload.get("actor_id", envelope.tenant_id))
        handler_name = "deterministic-task-worker"

        with self.database.transaction(worker_id=self.worker_id) as conn:
            worker = WorkerRepository(conn, lease_seconds=self.lease_seconds)
            if not worker.begin_inbox(envelope=envelope, handler_name=handler_name):
                self.queue.ack(message_id=envelope.message_id)
                return "duplicate"
            claim = worker.claim_task(
                envelope=envelope,
                worker_id=self.worker_id,
                actor_id=actor_id,
            )
            if claim is None:
                worker.finish_inbox(envelope=envelope, handler_name=handler_name, status="skipped")
                self.queue.ack(message_id=envelope.message_id)
                return "skipped"

        parent_trace_context = envelope.payload.get("trace_context")
        if not isinstance(parent_trace_context, dict):
            parent_trace_context = None

        with self.telemetry.span(
            "task.execute",
            attributes={
                "task_id": claim.get("task_id"),
                "run_id": claim.get("run_id"),
                "kind": claim.get("kind"),
            },
            parent_trace_context=parent_trace_context,
        ) as trace_context:
            self._record_trace_correlation(
                claim=claim, actor_id=actor_id, trace_context=trace_context
            )
            try:
                result = self.executor.execute(claim)
            except RetryableExecutionError as exc:
                self._fail_claim(
                    envelope=envelope,
                    claim=claim,
                    actor_id=actor_id,
                    error_type="transient",
                    error_message=str(exc),
                )
                self.queue.ack(message_id=envelope.message_id)
                return "retry_scheduled"
            except PermanentExecutionError as exc:
                self._fail_claim(
                    envelope=envelope,
                    claim=claim,
                    actor_id=actor_id,
                    error_type="permanent",
                    error_message=str(exc),
                )
                self.queue.ack(message_id=envelope.message_id)
                return "dead_lettered"
            except ApprovalRequiredError:
                with self.database.transaction(worker_id=self.worker_id) as conn:
                    WorkerRepository(conn, lease_seconds=self.lease_seconds).finish_inbox(
                        envelope=envelope,
                        handler_name=handler_name,
                        status="succeeded",
                    )
                self.queue.ack(message_id=envelope.message_id)
                return "waiting_approval"
            except ProblemError as exc:
                self._fail_claim(
                    envelope=envelope,
                    claim=claim,
                    actor_id=actor_id,
                    error_type=exc.code,
                    error_message=exc.message,
                )
                self.queue.ack(message_id=envelope.message_id)
                return "policy_denied"

        with self.database.transaction(worker_id=self.worker_id) as conn:
            worker = WorkerRepository(conn, lease_seconds=self.lease_seconds)
            completed = worker.complete_attempt(claim=claim, result=result, actor_id=actor_id)
            worker.finish_inbox(
                envelope=envelope,
                handler_name=handler_name,
                status="succeeded" if completed else "skipped",
            )
        self.queue.ack(message_id=envelope.message_id)
        return "succeeded" if completed else "stale_fence"

    def _record_trace_correlation(
        self, *, claim: dict[str, Any], actor_id: str, trace_context: dict[str, str]
    ) -> None:
        if not trace_context:
            return
        with self.database.transaction(worker_id=self.worker_id) as conn:
            EventRepository(conn).append(
                tenant_id=str(claim["tenant_id"]),
                workspace_id=str(claim["workspace_id"]),
                run_id=str(claim["run_id"]),
                task_id=str(claim["task_id"]),
                aggregate_type="task",
                aggregate_id=str(claim["task_id"]),
                event_type="task.trace_correlated",
                actor_id=actor_id,
                payload={"span_name": "task.execute"},
                trace_context=dict(trace_context),
                correlation_id=correlation_id_from_trace_context(dict(trace_context)),
            )

    def _fail_claim(
        self,
        *,
        envelope: JobEnvelope,
        claim: dict[str, Any],
        actor_id: str,
        error_type: str,
        error_message: str,
    ) -> None:
        with self.database.transaction(worker_id=self.worker_id) as conn:
            worker = WorkerRepository(conn, lease_seconds=self.lease_seconds)
            worker.fail_attempt(
                claim=claim,
                error_type=error_type,
                error_message=error_message,
                actor_id=actor_id,
                retry_policy=self.retry_policy,
            )
            worker.finish_inbox(
                envelope=envelope,
                handler_name="deterministic-task-worker",
                status="failed",
            )


class RecoveryService:
    def __init__(self, *, database: Database, worker_id: str) -> None:
        self.database = database
        self.worker_id = worker_id

    def scan_once(self) -> dict[str, int]:
        with self.database.transaction(worker_id=self.worker_id) as conn:
            return WorkerRepository(conn).run_recovery_scan(actor_id=self.worker_id)


def safe_envelope_payload(envelope: JobEnvelope) -> dict[str, Any]:
    return sanitize_payload(
        {
            "message_id": envelope.message_id,
            "message_type": envelope.message_type,
            "aggregate_type": envelope.aggregate_type,
            "aggregate_id": envelope.aggregate_id,
        }
    )
