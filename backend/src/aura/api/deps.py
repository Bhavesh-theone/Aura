from typing import Generator

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from aura.api.security import decode_token
from aura.api.ws.hub import hub
from aura.core.domain.enums import Role
from aura.core.domain.user import User
from aura.data.engine import SessionLocal
from aura.data.repositories.sql import (SqlApprovalRepository, SqlAuditRepository,
                                        SqlJobRepository, SqlSegmentRepository,
                                        SqlUserRepository)

bearer = HTTPBearer(auto_error=False)


def get_session() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def get_jobs(s: Session = Depends(get_session)) -> SqlJobRepository:
    return SqlJobRepository(s)


def get_segments(s: Session = Depends(get_session)) -> SqlSegmentRepository:
    return SqlSegmentRepository(s)


def get_approvals(s: Session = Depends(get_session)) -> SqlApprovalRepository:
    return SqlApprovalRepository(s)


def get_audit(s: Session = Depends(get_session)) -> SqlAuditRepository:
    return SqlAuditRepository(s)


def get_users(s: Session = Depends(get_session)) -> SqlUserRepository:
    return SqlUserRepository(s)


def get_events():
    return hub


def current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    users: SqlUserRepository = Depends(get_users),
) -> User:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    claims = decode_token(creds.credentials)
    if claims is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token")
    user = users.get(int(claims["sub"]))
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unknown user")
    return user


def require_admin(user: User = Depends(current_user)) -> User:
    if user.role is not Role.ADMIN:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin role required")
    return user
