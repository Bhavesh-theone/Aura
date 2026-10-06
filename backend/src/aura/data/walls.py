"""Deal walls in the data layer: every deal-scoped repository filters through here.

A repository is built for a viewer: a username, whose wall memberships decide what it can
see, or SYSTEM for the worker, seeding and other internal callers. There is deliberately no
default, so a repository cannot be built without saying who it acts for. Admins get no
exemption.
"""
from sqlalchemy import or_, select

from aura.data.models.tables import UserRow, WallMemberRow, WallRow


class _System:
    def __repr__(self) -> str:
        return "SYSTEM"


SYSTEM = _System()
Viewer = str | _System


def check_viewer(viewer: Viewer) -> Viewer:
    if viewer is SYSTEM or isinstance(viewer, str):
        return viewer
    raise TypeError("repository viewer must be a username or SYSTEM")


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
