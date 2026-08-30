from dataclasses import dataclass

from forge_api.domain.identity import ROLE_CAPABILITIES, ActorContext, Capability


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    reason: str


class AuthorizationService:
    def decide_workspace(
        self, actor: ActorContext, workspace_id: str, capability: Capability
    ) -> PolicyDecision:
        role = actor.role_for_workspace(workspace_id)
        if role is None:
            return PolicyDecision(False, "membership_required")
        if capability not in ROLE_CAPABILITIES[role]:
            return PolicyDecision(False, "capability_required")
        return PolicyDecision(True, "allowed")

    def decide_tenant(
        self,
        actor: ActorContext,
        tenant_id: str,
        capability: Capability,
    ) -> PolicyDecision:
        if tenant_id not in actor.tenant_ids:
            return PolicyDecision(False, "tenant_membership_required")
        if capability != Capability.TENANT_ADMIN:
            return PolicyDecision(True, "allowed")
        for workspace_id in actor.workspace_roles:
            if actor.workspace_roles[workspace_id].value == "tenant_admin":
                return PolicyDecision(True, "allowed")
        return PolicyDecision(False, "tenant_admin_required")
