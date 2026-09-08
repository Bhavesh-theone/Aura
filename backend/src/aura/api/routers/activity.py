from fastapi import APIRouter, Depends

from aura.api.deps import current_user, get_audit
from aura.api.schemas.dto import AuditResponse
from aura.core.domain.user import User

router = APIRouter(prefix="/api/activity", tags=["activity"])


@router.get("", response_model=list[AuditResponse])
def list_activity(user: User = Depends(current_user), audit=Depends(get_audit)):
    return [AuditResponse(id=e.id, job_id=e.job_id, actor=e.actor, action=e.action,
                          payload=e.payload, created_at=e.created_at)
            for e in audit.list_recent()]
