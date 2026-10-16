"""Internal notes on a deal. Written by the deals MCP tool add_internal_note (as the acting
user, behind that user's walls) and listed at GET /api/deals/{id}/notes."""
from aura.core.clock import utcnow
from aura.core.domain.audit import AuditEntry
from aura.core.domain.errors import NotFound, RuleViolation
from aura.core.domain.harness import DealNote
from aura.core.ports.repositories import AuditRepository, DealRepository, NoteRepository

MAX_NOTE_CHARS = 4000


def add_note(external_id: str, body: str, actor: str, source: str, deals: DealRepository,
             notes: NoteRepository, audit: AuditRepository,
             job_id: int | None = None) -> DealNote:
    """`deals` is built for the actor, so a deal behind a wall they are not on is not found."""
    deal = deals.get_by_external_id(external_id)
    if deal is None:
        raise NotFound(f"No deal found with ID {external_id}")
    text = (body or "").strip()
    if not text:
        raise RuleViolation("A note needs text")
    now = utcnow()
    note = notes.add(DealNote(id=None, deal_id=deal.id, body=text[:MAX_NOTE_CHARS],
                              author=actor or "unknown", source=source, created_at=now,
                              job_id=job_id))
    audit.append(AuditEntry(id=None, job_id=job_id, deal_id=deal.id, actor=actor or "unknown",
                            action="note_added", created_at=now,
                            payload={"note_id": note.id, "source": source,
                                     "chars": len(note.body)}))
    return note


def list_notes(deal_id: int, deals: DealRepository, notes: NoteRepository) -> list[DealNote]:
    if deals.get(deal_id) is None:
        raise NotFound("Deal not found")
    return notes.list_for_deal(deal_id)
