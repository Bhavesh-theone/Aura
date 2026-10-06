from pathlib import Path
from typing import Generator

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from aura.api.security import decode_token
from aura.api.ws.hub import hub
from aura.core.domain.enums import Role
from aura.core.domain.user import User
from aura.core.services.notifying_audit import NotifyingAudit
from aura.data.engine import SessionLocal
from aura.data.filestore import LocalFileStore
from aura.data.repositories.sql import (SqlAgentRunRepository, SqlAuditRepository,
                                        SqlHandoffRepository, SqlJobRepository,
                                        SqlSegmentRepository, SqlTaskRepository,
                                        SqlUserRepository)
from aura.data.repositories.sql_deals import (SqlConditionRepository, SqlDealRepository,
                                              SqlDiligenceRepository, SqlDocumentRepository,
                                              SqlExtractionRepository, SqlFindingRepository,
                                              SqlGuardRepository, SqlMandateRepository,
                                              SqlPartyRepository, SqlSignoffRepository,
                                              SqlStageHistoryRepository, SqlWallRepository)
from aura.data.uow import SqlUnitOfWork
from aura.data.verify_audit import default_anchor_path

bearer = HTTPBearer(auto_error=False)


def get_uow() -> Generator[SqlUnitOfWork, None, None]:
    """One unit of work per request: commit when the route returns, roll back when it
    raises. Repositories never commit, so a failure midway leaves no partial writes."""
    session = SessionLocal()
    try:
        with SqlUnitOfWork(session).transaction() as uow:
            yield uow
    finally:
        session.close()


# scope="function": commit (or roll back) as soon as the route returns, before the response
# is sent, so a client never reads back state that is not committed yet.
_uow = Depends(get_uow, scope="function")


def get_session(uow: SqlUnitOfWork = _uow) -> Session:
    return uow.session


def get_events(uow: SqlUnitOfWork = _uow):
    """Events are held until the request's transaction commits."""
    return uow.defer(hub)


def get_users(s: Session = Depends(get_session)) -> SqlUserRepository:
    return SqlUserRepository(s)


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
    if user is None or not user.active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unknown user")
    return user


def require_admin(user: User = Depends(current_user)) -> User:
    """Gate for the user-management routes. Every deal rule is enforced in core services."""
    if user.role is not Role.ADMIN:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin role required")
    return user


# Everything below is built for the requesting user, so deal walls apply in the repository.

def get_jobs(s: Session = Depends(get_session),
             user: User = Depends(current_user)) -> SqlJobRepository:
    return SqlJobRepository(s, user.username)


def get_segments(s: Session = Depends(get_session)) -> SqlSegmentRepository:
    return SqlSegmentRepository(s)


def get_tasks(s: Session = Depends(get_session),
              user: User = Depends(current_user)) -> SqlTaskRepository:
    return SqlTaskRepository(s, user.username)


def get_handoffs(s: Session = Depends(get_session),
                 user: User = Depends(current_user)) -> SqlHandoffRepository:
    return SqlHandoffRepository(s, user.username)


def get_agent_runs(s: Session = Depends(get_session),
                   user: User = Depends(current_user)) -> SqlAgentRunRepository:
    return SqlAgentRunRepository(s, user.username)


def get_audit(s: Session = Depends(get_session), user: User = Depends(current_user),
              events=Depends(get_events)) -> NotifyingAudit:
    """The audit trail; each entry also announces what changed (entity_changed)."""
    return NotifyingAudit(SqlAuditRepository(s, user.username), events)


def get_plain_audit(s: Session = Depends(get_session),
                    user: User = Depends(current_user)) -> SqlAuditRepository:
    """For reads that never write an entry, so they have nothing to announce."""
    return SqlAuditRepository(s, user.username)


def get_deals(s: Session = Depends(get_session),
              user: User = Depends(current_user)) -> SqlDealRepository:
    return SqlDealRepository(s, user.username)


def get_history(s: Session = Depends(get_session),
                user: User = Depends(current_user)) -> SqlStageHistoryRepository:
    return SqlStageHistoryRepository(s, user.username)


def get_guards(s: Session = Depends(get_session)) -> SqlGuardRepository:
    return SqlGuardRepository(s)


def get_parties(s: Session = Depends(get_session),
                user: User = Depends(current_user)) -> SqlPartyRepository:
    return SqlPartyRepository(s, user.username)


def get_mandates(s: Session = Depends(get_session),
                 user: User = Depends(current_user)) -> SqlMandateRepository:
    return SqlMandateRepository(s, user.username)


def get_documents(s: Session = Depends(get_session),
                  user: User = Depends(current_user)) -> SqlDocumentRepository:
    return SqlDocumentRepository(s, user.username)


def get_diligence(s: Session = Depends(get_session),
                  user: User = Depends(current_user)) -> SqlDiligenceRepository:
    return SqlDiligenceRepository(s, user.username)


def get_conditions(s: Session = Depends(get_session),
                   user: User = Depends(current_user)) -> SqlConditionRepository:
    return SqlConditionRepository(s, user.username)


def get_walls(s: Session = Depends(get_session),
              user: User = Depends(current_user)) -> SqlWallRepository:
    return SqlWallRepository(s, user.username)


def get_store() -> LocalFileStore:
    return LocalFileStore()


def get_findings(s: Session = Depends(get_session),
                 user: User = Depends(current_user)) -> SqlFindingRepository:
    return SqlFindingRepository(s, user.username)


def get_extractions(s: Session = Depends(get_session),
                    user: User = Depends(current_user)) -> SqlExtractionRepository:
    return SqlExtractionRepository(s, user.username)


def get_signoffs(s: Session = Depends(get_session),
                 user: User = Depends(current_user)) -> SqlSignoffRepository:
    return SqlSignoffRepository(s, user.username)


def get_anchor_path() -> Path | None:
    """Where the audit anchor lives; tests override this to a temporary file."""
    return default_anchor_path()
