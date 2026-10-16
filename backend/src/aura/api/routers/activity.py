from fastapi import APIRouter, Depends

from aura.api.deps import current_user, get_plain_audit
from aura.api.schemas.dto import AuditResponse
from aura.core.domain.user import User

router = APIRouter(prefix="/api/activity", tags=["activity"])


def audit_out(e) -> AuditResponse:
    return AuditResponse(id=e.id, job_id=e.job_id, deal_id=e.deal_id, actor=e.actor,
                         action=e.action, payload=e.payload, created_at=e.created_at,
                         prev_hash=e.prev_hash, row_hash=e.row_hash)


@router.get("", response_model=list[AuditResponse])
def list_activity(user: User = Depends(current_user), audit=Depends(get_plain_audit)):
    return [audit_out(e) for e in audit.list_recent()]
