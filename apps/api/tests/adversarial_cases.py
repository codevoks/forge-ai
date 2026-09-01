from dataclasses import dataclass


@dataclass(frozen=True)
class AdversarialUrlCase:
    url: str
    expected_code: str
    reason: str


@dataclass(frozen=True)
class AdversarialAgentCase:
    scenario: str
    expected_outcome: str
    reason: str


@dataclass(frozen=True)
class AdversarialEngineCase:
    engine_kind: str
    scenario: str
    expected_outcome: str
    reason: str


@dataclass(frozen=True)
class AdversarialEvaluationCase:
    case_key: str
    expected_outcome: str
    reason: str


@dataclass(frozen=True)
class AdversarialDebuggerCase:
    scenario: str
    expected_outcome: str
    reason: str


@dataclass(frozen=True)
class AdversarialMCPCase:
    scenario: str
    expected_outcome: str
    reason: str


SSRF_DENIAL_CASES = (
    AdversarialUrlCase(
        url="http://example.com/callback",
        expected_code="network_scheme_denied",
        reason="plain HTTP is not accepted for tool egress",
    ),
    AdversarialUrlCase(
        url="https://localhost/admin",
        expected_code="network_private_host_denied",
        reason="loopback hostname must not be reachable from tool inputs",
    ),
    AdversarialUrlCase(
        url="https://127.0.0.1/admin",
        expected_code="network_private_address_denied",
        reason="loopback IP must not be reachable from tool inputs",
    ),
    AdversarialUrlCase(
        url="https://169.254.169.254/latest/meta-data",
        expected_code="network_private_address_denied",
        reason="link-local cloud metadata address must be denied",
    ),
    AdversarialUrlCase(
        url="https://10.0.0.4/internal",
        expected_code="network_private_address_denied",
        reason="private RFC1918 address must be denied",
    ),
)


AGENT_ADVERSARIAL_CASES = (
    AdversarialAgentCase(
        scenario="unauthorized_tool",
        expected_outcome="denied",
        reason="model-proposed tools outside the run grant must fail closed",
    ),
    AdversarialAgentCase(
        scenario="prompt_injection",
        expected_outcome="contained",
        reason="hostile objective text cannot become privileged agent instruction",
    ),
    AdversarialAgentCase(
        scenario="unsupported_claim",
        expected_outcome="denied",
        reason="consequential agent conclusions require persisted evidence citations",
    ),
)


LANGGRAPH_ADVERSARIAL_CASES = (
    AdversarialEngineCase(
        engine_kind="langgraph",
        scenario="unauthorized_tool",
        expected_outcome="denied",
        reason="LangGraph cannot expand run-scoped tool authority",
    ),
    AdversarialEngineCase(
        engine_kind="langgraph",
        scenario="prompt_injection",
        expected_outcome="contained",
        reason="LangGraph state/tool output cannot become privileged Forge instructions",
    ),
    AdversarialEngineCase(
        engine_kind="langgraph",
        scenario="step_limit",
        expected_outcome="denied",
        reason="framework orchestration must still stop at Forge-owned budgets",
    ),
)


EVALUATION_ADVERSARIAL_CASES = (
    AdversarialEvaluationCase(
        case_key="langchain_hallucinated_tool_denied",
        expected_outcome="passed",
        reason="LangChain interop cannot expand allowed tool authority",
    ),
    AdversarialEvaluationCase(
        case_key="langchain_prompt_injection_contained",
        expected_outcome="passed",
        reason="prompt-injected input remains untrusted data inside Forge validation",
    ),
    AdversarialEvaluationCase(
        case_key="langgraph_step_limit_failure",
        expected_outcome="passed",
        reason="framework orchestration must terminate at Forge-owned budgets",
    ),
)


MCP_ADVERSARIAL_CASES = (
    AdversarialMCPCase(
        scenario="remote_server_ssrf_denied",
        expected_outcome="denied",
        reason="HTTP MCP server URLs reuse the Phase 6 NetworkPolicy SSRF denial list",
    ),
    AdversarialMCPCase(
        scenario="remote_transport_zero_cost_denied",
        expected_outcome="denied",
        reason="remote MCP servers are an external integration and stay off the default path",
    ),
    AdversarialMCPCase(
        scenario="discovery_quarantine",
        expected_outcome="denied",
        reason="a newly discovered MCP tool cannot execute until an admin reviews and enables it",
    ),
    AdversarialMCPCase(
        scenario="malicious_description_contained",
        expected_outcome="contained",
        reason="a suspicious description/output is flagged and labeled untrusted, never executed",
    ),
    AdversarialMCPCase(
        scenario="schema_drift_blocks_execution",
        expected_outcome="denied",
        reason="a changed remote schema retires the enabled tool version until re-review",
    ),
    AdversarialMCPCase(
        scenario="confused_deputy_no_run_grant",
        expected_outcome="denied",
        reason="a globally enabled MCP tool still requires an explicit run-scoped grant to execute",
    ),
    AdversarialMCPCase(
        scenario="cross_tenant_server_hidden",
        expected_outcome="denied",
        reason="MCP servers, snapshots, and mappings are RLS-scoped like every other tenant record",
    ),
    AdversarialMCPCase(
        scenario="stdio_command_not_allowlisted",
        expected_outcome="denied",
        reason="only a Forge-owned, reviewable module may run as a local subprocess",
    ),
)


DEBUGGER_ADVERSARIAL_CASES = (
    AdversarialDebuggerCase(
        scenario="effect_replay",
        expected_outcome="blocked",
        reason="debug replay must not execute real side effects or reuse old approvals",
    ),
    AdversarialDebuggerCase(
        scenario="forged_cursor",
        expected_outcome="denied",
        reason="cursor replay/tampering must not leak or skip into another run scope",
    ),
    AdversarialDebuggerCase(
        scenario="cross_tenant_history",
        expected_outcome="denied",
        reason="history, checkpoints, traces, and replay artifacts remain tenant scoped",
    ),
)
