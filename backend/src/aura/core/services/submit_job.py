


from aura.core.clock import utcnow
from aura.core.domain.audit import AuditEntry
from aura.core.domain.enums import JobStatus, Role, SegmentStatus
from aura.core.domain.errors import NotFound, RuleViolation
from aura.core.domain.job import Job
from aura.core.domain.segment import Segment
from aura.core.policy.rbac_policy import Capability, require
from aura.core.ports.events import EventPublisher
from aura.core.ports.repositories import (AuditRepository, DealRepository,
                                          DocumentRepository, FileStore, JobRepository,
                                          PartyRepository, SegmentRepository)

CAPABILITIES = frozenset({"classify_document", "draft_email", "extract_financials"})
EXCERPT_CHARS = 2000


def _enrich(capability: str, inputs: dict, deal, documents: DocumentRepository | None,
            parties: PartyRepository | None, store: FileStore | None) -> dict:
    """Load what the agent needs into the segment context, so the orchestrator never
    reaches into the database itself."""
    if deal is None:
        raise RuleViolation(f"{capability} needs a deal_id")
    context = {"deal": {"id": deal.id, "external_id": deal.external_id, "name": deal.name,
                        "stage": deal.stage.value}}
    if capability in ("classify_document", "extract_financials"):
        doc_id = inputs.get("document_id")
        doc = documents.get(doc_id) if isinstance(doc_id, int) and documents else None
        if doc is None or doc.deal_id != deal.id:
            raise NotFound("Document not found on this deal")
        excerpt = store.read_head(doc.sha256, EXCERPT_CHARS) if store else ""
        context["document"] = {"id": doc.id, "filename": doc.filename,
                               "current_class": doc.doc_class.value, "excerpt": excerpt,
                               "version": doc.current_version}
    else:
        party_id = inputs.get("party_id")
        link = next((p for p in (parties.list_for_deal(deal.id) if parties else [])
                     if p.party_id == party_id), None)
        if link is None:
            raise NotFound("Party is not on this deal")
        context["party"] = {"id": link.party_id, "display_name": link.display_name,
                            "role": link.role.value}
    return context


def submit_job(
    inputs: dict,
    deal_id: int | None,
    actor: str,
    actor_role: Role,
    jobs: JobRepository,
    segments: SegmentRepository,
    audit: AuditRepository,
    events: EventPublisher,
    deals: DealRepository,
    documents: DocumentRepository | None = None,
    parties: PartyRepository | None = None,
    store: FileStore | None = None,
) -> Job:
    """Create a job and queue its first segment. Returns immediately - no inference here.

    A job on a deal needs that deal to be visible to the submitter. A job with a
    `capability` input (classify_document, draft_email) gets its subject loaded into the
    segment context here.
    """
    require(actor_role, Capability.SUBMIT_JOB, "run agent jobs")
    now = utcnow()
    deal = None
    if deal_id is not None:
        deal = deals.get(deal_id)
        if deal is None:
            raise NotFound("Deal not found")

    context = dict(inputs)
    capability = inputs.get("capability")
    if capability is not None:
        if capability not in CAPABILITIES:
            raise RuleViolation(f"Unknown capability {capability!r}")
        context.update(_enrich(capability, inputs, deal, documents, parties, store))

    job = jobs.add(Job(id=None, status=JobStatus.PENDING, inputs=inputs,
                       deal_id=deal_id, result=None, created_at=now, created_by=actor))

    segments.add(Segment(id=None, job_id=job.id, seq=1, status=SegmentStatus.QUEUED,
                         context_in=context, context_out=None,
                         started_at=None, ended_at=None))

    audit.append(AuditEntry(id=None, job_id=job.id, deal_id=deal_id, actor=actor,
                            action="job_submitted",
                            payload={"inputs": inputs, "deal_id": deal_id}, created_at=now))

    events.publish("job_submitted", {"job_id": job.id, "deal_id": deal_id})
    return job
