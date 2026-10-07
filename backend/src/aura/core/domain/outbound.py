"""Outbound email: party contacts, the suppression list and outbound messages (migration
0013). Nothing here sends anything; see aura.core.services.outbound."""
from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class OutboundMode(str, Enum):
    OFF = "off"                  # nothing leaves Aura (default)
    GMAIL_DRAFT = "gmail_draft"  # an approved email becomes a draft in the connected Gmail
    GMAIL_SEND = "gmail_send"    # an approved email is sent from the connected Gmail


class OutboundStatus(str, Enum):
    QUEUED = "queued"
    DRAFTED = "drafted"
    SENT = "sent"
    BLOCKED = "blocked"
    FAILED = "failed"


class SuppressionKind(str, Enum):
    EMAIL = "email"
    DOMAIN = "domain"


# Why an approved email did not go out. Stable codes: the UI and metrics key on them.
class BlockReason(str, Enum):
    NO_EXPLICIT_APPROVAL = "no_explicit_approval"
    OUTBOUND_OFF = "outbound_off"
    GMAIL_NOT_CONNECTED = "gmail_not_connected"
    GMAIL_RECONNECT_NEEDED = "gmail_reconnect_needed"
    NO_VERIFIED_EMAIL = "no_verified_email"
    RECIPIENT_CHANGED = "recipient_changed"
    SUPPRESSED = "suppressed"
    APPROVER_NOT_ON_WALL = "approver_not_on_wall"
    DAILY_LIMIT_REACHED = "daily_limit_reached"
    REFUSED_BY_SERVER = "refused_by_server"


@dataclass
class PartyContact:
    id: int | None
    party_id: int
    name: str
    email: str
    is_primary: bool
    created_by: str
    created_at: datetime
    verified_at: datetime | None = None
    verified_by: str | None = None


@dataclass
class Suppression:
    id: int | None
    kind: SuppressionKind
    value: str
    reason: str
    created_by: str
    created_at: datetime


@dataclass
class OutboundMessage:
    id: int | None
    handoff_id: int
    job_id: int | None
    deal_id: int | None
    party_id: int | None
    to_email: str
    subject: str
    mode: OutboundMode
    status: OutboundStatus
    created_at: datetime
    gmail_id: str | None = None
    gmail_thread_id: str | None = None
    error: str | None = None
    completed_at: datetime | None = None
    trace_id: str | None = None


@dataclass
class MailerStatus:
    """What the outbound mailer knows about its Gmail connection. Never carries a token."""
    connected: bool
    account_email: str | None = None
    scopes: tuple[str, ...] = ()
    expires_at: datetime | None = None
    needs_reconnect: bool = False
    storage: str | None = None   # keyring | encrypted_file
    detail: str | None = None


@dataclass
class MailResult:
    """The MCP server's answer: ok with Gmail ids, or refused/failed with a reason."""
    status: str                  # drafted | sent | refused | failed
    gmail_id: str | None = None
    gmail_thread_id: str | None = None
    reason: str | None = None
