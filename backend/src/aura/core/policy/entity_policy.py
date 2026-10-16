"""Which audited actions change something a screen shows, and what kind of thing it is.
A client that hears `entity_changed {kind, deal_id}` refetches that kind for that deal."""

ENTITY_KINDS = ("deal", "document", "diligence", "condition", "handoff", "job", "finding",
                "extraction", "signoff", "intake")

_KIND_FOR_ACTION: dict[str, str] = {
    "deal_created": "deal", "deal_transition": "deal", "deal_transition_blocked": "deal",
    "deal_flags_updated": "deal", "wall_member_added": "deal", "wall_member_removed": "deal",
    "party_linked": "deal", "mandate_created": "deal",
    "deal_signoff": "signoff",
    "document_uploaded": "document", "document_updated": "document",
    "document_indexed": "document", "document_index_failed": "document",
    "document_reindex_requested": "document",
    "diligence_updated": "diligence",
    "condition_created": "condition", "condition_updated": "condition",
    "finding_created": "finding",
    "extraction_created": "extraction", "extraction_verified": "extraction",
    "handoff_created": "handoff", "handoff_resolved": "handoff",
    "handoff_escalated": "handoff", "handoff_skipped_per_directive": "handoff",
    "job_submitted": "job", "job_completed": "job", "segment_failed": "job",
    "segment_retry_scheduled": "job", "segment_dead_lettered": "job",
    "segment_recovered": "job", "segment_retried": "job", "budget_deferred": "job",
    "orchestrator_fallback": "job",
    # Deal intake (phase 3): heard only by the intake's creator (payload 'recipient').
    "intake_created": "intake", "intake_file_staged": "intake", "intake_file_removed": "intake",
    "intake_file_indexed": "intake", "intake_file_index_failed": "intake",
    "intake_extraction_requested": "intake", "intake_extracted": "intake",
    "intake_extraction_failed": "intake", "intake_updated": "intake",
    "intake_discarded": "intake",
    # Confirming creates the deal: the deal list changes for everyone on the new wall.
    "intake_confirmed": "deal",
}



def entity_kind_for(action: str) -> str | None:
    """The entity kind an audited action changed, or None (reads, user admin, rejections)."""
    return _KIND_FOR_ACTION.get(action)
