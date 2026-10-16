


from aura.core.clock import utcnow
from aura.core.domain.audit import AuditEntry
from aura.core.domain.deal import Deal
from aura.core.domain.diligence import ConditionPrecedent, DiligenceItem, Finding
from aura.core.domain.enums import CPStatus, DiligenceStatus, FindingType, Role
from aura.core.domain.errors import NotFound, RuleViolation
from aura.core.policy.rbac_policy import Capability, require
from aura.core.ports.repositories import (AuditRepository, ConditionRepository,
                                          DealRepository, DiligenceRepository,
                                          DocumentRepository, FindingRepository)


def instantiate_checklist(deal: Deal, diligence: DiligenceRepository) -> int:
    """Create the deal's items from templates for its class (or any class).
    Idempotent: a deal that already has items is left alone."""
    if diligence.list_items(deal.id):
        return 0
    templates = diligence.list_templates(deal.transaction_class)
    for t in templates:
        diligence.add_item(DiligenceItem(id=None, deal_id=deal.id, template_id=t.id,
                                         prompt=t.prompt, severity=t.default_severity))
    return len(templates)


def update_diligence_item(
    item_id: int,
    status: DiligenceStatus,
    evidence_doc_ids: list[int] | None,
    waiver_justification: str | None,
    actor: str,
    actor_role: Role,
    diligence: DiligenceRepository,
    documents: DocumentRepository,
    audit: AuditRepository,
) -> DiligenceItem:
    require(actor_role, Capability.EDIT_DEAL_DATA, "edit diligence items")
    item = diligence.get_item(item_id)
    if item is None:
        raise NotFound("Diligence item not found")
    before = item.status
    if evidence_doc_ids is not None:
        for doc_id in evidence_doc_ids:
            doc = documents.get(doc_id)
            if doc is None or doc.deal_id != item.deal_id:
                raise RuleViolation(f"Evidence document {doc_id} is not on this deal")
        item.evidence_doc_ids = list(evidence_doc_ids)
    if waiver_justification is not None:
        item.waiver_justification = waiver_justification
    if status is DiligenceStatus.SATISFIED and not item.evidence_doc_ids:
        raise RuleViolation("Satisfied requires at least one evidence document")
    if status is DiligenceStatus.WAIVED and not (item.waiver_justification or "").strip():
        raise RuleViolation("Waived requires a waiver_justification")
    item.status = status
    saved = diligence.update_item(item)
    audit.append(AuditEntry(id=None, job_id=None, deal_id=item.deal_id, actor=actor,
                            action="diligence_updated", created_at=utcnow(),
                            payload={"item_id": item.id, "from": before.value,
                                     "to": status.value,
                                     "evidence_doc_ids": item.evidence_doc_ids}))
    return saved


def add_condition(deal_id: int, description: str, cp_type: str, actor: str,
                  actor_role: Role, deals: DealRepository, conditions: ConditionRepository,
                  audit: AuditRepository) -> ConditionPrecedent:
    require(actor_role, Capability.EDIT_DEAL_DATA, "edit conditions precedent")
    if deals.get(deal_id) is None:
        raise NotFound("Deal not found")
    cp = conditions.add(ConditionPrecedent(id=None, deal_id=deal_id,
                                           description=description, cp_type=cp_type))
    audit.append(AuditEntry(id=None, job_id=None, deal_id=deal_id, actor=actor,
                            action="condition_created", created_at=utcnow(),
                            payload={"condition_id": cp.id, "cp_type": cp_type}))
    return cp


def update_condition(cp_id: int, status: CPStatus, waiver_justification: str | None,
                     actor: str, actor_role: Role, conditions: ConditionRepository,
                     audit: AuditRepository) -> ConditionPrecedent:
    require(actor_role, Capability.EDIT_DEAL_DATA, "edit conditions precedent")
    cp = conditions.get(cp_id)
    if cp is None:
        raise NotFound("Condition not found")
    before = cp.status
    if waiver_justification is not None:
        cp.waiver_justification = waiver_justification
    if status is CPStatus.WAIVED and not (cp.waiver_justification or "").strip():
        raise RuleViolation("Waived requires a waiver_justification")
    cp.status = status
    saved = conditions.update(cp)
    audit.append(AuditEntry(id=None, job_id=None, deal_id=cp.deal_id, actor=actor,
                            action="condition_updated", created_at=utcnow(),
                            payload={"condition_id": cp.id, "from": before.value,
                                     "to": status.value}))
    return saved


def add_finding(deal_id: int, diligence_item_id: int, finding_type: FindingType,
                description: str, quantified_impact_inr: int | None, affects_valuation: bool,
                actor: str, actor_role: Role, deals: DealRepository,
                diligence: DiligenceRepository, findings: FindingRepository,
                audit: AuditRepository) -> Finding:
    """A finding hangs off a diligence item on this deal. One that moves the valuation must
    say by how much."""
    require(actor_role, Capability.EDIT_DEAL_DATA, "raise findings")
    if deals.get(deal_id) is None:
        raise NotFound("Deal not found")
    item = diligence.get_item(diligence_item_id)
    if item is None or item.deal_id != deal_id:
        raise NotFound("Diligence item not found on this deal")
    if not description.strip():
        raise RuleViolation("A finding needs a description")
    if affects_valuation and quantified_impact_inr is None:
        raise RuleViolation("A finding that affects valuation needs quantified_impact_inr")
    now = utcnow()
    finding = findings.add(Finding(
        id=None, diligence_item_id=diligence_item_id, deal_id=deal_id,
        finding_type=finding_type, description=description,
        quantified_impact_inr=quantified_impact_inr, affects_valuation=affects_valuation,
        raised_by=actor, raised_at=now))
    audit.append(AuditEntry(id=None, job_id=None, deal_id=deal_id, actor=actor,
                            action="finding_created", created_at=now,
                            payload={"finding_id": finding.id, "item_id": diligence_item_id,
                                     "finding_type": finding_type.value,
                                     "affects_valuation": affects_valuation}))
    return finding
