from fastapi import APIRouter, Depends, HTTPException, status

from aura.api.deps import current_user, get_users
from aura.api.schemas.dto import LoginRequest, MeResponse, TokenResponse
from aura.api.security import create_token, verify_password
from aura.core.domain.user import User
from aura.core.services.authenticate import authenticate
from aura.data.repositories.sql import SqlUserRepository

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, users: SqlUserRepository = Depends(get_users)):
    user = authenticate(body.username, body.password, users, verify_password)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")
    return TokenResponse(access_token=create_token(user))


@router.get("/me", response_model=MeResponse)
def me(user: User = Depends(current_user)):
    return MeResponse(id=user.id, username=user.username, role=user.role.value)
