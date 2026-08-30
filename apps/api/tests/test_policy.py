from forge_api.domain.identity import ActorContext, Capability, Role
from forge_api.policy.authorization import AuthorizationService


def test_viewer_cannot_admin_workspace() -> None:
    actor = ActorContext(
        user_id="user-1",
        external_subject="oidc|viewer",
        email="viewer@forge.local",
        display_name="Viewer",
        tenant_ids=frozenset({"tenant-1"}),
        workspace_roles={"workspace-1": Role.VIEWER},
    )

    decision = AuthorizationService().decide_workspace(
        actor, "workspace-1", Capability.MEMBER_MANAGE
    )

    assert decision.allowed is False
    assert decision.reason == "capability_required"


def test_tenant_admin_has_member_management_capability() -> None:
    actor = ActorContext(
        user_id="user-1",
        external_subject="oidc|admin",
        email="admin@forge.local",
        display_name="Admin",
        tenant_ids=frozenset({"tenant-1"}),
        workspace_roles={"workspace-1": Role.TENANT_ADMIN},
    )

    decision = AuthorizationService().decide_workspace(
        actor, "workspace-1", Capability.MEMBER_MANAGE
    )

    assert decision.allowed is True
