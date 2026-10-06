"""Who an MCP tool call is acting for. Deal walls bind agents too: a tool sees only the deals
the acting user's wall memberships allow, and with no acting user it sees nothing."""
import os
from contextlib import contextmanager
from contextvars import ContextVar

_acting_user: ContextVar[str | None] = ContextVar("aura_acting_user", default=None)


def acting_username() -> str:
    """The acting user, from the running job or (for a standalone stdio server) the
    AURA_MCP_USER environment variable. Empty means nobody, which matches no wall."""
    return _acting_user.get() or os.environ.get("AURA_MCP_USER", "")


@contextmanager
def acting_as(username: str | None):
    token = _acting_user.set(username)
    try:
        yield
    finally:
        _acting_user.reset(token)
