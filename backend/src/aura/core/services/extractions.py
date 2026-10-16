"""Extractions from documents, and the gate on feeding them into a valuation (PRD F5.5).

An extraction is stored with feeds_valuation False. Only a person verifying it flips the
flag; the database also refuses an unverified low-confidence row that claims to feed
valuation."""
from datetime import datetime


from aura.core.clock import utcnow
from aura.core.domain.audit import AuditEntry
from aura.core.domain.document import Document
from aura.core.domain.enums import Role
from aura.core.domain.errors import Conflict, NotFound, RuleViolation
from aura.core.domain.extraction import Extraction, ExtractionProposal
from aura.core.policy.rbac_policy import Capability, require
from aura.core.ports.repositories import (AuditRepository, DealRepository,
                                          DocumentRepository, ExtractionRepository)


def record_extraction(proposal: ExtractionProposal, document: Document, actor: str,
                      job_id: int | None, extractions: ExtractionRepository,
                      audit: AuditRepository, now: datetime | None = None) -> Extraction:
    """Store what an agent read from a document. It never feeds valuation on its own."""
    now = now or utcnow()
    if not 0 <= proposal.confidence <= 1:
        raise RuleViolation("extraction confidence must be between 0 and 1")
    saved = extractions.add(Extraction(
        id=None, document_id=document.id, version=document.current_version,
        schema_name=proposal.schema_name, payload=proposal.payload,
        confidence=proposal.confidence, feeds_valuation=False, human_verified_by=None,
        human_verified_at=None, model_run_id=proposal.model_run_id, created_at=now))
    audit.append(AuditEntry(id=None, job_id=job_id, deal_id=document.deal_id, actor=actor,
                            action="extraction_created", created_at=now,
                            payload={"extraction_id": saved.id, "document_id": document.id,
                                     "confidence": proposal.confidence}))
    return saved


def apply_verification(extraction: Extraction, actor: str, deal_id: int | None,
                       extractions: ExtractionRepository, audit: AuditRepository,
                       now: datetime) -> Extraction:
    """Mark the extraction human-verified and let it feed valuation."""
    extraction.human_verified_by, extraction.human_verified_at = actor, now
    extraction.feeds_valuation = True
    saved = extractions.update(extraction)
    audit.append(AuditEntry(id=None, job_id=None, deal_id=deal_id, actor=actor,
                            action="extraction_verified", created_at=now,
                            payload={"extraction_id": saved.id,
                                     "document_id": saved.document_id}))
    return saved


def verify_extraction(extraction_id: int, actor: str, actor_role: Role,
                      extractions: ExtractionRepository, documents: DocumentRepository,
                      audit: AuditRepository, now: datetime | None = None) -> Extraction:
    """A person vouches for the extraction: it may now feed a valuation."""
    require(actor_role, Capability.VERIFY_EXTRACTION, "verify an extraction")
    extraction = extractions.get(extraction_id)
    if extraction is None:
        raise NotFound("Extraction not found")
    document = documents.get(extraction.document_id)
    if document is None:
        raise NotFound("Extraction not found")
    if extraction.human_verified_by is not None:
        raise Conflict(f"Extraction {extraction_id} is already verified")
    return apply_verification(extraction, actor, document.deal_id, extractions, audit,
                              now or utcnow())


def list_extractions(deal_id: int, deals: DealRepository,
                     extractions: ExtractionRepository) -> list[Extraction]:
    if deals.get(deal_id) is None:
        raise NotFound("Deal not found")
    return extractions.list_for_deal(deal_id)
