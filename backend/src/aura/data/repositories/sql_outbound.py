"""Party contacts, the suppression list and outbound messages (migration 0013).

Contacts and suppression entries are firm-wide, like parties. Outbound messages belong to a
deal and are wall-filtered for the viewer."""
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from aura.core.domain.errors import Conflict
from aura.core.domain.outbound import (OutboundMessage, OutboundMode, OutboundStatus,
                                       PartyContact, Suppression, SuppressionKind)
from aura.core.policy.email_policy import domain_of
from aura.data.models.tables import OutboundMessageRow, PartyContactRow, SuppressionRow
from aura.data.walls import Viewer, check_viewer, walled


def _contact(row: PartyContactRow) -> PartyContact:
    return PartyContact(id=row.id, party_id=row.party_id, name=row.name or "",
                        email=row.email, is_primary=bool(row.is_primary),
                        created_by=row.created_by, created_at=row.created_at,
                        verified_at=row.verified_at, verified_by=row.verified_by)


def _suppression(row: SuppressionRow) -> Suppression:
    return Suppression(id=row.id, kind=SuppressionKind(row.kind), value=row.value,
                       reason=row.reason or "", created_by=row.created_by,
                       created_at=row.created_at)


def _message(row: OutboundMessageRow) -> OutboundMessage:
    return OutboundMessage(id=row.id, handoff_id=row.handoff_id, job_id=row.job_id,
                           deal_id=row.deal_id, party_id=row.party_id, to_email=row.to_email,
                           subject=row.subject or "", mode=OutboundMode(row.mode),
                           status=OutboundStatus(row.status), created_at=row.created_at,
                           gmail_id=row.gmail_id, gmail_thread_id=row.gmail_thread_id,
                           error=row.error, completed_at=row.completed_at,
                           trace_id=row.trace_id)


def _insert(session: Session, row, conflict: str):
    """Insert in a savepoint, so a unique-key clash is a Conflict and not a lost transaction."""
    try:
        with session.begin_nested():
            session.add(row)
            session.flush()
    except IntegrityError:
        raise Conflict(conflict) from None
    return row


class SqlContactRepository:
    def __init__(self, session: Session):
        self.s = session

    def add(self, contact: PartyContact) -> PartyContact:
        row = _insert(self.s, PartyContactRow(
            party_id=contact.party_id, name=contact.name, email=contact.email,
            is_primary=contact.is_primary, verified_at=contact.verified_at,
            verified_by=contact.verified_by, created_by=contact.created_by,
            created_at=contact.created_at), "This party already has that email")
        return _contact(row)

    def get(self, contact_id: int) -> PartyContact | None:
        row = self.s.get(PartyContactRow, contact_id)
        return _contact(row) if row else None

    def update(self, contact: PartyContact) -> PartyContact:
        row = self.s.get(PartyContactRow, contact.id)
        row.name, row.is_primary = contact.name, contact.is_primary
        row.verified_at, row.verified_by = contact.verified_at, contact.verified_by
        self.s.flush()
        return _contact(row)

    def delete(self, contact_id: int) -> None:
        row = self.s.get(PartyContactRow, contact_id)
        if row is not None:
            self.s.delete(row)
            self.s.flush()

    def list_for_party(self, party_id: int) -> list[PartyContact]:
        rows = self.s.scalars(select(PartyContactRow).where(PartyContactRow.party_id == party_id)
                              .order_by(PartyContactRow.id))
        return [_contact(r) for r in rows]


class SqlSuppressionRepository:
    def __init__(self, session: Session):
        self.s = session

    def add(self, entry: Suppression) -> Suppression:
        row = _insert(self.s, SuppressionRow(kind=entry.kind.value, value=entry.value,
                                             reason=entry.reason, created_by=entry.created_by,
                                             created_at=entry.created_at),
                      f"{entry.value} is already on the suppression list")
        return _suppression(row)

    def get(self, suppression_id: int) -> Suppression | None:
        row = self.s.get(SuppressionRow, suppression_id)
        return _suppression(row) if row else None

    def delete(self, suppression_id: int) -> None:
        row = self.s.get(SuppressionRow, suppression_id)
        if row is not None:
            self.s.delete(row)
            self.s.flush()

    def list_all(self) -> list[Suppression]:
        return [_suppression(r) for r in self.s.scalars(select(SuppressionRow)
                                                        .order_by(SuppressionRow.id))]

    def matches(self, email: str) -> Suppression | None:
        email = (email or "").strip().lower()
        domain = domain_of(email)
        row = self.s.scalars(select(SuppressionRow).where(
            ((SuppressionRow.kind == "email") & (SuppressionRow.value == email))
            | ((SuppressionRow.kind == "domain") & (SuppressionRow.value == domain)))
            .order_by(SuppressionRow.id)).first()
        return _suppression(row) if row else None


class SqlOutboundRepository:
    def __init__(self, session: Session, viewer: Viewer):
        self.s, self.viewer = session, check_viewer(viewer)

    def add(self, message: OutboundMessage) -> OutboundMessage:
        row = _insert(self.s, OutboundMessageRow(
            handoff_id=message.handoff_id, job_id=message.job_id, deal_id=message.deal_id,
            party_id=message.party_id, to_email=message.to_email, subject=message.subject,
            mode=message.mode.value, status=message.status.value, gmail_id=message.gmail_id,
            gmail_thread_id=message.gmail_thread_id, error=message.error,
            created_at=message.created_at, completed_at=message.completed_at,
            trace_id=message.trace_id), "This approval already has an outbound message")
        return _message(row)

    def update(self, message: OutboundMessage) -> OutboundMessage:
        row = self.s.get(OutboundMessageRow, message.id)
        row.status, row.gmail_id = message.status.value, message.gmail_id
        row.gmail_thread_id, row.error = message.gmail_thread_id, message.error
        row.completed_at = message.completed_at
        self.s.flush()
        return _message(row)

    def get_for_handoff(self, handoff_id: int) -> OutboundMessage | None:
        stmt = walled(select(OutboundMessageRow).where(OutboundMessageRow.handoff_id
                                                       == handoff_id),
                      self.viewer, OutboundMessageRow.deal_id, include_unattached=True)
        row = self.s.scalars(stmt).first()
        return _message(row) if row else None

    def list_all(self, handoff_id: int | None = None,
                 limit: int = 200) -> list[OutboundMessage]:
        stmt = select(OutboundMessageRow)
        if handoff_id is not None:
            stmt = stmt.where(OutboundMessageRow.handoff_id == handoff_id)
        stmt = walled(stmt, self.viewer, OutboundMessageRow.deal_id, include_unattached=True)
        rows = self.s.scalars(stmt.order_by(OutboundMessageRow.id.desc()).limit(limit))
        return [_message(r) for r in rows]

    def count_since(self, since: datetime) -> int:
        """Across all deals (the cap is firm-wide), whatever the viewer."""
        return self.s.scalar(select(func.count(OutboundMessageRow.id)).where(
            OutboundMessageRow.created_at >= since,
            OutboundMessageRow.status != OutboundStatus.BLOCKED.value)) or 0
