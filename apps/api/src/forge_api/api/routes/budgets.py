from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends

from forge_api.api.dependencies import get_actor, get_database
from forge_api.api.errors import ProblemError
from forge_api.domain.identity import ActorContext
from forge_api.infrastructure.budget_repositories import (
    BudgetPolicyRepository,
    BudgetUsageRepository,
)
from forge_api.infrastructure.database import Database
from forge_api.infrastructure.workflow_repositories import WorkflowRepository

router = APIRouter(prefix="/v1/budgets", tags=["budgets"])


@router.get("/usage")
def get_workspace_budget_usage(
    workspace_id: str,
    actor: Annotated[ActorContext, Depends(get_actor)],
    database: Annotated[Database, Depends(get_database)],
) -> dict[str, object]:
    with database.transaction(actor_id=actor.user_id) as conn:
        scope = WorkflowRepository(conn).workspace_scope_for_actor(
            actor_id=actor.user_id, workspace_id=workspace_id
        )
        if scope is None:
            raise ProblemError(403, "workspace_forbidden", "The workspace is not accessible.")
        tenant_id = str(scope["tenant_id"])
        policy = BudgetPolicyRepository(conn).get_workspace_policy(
            tenant_id=tenant_id, workspace_id=workspace_id
        )
        usage = BudgetUsageRepository(conn).get_for_actor(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            usage_date=datetime.now(UTC).date(),
        )
    return {"policy": policy, "usage": usage}
