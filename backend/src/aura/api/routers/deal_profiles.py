"""Deal profile JSON Schemas (draft 2020-12), one per transaction class, for the portal to
render class-specific deal-terms forms from."""
from fastapi import APIRouter, Depends

from aura.api.deps import current_user
from aura.core.domain.user import User
from aura.core.services.deal_profile import get_schema, list_schemas

router = APIRouter(prefix="/api/deal-profiles", tags=["deal-profiles"])


@router.get("/schemas", response_model=dict[str, dict])
def schemas(user: User = Depends(current_user)):
    """Current schema of every transaction class, keyed by class (DEBT, EQUITY, ...)."""
    return list_schemas()


@router.get("/schemas/{transaction_class}", response_model=dict)
def schema(transaction_class: str, user: User = Depends(current_user)):
    """Current schema of one class; 404 for an unknown class."""
    return get_schema(transaction_class.upper())
