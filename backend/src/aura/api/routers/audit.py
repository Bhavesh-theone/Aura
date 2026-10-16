from pathlib import Path

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from aura.api.deps import current_user, get_anchor_path, get_session
from aura.api.schemas.deals import AnchorOut, AuditVerifyOut
from aura.core.domain.user import User
from aura.data.verify_audit import verify

router = APIRouter(prefix="/api/audit", tags=["audit"])


@router.get("/verify", response_model=AuditVerifyOut)
def verify_audit(user: User = Depends(current_user), s: Session = Depends(get_session),
                 anchor_path: Path | None = Depends(get_anchor_path)):
    """Recompute the hash chain and compare its head with the anchor file."""
    result = verify(s, anchor_path)
    a = result.anchor
    return AuditVerifyOut(ok=result.ok, broken_at=result.broken_at,
                          anchor=AnchorOut(head_id=a.head_id, head_hash=a.head_hash,
                                           written_at=a.written_at, ok=a.ok))
