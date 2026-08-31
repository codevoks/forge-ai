from typing import Annotated

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, Field

from forge_api.api.dependencies import get_actor, get_database, require_idempotency_key
from forge_api.api.errors import ProblemError
from forge_api.application.approval_service import ApprovalService
from forge_api.domain.approvals import ApprovalDecisionValue
from forge_api.domain.identity import ActorContext
from forge_api.infrastructure.database import Database

router = APIRouter(prefix="/v1/approvals", tags=["approvals"])


class ApprovalDecisionRequest(BaseModel):
    reason: str = Field(min_length=2, max_length=500)


def require_if_match(if_match: Annotated[str | None, Header()] = None) -> int:
    if not if_match:
        raise ProblemError(428, "if_match_required", "If-Match version header is required.")
    try:
        version = int(if_match.strip().strip('"'))
    except ValueError as exc:
        raise ProblemError(400, "if_match_invalid", "If-Match must be a resource version.") from exc
    if version < 1:
        raise ProblemError(400, "if_match_invalid", "If-Match must be a positive version.")
    return version


@router.get("")
def list_approvals(
    actor: Annotated[ActorContext, Depends(get_actor)],
    database: Annotated[Database, Depends(get_database)],
) -> dict[str, object]:
    return {"approval_requests": ApprovalService(database).list_approvals(actor)}


@router.post("/{approval_request_id}:approve")
def approve(
    approval_request_id: str,
    payload: ApprovalDecisionRequest,
    actor: Annotated[ActorContext, Depends(get_actor)],
    database: Annotated[Database, Depends(get_database)],
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
    expected_version: Annotated[int, Depends(require_if_match)],
) -> dict[str, object]:
    return ApprovalService(database).decide(
        actor,
        approval_request_id,
        decision=ApprovalDecisionValue.APPROVED,
        reason=payload.reason,
        expected_version=expected_version,
        idempotency_key=idempotency_key,
    )


@router.post("/{approval_request_id}:reject")
def reject(
    approval_request_id: str,
    payload: ApprovalDecisionRequest,
    actor: Annotated[ActorContext, Depends(get_actor)],
    database: Annotated[Database, Depends(get_database)],
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
    expected_version: Annotated[int, Depends(require_if_match)],
) -> dict[str, object]:
    return ApprovalService(database).decide(
        actor,
        approval_request_id,
        decision=ApprovalDecisionValue.REJECTED,
        reason=payload.reason,
        expected_version=expected_version,
        idempotency_key=idempotency_key,
    )


@router.post(":expire")
def expire_pending(
    actor: Annotated[ActorContext, Depends(get_actor)],
    database: Annotated[Database, Depends(get_database)],
) -> dict[str, object]:
    return {"approvals": ApprovalService(database).expire_pending(actor)}
