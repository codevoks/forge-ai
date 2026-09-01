import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from forge_api.api.errors import ProblemError
from forge_api.domain import json_schema

MAX_TOOL_INPUT_BYTES = 4096
MAX_TOOL_OUTPUT_BYTES = 8192


class ToolRisk(StrEnum):
    READ_ONLY = "read_only"
    SIMULATED_EFFECT = "simulated_effect"


class InvocationStatus(StrEnum):
    INTENT_RECORDED = "intent_recorded"
    APPROVAL_REQUIRED = "approval_required"
    AUTHORIZED = "authorized"
    EXECUTING = "executing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    POLICY_DENIED = "policy_denied"
    OUTCOME_UNKNOWN = "outcome_unknown"


class TrustLabel(StrEnum):
    TRUSTED_LOCAL_FIXTURE = "trusted_local_fixture"
    UNTRUSTED_TOOL_OUTPUT = "untrusted_tool_output"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class DeploymentHistoryInput(StrictModel):
    service: Literal["api", "web", "worker"]
    environment: Literal["staging", "production"] = "production"


class DeploymentHistoryOutput(StrictModel):
    service: str
    environment: str
    deployments: list[dict[str, str]] = Field(min_length=1, max_length=10)


class CustomerReportsInput(StrictModel):
    product_area: Literal["workflow", "worker", "security"]
    severity: Literal["low", "medium", "high"] = "medium"


class CustomerReportsOutput(StrictModel):
    product_area: str
    reports: list[dict[str, str]] = Field(min_length=1, max_length=10)


class SimulatedTicketInput(StrictModel):
    title: str = Field(min_length=2, max_length=120)
    severity: Literal["low", "medium", "high"]
    dry_run: Literal[True] = True
    simulate_outcome_unknown: bool = False


class SimulatedTicketOutput(StrictModel):
    provider_operation_id: str
    status: Literal["simulated"]
    title: str
    severity: str


class ToolContract(Protocol):
    """The shape `ToolRuntime` needs from any tool origin (code-registered or MCP-mapped).

    Every member is a read-only property so both the code-registered `ToolDefinition`
    and the runtime-built `DynamicToolContract` (frozen dataclasses) satisfy it.
    """

    @property
    def name(self) -> str: ...

    @property
    def version(self) -> int: ...

    @property
    def risk(self) -> ToolRisk: ...

    @property
    def trust_label(self) -> TrustLabel: ...

    @property
    def origin(self) -> str: ...

    @property
    def input_schema(self) -> dict[str, Any]: ...

    @property
    def output_schema(self) -> dict[str, Any]: ...

    def validate_input(self, payload: dict[str, Any]) -> dict[str, Any]: ...

    def validate_output(self, payload: dict[str, Any]) -> dict[str, Any]: ...


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    version: int
    display_name: str
    description: str
    risk: ToolRisk
    input_model: type[StrictModel]
    output_model: type[StrictModel]
    timeout_ms: int
    retryable: bool
    trust_label: TrustLabel
    origin: str = "code"

    @property
    def input_schema(self) -> dict[str, Any]:
        return self.input_model.model_json_schema()

    @property
    def output_schema(self) -> dict[str, Any]:
        return self.output_model.model_json_schema()

    def validate_input(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            _assert_json_size(payload, max_bytes=MAX_TOOL_INPUT_BYTES, label="tool input")
            return self.input_model.model_validate(payload).model_dump()
        except ValidationError as exc:
            raise ProblemError(
                422,
                "tool_input_invalid",
                "Tool input did not match the registered schema.",
            ) from exc

    def validate_output(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            _assert_json_size(payload, max_bytes=MAX_TOOL_OUTPUT_BYTES, label="tool output")
            return self.output_model.model_validate(payload).model_dump()
        except ValidationError as exc:
            raise ProblemError(
                502,
                "tool_output_invalid",
                "Tool output did not match the registered schema.",
            ) from exc


@dataclass(frozen=True)
class DynamicToolContract:
    """A tool contract built at runtime from a stored JSON Schema (MCP-mapped tools).

    Unlike code tools, an MCP tool's schema is only known after discovery, so it
    cannot be a compile-time Pydantic model. Validation instead uses the bounded
    `forge_api.domain.json_schema` dialect against the exact schema an administrator
    reviewed and pinned at enable time.
    """

    name: str
    version: int
    risk: ToolRisk
    trust_label: TrustLabel
    input_json_schema: dict[str, Any]
    output_json_schema: dict[str, Any]
    origin: str = "mcp"

    @property
    def input_schema(self) -> dict[str, Any]:
        return self.input_json_schema

    @property
    def output_schema(self) -> dict[str, Any]:
        return self.output_json_schema

    def validate_input(self, payload: dict[str, Any]) -> dict[str, Any]:
        _assert_json_size(payload, max_bytes=MAX_TOOL_INPUT_BYTES, label="tool input")
        errors = json_schema.validate_payload(payload, self.input_json_schema)
        if errors:
            raise ProblemError(
                422,
                "tool_input_invalid",
                "Tool input did not match the registered schema.",
            )
        return payload

    def validate_output(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ProblemError(502, "tool_output_invalid", "Tool output must be an object.")
        _assert_json_size(payload, max_bytes=MAX_TOOL_OUTPUT_BYTES, label="tool output")
        errors = json_schema.validate_payload(payload, self.output_json_schema)
        if errors:
            raise ProblemError(
                502,
                "tool_output_invalid",
                "Tool output did not match the registered schema.",
            )
        return payload


def dynamic_contract_from_registry_row(row: dict[str, Any]) -> DynamicToolContract:
    """Build a `DynamicToolContract` from a `tool_versions`/`tool_definitions` join row.

    Used for MCP-mapped tools, which have no compile-time Pydantic model: the exact
    schema an administrator reviewed and pinned at enable time is stored as JSON on
    the immutable `tool_versions` row and read back here.
    """
    input_schema = row["input_schema"]
    output_schema = row["output_schema"]
    if not isinstance(input_schema, dict) or not isinstance(output_schema, dict):
        raise ProblemError(500, "tool_schema_invalid", "Stored tool schema is invalid.")
    return DynamicToolContract(
        name=str(row["name"]),
        version=int(row["version"]),
        risk=ToolRisk(str(row["risk"])),
        trust_label=TrustLabel(str(row["trust_label"])),
        input_json_schema=input_schema,
        output_json_schema=output_schema,
        origin=str(row["origin"]),
    )


def _assert_json_size(payload: dict[str, Any], *, max_bytes: int, label: str) -> None:
    size = len(canonical_json(payload).encode("utf-8"))
    if size > max_bytes:
        raise ProblemError(422, "tool_payload_too_large", f"{label} exceeds the allowed size.")


def canonical_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def action_hash(tool_name: str, tool_version: int, arguments: dict[str, Any]) -> str:
    digest = hashlib.sha256()
    digest.update(f"{tool_name}:{tool_version}:".encode())
    digest.update(canonical_json(arguments).encode("utf-8"))
    return digest.hexdigest()


def content_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def registered_tools() -> tuple[ToolDefinition, ...]:
    return (
        ToolDefinition(
            name="deployment_history.lookup",
            version=1,
            display_name="Deployment history lookup",
            description="Reads deterministic local deployment history for a Forge service.",
            risk=ToolRisk.READ_ONLY,
            input_model=DeploymentHistoryInput,
            output_model=DeploymentHistoryOutput,
            timeout_ms=1000,
            retryable=True,
            trust_label=TrustLabel.TRUSTED_LOCAL_FIXTURE,
        ),
        ToolDefinition(
            name="customer_reports.search",
            version=1,
            display_name="Customer reports search",
            description="Reads deterministic local customer reports and labels them untrusted.",
            risk=ToolRisk.READ_ONLY,
            input_model=CustomerReportsInput,
            output_model=CustomerReportsOutput,
            timeout_ms=1000,
            retryable=True,
            trust_label=TrustLabel.UNTRUSTED_TOOL_OUTPUT,
        ),
        ToolDefinition(
            name="ticket.create_simulated",
            version=1,
            display_name="Simulated ticket creation",
            description=(
                "Records a local dry-run ticket effect without contacting an external service."
            ),
            risk=ToolRisk.SIMULATED_EFFECT,
            input_model=SimulatedTicketInput,
            output_model=SimulatedTicketOutput,
            timeout_ms=1000,
            retryable=False,
            trust_label=TrustLabel.TRUSTED_LOCAL_FIXTURE,
        ),
    )


def tool_by_name_version(tool_name: str, version: int) -> ToolDefinition | None:
    return next(
        (
            tool
            for tool in registered_tools()
            if tool.name == tool_name and tool.version == version
        ),
        None,
    )
