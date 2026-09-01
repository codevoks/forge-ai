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
