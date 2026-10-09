"""Deal walls in the data layer: every deal-scoped repository filters through here.

A repository is built for a viewer: a username, whose wall memberships decide what it can
see, or SYSTEM for the worker, seeding and other internal callers. There is deliberately no
default, so a repository cannot be built without saying who it acts for. Admins get no
exemption.

Two layers enforce the wall (PRD D1):
1. Row-level security in PostgreSQL. Building a repository binds its viewer to the session
   (`bind_viewer`); every transaction then starts with `SET LOCAL aura.viewer = <username>`
   (aura.data.engine) and the policies on deal-scoped tables only return rows of deals whose
   wall currently lists that user. SYSTEM is the value SYSTEM_VIEWER, which the policies let
   through. Once a session has acted as SYSTEM it stays SYSTEM (the worker mixes SYSTEM and
   user-scoped repositories on one session; narrowing mid-way would hide its own rows). A new
   unit of work starts unbound (`reset_viewer`).
2. The repository filters below (`walled`), kept as defence in depth: a wrong policy or a
   SYSTEM-bound session still cannot widen what a user-scoped repository returns.
"""
from contextlib import contextmanager

from sqlalchemy import or_, select, text
from sqlalchemy.orm import Session

from aura.data.engine import VIEWER_KEY
from aura.data.models.tables import UserRow, WallMemberRow, WallRow

# The aura.viewer value that the RLS policies treat as "every deal". Not a valid username
# (usernames cannot contain ':'), so no user can be named into it.
SYSTEM_VIEWER = ":system"
_SET = text("SELECT set_config('aura.viewer', :v, true)")


class _System:
    def __repr__(self) -> str:
        return "SYSTEM"


SYSTEM = _System()
Viewer = str | _System


def check_viewer(viewer: Viewer) -> Viewer:
    if viewer is SYSTEM or isinstance(viewer, str):
        return viewer
    raise TypeError("repository viewer must be a username or SYSTEM")


def viewer_value(viewer: Viewer) -> str:
    return SYSTEM_VIEWER if viewer is SYSTEM else viewer


def bind_viewer(session: Session, viewer: Viewer) -> Viewer:
    """Validate the viewer and make it the session's RLS viewer (now, if a transaction is
    open, and at the start of every later transaction). SYSTEM, once bound, stays."""
    check_viewer(viewer)
    current = session.info.get(VIEWER_KEY)
    value = viewer_value(viewer)
    if current == SYSTEM_VIEWER or current == value:
        return viewer
    session.info[VIEWER_KEY] = value
    if session.in_transaction():
        session.execute(_SET, {"v": value})
    return viewer


def reset_viewer(session: Session) -> None:
    """Forget the bound viewer (a new unit of work on a reused session)."""
    session.info.pop(VIEWER_KEY, None)
    if session.in_transaction():
        session.execute(_SET, {"v": ""})


@contextmanager
def system_scope(session: Session):
    """Read across every wall for the duration of the block, then drop back to the
    session's own viewer. A savepoint that is always rolled back carries the SET LOCAL, so
    nothing written inside survives either: use it for reads (audit chain verification)."""
    savepoint = session.begin_nested()
    try:
        session.execute(_SET, {"v": SYSTEM_VIEWER})
        yield session
    finally:
        savepoint.rollback()


def member_deal_ids(viewer: str):
    """Subquery: ids of the deals whose wall currently includes this username."""
    return (select(WallRow.deal_id)
            .join(WallMemberRow, WallMemberRow.wall_id == WallRow.id)
            .join(UserRow, UserRow.id == WallMemberRow.user_id)
            .where(UserRow.username == viewer, WallMemberRow.removed_at.is_(None)))


def walled(stmt, viewer: Viewer, deal_col, include_unattached: bool = False):
    """Restrict a select to rows on deals the viewer may see. With include_unattached,
    rows that belong to no deal (deal_id is NULL) stay visible to everyone."""
    if viewer is SYSTEM:
        return stmt
    clause = deal_col.in_(member_deal_ids(viewer))
    if include_unattached:
        clause = or_(deal_col.is_(None), clause)
    return stmt.where(clause)
