from fastapi import APIRouter, Depends, status

from aura.api.deps import current_user, get_audit, get_users
from aura.api.schemas.deals import CreateUserRequest, UpdateUserRequest, UserOut
from aura.api.security import hash_password
from aura.core.domain.user import User
from aura.core.services import users as user_service

router = APIRouter(prefix="/api/users", tags=["users"])


def _out(u: User) -> UserOut:
    return UserOut(id=u.id, username=u.username, role=u.role.value, active=u.active)


@router.get("", response_model=list[UserOut])
def list_users(user: User = Depends(current_user), users=Depends(get_users)):
    return [_out(u) for u in user_service.list_users(user.role, users)]


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(body: CreateUserRequest, user: User = Depends(current_user),
                users=Depends(get_users), audit=Depends(get_audit)):
    created = user_service.create_user(body.username, body.password, body.role,
                                       user.username, user.role, users, audit, hash_password)
    return _out(created)


@router.patch("/{user_id}", response_model=UserOut)
def update_user(user_id: int, body: UpdateUserRequest, user: User = Depends(current_user),
                users=Depends(get_users), audit=Depends(get_audit)):
    return _out(user_service.update_user(user_id, body.role, body.active, user.username,
                                         user.role, users, audit))
