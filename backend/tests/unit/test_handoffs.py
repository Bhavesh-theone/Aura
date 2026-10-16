import copy
from datetime import datetime, timedelta, timezone

import pytest

from aura.core.domain.document import Document
from aura.core.domain.enums import (ActionCategory, AssignmentMode, DocClass,
                                    HandoffDirection, HandoffStatus, HandoffTrigger,
                                    JobStatus, Role, SegmentStatus, TaskStatus)
from aura.core.domain.errors import (Conflict, Forbidden, HandoffRejected, NotFound,
                                     RuleViolation)
from aura.core.domain.job import Job
from aura.core.domain.segment import ProposedAction, Segment
from aura.core.policy.handoff_policy import build_gate_package
from aura.core.services.handoffs import create_handoff, escalate_overdue, resolve_handoff
from tests.unit.fakes import (FakeAuditRepo, FakeDocumentRepo, FakeEvents, FakeHandoffRepo,
                              FakeJobRepo, FakeSegmentRepo, FakeTaskRepo)

NOW = datetime(2026, 10, 6, 12, 0, tzinfo=timezone.utc)

DIRECTIVE = {"decision": "approve",
             "reasoning": "The draft is accurate and the tone is right for this contact.",
             "new_constraints": {"do_not_revisit": ["subject line"]},
             "next_checkpoint": {"condition": "Reply received", "escalate_if": "No reply in 7d"}}


def good_package():
    return build_gate_package(
        ProposedAction(tool="send_email", category=ActionCategory.OUTBOUND,
                       arguments={"to": "a@b.com"}, summary="Send intro email"), NOW)


class W:
    def __init__(self):
        self.jobs, self.segments = FakeJobRepo(), FakeSegmentRepo()
        self.tasks, self.handoffs = FakeTaskRepo(), FakeHandoffRepo()
        self.documents = FakeDocumentRepo()
        self.audit, self.events = FakeAuditRepo(), FakeEvents()

    def create(self, package=None, **kw):
        args = dict(deal_id=None, job_id=None, task_type="send_email",
                    assignment_mode=AssignmentMode.HUMAN_REQUIRED,
                    direction=HandoffDirection.BOT_TO_HUMAN,
                    trigger=HandoffTrigger.POLICY_REQUIRED,
                    context_package=package if package is not None else good_package(),
                    directive=None, materiality_inr=None, actor="bot", tasks=self.tasks,
                    handoffs=self.handoffs, audit=self.audit, events=self.events, now=NOW)
        args.update(kw)
        return create_handoff(**args)

    def resolve(self, handoff_id, directive=None, role=Role.DEALMAKER):
        return resolve_handoff(handoff_id, directive or DIRECTIVE, "bhavesh", role, self.jobs,
                               self.segments, self.tasks, self.handoffs, self.documents,
                               self.audit, self.events, now=NOW)

    def paused_job(self):
        job = self.jobs.add(Job(id=None, status=JobStatus.AWAITING_APPROVAL, inputs={},
                                deal_id=None, result=None, created_at=NOW))
        self.segments.add(Segment(id=None, job_id=job.id, seq=1,
                                  status=SegmentStatus.AWAITING_APPROVAL, context_in={},
                                  context_out={"draft": "hi"}, started_at=None, ended_at=None))
        return job


def broken(path, value="__drop__"):
    """A good package with one nested key removed or replaced."""
    pkg = copy.deepcopy(good_package())
    node = pkg
    *parents, leaf = path
    for key in parents:
        node = node[key]
    if value == "__drop__":
        del node[leaf]
    else:
        node[leaf] = value
    return pkg


@pytest.mark.parametrize("package", [
    broken(["decision_required"]),
    broken(["if_you_do_nothing"]),
    broken(["what_happened"]),
    broken(["evidence"]),
    broken(["decision_required", "question"], "too short"),
    broken(["decision_required", "options"], [{"id": "a", "label": "A", "consequence": "x",
                                                "reversible": True}]),
    broken(["decision_required", "options"],
           [{"id": str(i), "label": "L", "consequence": "c", "reversible": True}
            for i in range(6)]),
    broken(["decision_required", "recommendation"], "no-such-option"),
    broken(["decision_required", "confidence"], 1.5),
    broken(["decision_required", "confidence"], -0.1),
    broken(["decision_required", "confidence"], "high"),
    broken(["if_you_do_nothing", "consequence"], "nothing much"),
    broken(["if_you_do_nothing", "auto_escalate_at"], "tomorrow-ish"),
    broken(["if_you_do_nothing", "escalates_to_role"], ""),
    broken(["decision_required", "options", 0, "reversible"], "yes"),
    broken(["decision_required", "recommendation"], None),
])
def test_incomplete_bot_to_human_package_is_rejected(package):
    w = W()
    with pytest.raises(RuleViolation):
        w.create(package)
    assert w.handoffs.items == {} and w.tasks.items == {}


def test_valid_package_creates_task_handoff_audit_and_event():
    w = W()
    h = w.create(deal_id=None, job_id=None)
    assert h.status is HandoffStatus.OPEN
    assert w.tasks.get(h.task_id).status is TaskStatus.REVIEW
    assert h.auto_escalate_at == NOW + timedelta(hours=24)
    assert w.audit.entries[-1].action == "handoff_created"
    assert w.events.published[-1][0] == "handoff_created"


def test_human_to_bot_requires_a_complete_directive():
    w = W()
    kw = dict(direction=HandoffDirection.HUMAN_TO_BOT,
              trigger=HandoffTrigger.HUMAN_CORRECTION, context_package={"note": "redo"})
    with pytest.raises(RuleViolation):
        w.create(directive=None, **kw)
    bad = copy.deepcopy(DIRECTIVE)
    del bad["new_constraints"]["do_not_revisit"]
    with pytest.raises(RuleViolation):
        w.create(directive=bad, **kw)
    h = w.create(directive=DIRECTIVE, **kw)
    assert h.directive == DIRECTIVE and w.tasks.get(h.task_id).status is TaskStatus.ASSIGNED


@pytest.mark.parametrize("mutate", [
    lambda d: d.pop("decision"),
    lambda d: d.update(reasoning="too brief"),
    lambda d: d.pop("new_constraints"),
    lambda d: d.update(new_constraints={}),
    lambda d: d.pop("next_checkpoint"),
    lambda d: d.update(next_checkpoint={"condition": "x"}),
])
def test_resolve_needs_a_complete_directive(mutate):
    w = W()
    h = w.create()
    directive = copy.deepcopy(DIRECTIVE)
    mutate(directive)
    with pytest.raises(RuleViolation):
        w.resolve(h.id, directive)
    assert w.handoffs.get(h.id).status is HandoffStatus.OPEN


def test_decision_must_be_one_of_the_offered_options():
    w = W()
    h = w.create()
    with pytest.raises(RuleViolation):
        w.resolve(h.id, {**DIRECTIVE, "decision": "maybe"})


def test_approve_continues_the_job_like_the_old_approval():
    w = W()
    job = w.paused_job()
    h = w.create(job_id=job.id)
    w.resolve(h.id)
    segs = sorted(w.segments.list_for_job(job.id), key=lambda s: s.seq)
    assert [s.status for s in segs] == [SegmentStatus.DONE, SegmentStatus.QUEUED]
    assert segs[1].context_in == {"draft": "hi"}
    assert w.jobs.get(job.id).status is JobStatus.PENDING
    assert w.handoffs.get(h.id).status is HandoffStatus.RESOLVED
    assert w.handoffs.get(h.id).resolved_by == "bhavesh"
    assert w.tasks.get(h.task_id).status is TaskStatus.DONE


def test_reject_ends_the_job_without_a_new_segment():
    w = W()
    job = w.paused_job()
    h = w.create(job_id=job.id)
    w.resolve(h.id, {**DIRECTIVE, "decision": "reject"})
    assert w.jobs.get(job.id).status is JobStatus.REJECTED
    assert len(w.segments.list_for_job(job.id)) == 1
    assert w.tasks.get(h.task_id).status is TaskStatus.CANCELLED


def test_resolving_twice_is_a_conflict():
    w = W()
    h = w.create()
    w.resolve(h.id)
    with pytest.raises(Conflict):
        w.resolve(h.id)


def test_resolving_an_unknown_handoff_is_not_found():
    with pytest.raises(NotFound):
        W().resolve(99)


def test_resolution_is_audited_and_published():
    w = W()
    h = w.create()
    w.resolve(h.id)
    entry = w.audit.entries[-1]
    assert entry.action == "handoff_resolved" and entry.payload["decision"] == "approve"
    assert w.events.published[-1][0] == "handoff_resolved"


def _classify_world(decision):
    w = W()
    doc = Document(id=5, deal_id=1, doc_class=DocClass.NDA, filename="ts.pdf", sha256="x",
                   byte_size=1, current_version=1, contains_upsi=False, sensitivity=2,
                   uploaded_by="u", uploaded_at=NOW)
    w.documents = FakeDocumentRepo([doc])
    action = ProposedAction(
        tool="classify_document", category=ActionCategory.DOCUMENT_CLASSIFICATION,
        arguments={"document_id": 5, "current_class": "nda", "proposed_class": "term_sheet",
                   "confidence": 0.8}, summary="Classify ts.pdf as term_sheet")
    h = w.create(build_gate_package(action, NOW), task_type="classify_document")
    w.resolve(h.id, {**DIRECTIVE, "decision": decision})
    return doc


def test_confirming_a_classification_sets_the_class_and_confirms_it():
    doc = _classify_world("confirm")
    assert doc.doc_class is DocClass.TERM_SHEET and doc.class_confirmed is True


def test_keeping_the_current_class_still_confirms_it():
    doc = _classify_world("keep")
    assert doc.doc_class is DocClass.NDA and doc.class_confirmed is True


def test_classification_package_offers_confirm_or_keep():
    action = ProposedAction(
        tool="classify_document", category=ActionCategory.DOCUMENT_CLASSIFICATION,
        arguments={"document_id": 5, "current_class": "nda", "proposed_class": "spa"},
        summary="Classify x as spa")
    decision = build_gate_package(action, NOW)["decision_required"]
    assert [o["id"] for o in decision["options"]] == ["confirm", "keep"]
    assert decision["recommendation"] == "confirm"


def test_overdue_open_handoffs_escalate_once():
    w = W()
    h = w.create()
    assert escalate_overdue(w.handoffs, w.audit, w.events, now=NOW) == 0
    later = NOW + timedelta(hours=25)
    assert escalate_overdue(w.handoffs, w.audit, w.events, now=later) == 1
    assert w.handoffs.get(h.id).status is HandoffStatus.ESCALATED
    assert escalate_overdue(w.handoffs, w.audit, w.events, now=later) == 0
    w.resolve(h.id)  # an escalated handoff can still be resolved
    assert w.handoffs.get(h.id).status is HandoffStatus.RESOLVED


@pytest.mark.parametrize("role", [Role.ANALYST, Role.ADMIN, Role.COMPLIANCE])
def test_only_a_dealmaker_resolves_a_non_policy_handoff(role):
    w = W()
    handoff = w.create(trigger=HandoffTrigger.MATERIALITY_GATE)
    with pytest.raises(Forbidden):
        w.resolve(handoff.id, role=role)
    assert w.handoffs.get(handoff.id).status is HandoffStatus.OPEN


def test_compliance_may_also_resolve_a_policy_required_handoff():
    w = W()
    handoff = w.create(trigger=HandoffTrigger.POLICY_REQUIRED)
    assert w.resolve(handoff.id, role=Role.COMPLIANCE).status is HandoffStatus.RESOLVED
    for role in (Role.ANALYST, Role.ADMIN):
        again = w.create(trigger=HandoffTrigger.POLICY_REQUIRED)
        with pytest.raises(Forbidden):
            w.resolve(again.id, role=role)


def test_a_rejected_handoff_leaves_an_audit_row_and_is_marked_to_be_kept():
    w = W()
    with pytest.raises(HandoffRejected) as exc:
        w.create(package={"what_happened": []})
    assert exc.value.persist_writes is True and isinstance(exc.value, RuleViolation)
    row = w.audit.entries[-1]
    assert row.action == "handoff_rejected" and "decision_required" in row.payload["reason"]
    assert w.handoffs.items == {}


def test_a_rejected_directive_is_audited_too():
    w = W()
    handoff = w.create()
    with pytest.raises(HandoffRejected):
        w.resolve(handoff.id, directive={"decision": "approve"})
    row = w.audit.entries[-1]
    assert row.action == "handoff_rejected" and row.payload["handoff_id"] == handoff.id
    assert w.handoffs.get(handoff.id).status is HandoffStatus.OPEN
