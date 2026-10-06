"""Which audited actions change something a screen shows, and what kind of thing it is.
A client that hears `entity_changed {kind, deal_id}` refetches that kind for that deal."""

ENTITY_KINDS = ("deal", "document", "diligence", "condition", "handoff", "job", "finding",
                "extraction", "signoff")

_KIND_FOR_ACTION: dict[str, str] = {
    "deal_created": "deal", "deal_transition": "deal", "deal_transition_blocked": "deal",
    "deal_flags_updated": "deal", "wall_member_added": "deal", "wall_member_removed": "deal",
    "party_linked": "deal", "mandate_created": "deal",
    "deal_signoff": "signoff",
    "document_uploaded": "document", "document_updated": "document",
    "diligence_updated": "diligence",
    "condition_created": "condition", "condition_updated": "condition",
    "finding_created": "finding",
    "extraction_created": "extraction", "extraction_verified": "extraction",
    "handoff_created": "handoff", "handoff_resolved": "handoff",
    "handoff_escalated": "handoff", "handoff_skipped_per_directive": "handoff",
    "job_submitted": "job", "job_completed": "job", "segment_failed": "job",
}


def entity_kind_for(action: str) -> str | None:
    """The entity kind an audited action changed, or None (reads, user admin, rejections)."""
    return _KIND_FOR_ACTION.get(action)
