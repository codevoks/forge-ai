from dataclasses import dataclass
from enum import StrEnum


class Role(StrEnum):
    TENANT_ADMIN = "tenant_admin"
    WORKSPACE_ADMIN = "workspace_admin"
    OPERATOR = "operator"
    APPROVER = "approver"
    VIEWER = "viewer"


class Capability(StrEnum):
    TENANT_ADMIN = "tenant.admin"
    WORKSPACE_ADMIN = "workspace.admin"
    WORKSPACE_READ = "workspace.read"
    WORKFLOW_PUBLISH = "workflow.publish"
    MEMBER_MANAGE = "member.manage"
    RUN_READ = "run.read"
    RUN_CREATE = "run.create"
    RUN_RECOVER = "run.recover"


ROLE_CAPABILITIES: dict[Role, set[Capability]] = {
    Role.TENANT_ADMIN: {
        Capability.TENANT_ADMIN,
        Capability.WORKSPACE_ADMIN,
        Capability.WORKSPACE_READ,
        Capability.WORKFLOW_PUBLISH,
        Capability.MEMBER_MANAGE,
        Capability.RUN_READ,
        Capability.RUN_CREATE,
        Capability.RUN_RECOVER,
    },
    Role.WORKSPACE_ADMIN: {
        Capability.WORKSPACE_ADMIN,
        Capability.WORKSPACE_READ,
        Capability.WORKFLOW_PUBLISH,
        Capability.MEMBER_MANAGE,
        Capability.RUN_READ,
        Capability.RUN_CREATE,
        Capability.RUN_RECOVER,
    },
    Role.OPERATOR: {
        Capability.WORKSPACE_READ,
        Capability.RUN_READ,
        Capability.RUN_CREATE,
        Capability.RUN_RECOVER,
    },
    Role.APPROVER: {
        Capability.WORKSPACE_READ,
        Capability.RUN_READ,
    },
    Role.VIEWER: {
        Capability.WORKSPACE_READ,
        Capability.RUN_READ,
    },
}


@dataclass(frozen=True)
class ActorContext:
    user_id: str
    external_subject: str
    email: str
    display_name: str
    tenant_ids: frozenset[str]
    workspace_roles: dict[str, Role]

    def role_for_workspace(self, workspace_id: str) -> Role | None:
        return self.workspace_roles.get(workspace_id)
