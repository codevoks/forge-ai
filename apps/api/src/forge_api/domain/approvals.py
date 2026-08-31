import hashlib
import ipaddress
import json
from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import urlparse

from forge_api.api.errors import ProblemError

APPROVAL_TTL_MINUTES = 30
MAX_PENDING_APPROVALS_PER_RUN = 10


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    CONSUMED = "consumed"


class ApprovalDecisionValue(StrEnum):
    APPROVED = "approved"
    REJECTED = "rejected"


@dataclass(frozen=True)
class ApprovalRequirement:
    required: bool
    reason: str


class ApprovalPolicy:
    def requirement(self, *, risk: str) -> ApprovalRequirement:
        if risk == "simulated_effect":
            return ApprovalRequirement(True, "simulated_effect_requires_human_approval")
        return ApprovalRequirement(False, "low_risk_auto_authorized")


class ApprovalRequiredError(Exception):
    def __init__(self, approval_request_id: str) -> None:
        super().__init__("approval required")
        self.approval_request_id = approval_request_id


def approval_binding_hash(
    *,
    tenant_id: str,
    workspace_id: str,
    run_id: str,
    task_id: str,
    tool_invocation_id: str,
    tool_version_id: str,
    action_hash: str,
    canonical_arguments: dict[str, object],
) -> str:
    payload = {
        "tenant_id": tenant_id,
        "workspace_id": workspace_id,
        "run_id": run_id,
        "task_id": task_id,
        "tool_invocation_id": tool_invocation_id,
        "tool_version_id": tool_version_id,
        "action_hash": action_hash,
        "canonical_arguments": canonical_arguments,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class NetworkPolicy:
    def validate_url(self, url: str) -> str:
        parsed = urlparse(url)
        if parsed.scheme not in {"https"}:
            raise ProblemError(422, "network_scheme_denied", "Only https URLs are allowed.")
        if not parsed.hostname:
            raise ProblemError(422, "network_host_required", "URL host is required.")
        hostname = parsed.hostname.strip().lower()
        if hostname in {"localhost"} or hostname.endswith(".localhost"):
            raise ProblemError(422, "network_private_host_denied", "Private hosts are denied.")
        try:
            ip = ipaddress.ip_address(hostname)
        except ValueError:
            return url
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            raise ProblemError(
                422,
                "network_private_address_denied",
                "Private network addresses are denied.",
            )
        return url


class FakeSecretResolver:
    def resolve_reference(self, reference: str) -> dict[str, str]:
        if not reference.startswith("secretref://"):
            raise ProblemError(422, "secret_reference_invalid", "Secret references must be opaque.")
        return {
            "reference": reference,
            "status": "available",
            "material": "[redacted]",
        }
