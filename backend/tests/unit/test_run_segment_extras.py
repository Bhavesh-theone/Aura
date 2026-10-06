"""run_segment: extractions with their confidence gate, and do_not_revisit."""
from datetime import datetime, timezone

import pytest

from aura.core.domain.deal import Deal
from aura.core.domain.document import Document
from aura.core.domain.enums import (ActionCategory, DealStage, DocClass, HandoffDirection,
                                    HandoffStatus, HandoffTrigger, JobStatus, Role,
                                    SegmentStatus, TaskStatus, TransactionClass)
from aura.core.domain.extraction import ExtractionProposal
from aura.core.domain.job import Job
from aura.core.domain.segment import ProposedAction, Segment
from aura.core.ports.orchestrator import OrchestratorResult
from aura.core.services.handoffs import resolve_handoff
from aura.core.services.run_segment import run_segment
from tests.unit.fakes import (FakeAuditRepo, FakeDocumentRepo, FakeEvents, FakeHandoffRepo,
                              FakeJobRepo, FakeRunSink, FakeSegmentRepo, FakeTaskRepo,
                              FakeUow)

NOW = datetime(2026, 10, 6, 12, 0, tzinfo=timezone.utc)
DOC = Document(id=5, deal_id=1, doc_class=DocClass.FINANCIAL_STATEMENT, filename="fy.txt",
               sha256="x", byte_size=1, current_version=2, contains_upsi=False,
               sensitivity=2, uploaded_by="u", uploaded_at=NOW)


class FakeExtractionRepo:
    def __init__(self):
        self.items = {}

    def add(self, e):
        e.id = len(self.items) + 1
        self.items[e.id] = e
        return e

    def get(self, extraction_id):
        return self.items.get(extraction_id)

    def update(self, e):
        self.items[e.id] = e
        return e

    def list_for_deal(self, deal_id):
        return list(self.items.values())


class Extracting:
    def __init__(self, confidence):
        self.confidence = confidence

    def run(self, context_in, run_context):
        return OrchestratorResult(
            completed=False, context_out={**context_in, "proposal_made": True},
            proposed_action=None,
            extraction=ExtractionProposal("financials.v1", {"revenue_inr": 1.0},
                                          self.confidence, model_run_id=9))


class Gating:
    def __init__(self, tool="send_email"):
        self.tool = tool

    def run(self, context_in, run_context):
        return OrchestratorResult(
            completed=False, context_out={"draft": "x"},
            proposed_action=ProposedAction(tool=self.tool, category=ActionCategory.OUTBOUND,
                                           arguments={}, summary="Send it"))


class World:
    def __init__(self, context_in=None):
        self.jobs, self.segments = FakeJobRepo(), FakeSegmentRepo()
        self.tasks, self.handoffs = FakeTaskRepo(), FakeHandoffRepo()
        self.audit, self.events = FakeAuditRepo(), FakeEvents()
        self.runs, self.uow = FakeRunSink(), FakeUow()
        self.extractions, self.documents = FakeExtractionRepo(), FakeDocumentRepo([DOC])
        self.job = self.jobs.add(Job(id=None, status=JobStatus.PENDING, inputs={}, deal_id=1,
                                     result=None, created_at=NOW, created_by="asha"))
        self.new_segment(context_in or {})

    def new_segment(self, context_in):
        self.seg = self.segments.add(Segment(
            id=None, job_id=self.job.id, seq=len(self.segments.items) + 1,
            status=SegmentStatus.QUEUED, context_in=context_in, context_out=None,
            started_at=None, ended_at=None))

    def run(self, orchestrator):
        run_segment(self.seg.id, orchestrator, self.jobs, self.segments, self.tasks,
                    self.handoffs, self.audit, self.events, self.runs, self.uow,
                    extractions=self.extractions, documents=self.documents)


EXTRACT_CONTEXT = {"document": {"id": 5, "filename": "fy.txt"}}


def test_a_confident_extraction_is_recorded_unverified_and_the_job_completes():
    w = World(EXTRACT_CONTEXT)
    w.run(Extracting(0.97))
    (extraction,) = w.extractions.items.values()
    assert extraction.feeds_valuation is False and extraction.human_verified_by is None
    assert extraction.document_id == 5 and extraction.version == 2
    assert extraction.model_run_id == 9
    assert w.jobs.get(w.job.id).status is JobStatus.COMPLETE
    assert w.handoffs.open_ones() == []
    assert "extraction_created" in [e.action for e in w.audit.entries]


def test_a_doubtful_extraction_goes_to_a_person_as_a_confidence_handoff():
    w = World(EXTRACT_CONTEXT)
    w.run(Extracting(0.6))
    (handoff,) = w.handoffs.open_ones()
    assert handoff.trigger is HandoffTrigger.CONFIDENCE_BELOW_THRESHOLD
    assert handoff.task_type == "extract_financials"
    options = handoff.context_package["decision_required"]["options"]
    assert [o["id"] for o in options] == ["verify", "discard"]
    assert w.jobs.get(w.job.id).status is JobStatus.AWAITING_APPROVAL
    (extraction,) = w.extractions.items.values()
    assert extraction.feeds_valuation is False
    assert handoff.context_package["proposed_action"]["arguments"]["extraction_id"] == \
        extraction.id


def _resolve(w, handoff, decision, role=Role.DEALMAKER):
    directive = {"decision": decision,
                 "reasoning": "I checked the figures against the audited statements.",
                 "new_constraints": {"do_not_revisit": []},
                 "next_checkpoint": {"condition": "Valuation drafted", "escalate_if": "n/a"}}
    return resolve_handoff(handoff.id, directive, "bhavesh", role, w.jobs, w.segments,
                           w.tasks, w.handoffs, w.documents, w.audit, w.events, now=NOW,
                           extractions=w.extractions)


def test_verifying_the_handoff_marks_the_extraction_verified_and_feeding_valuation():
    w = World(EXTRACT_CONTEXT)
    w.run(Extracting(0.6))
    (handoff,) = w.handoffs.open_ones()
    _resolve(w, handoff, "verify")
    (extraction,) = w.extractions.items.values()
    assert extraction.human_verified_by == "bhavesh" and extraction.feeds_valuation is True
    assert w.jobs.get(w.job.id).status is JobStatus.PENDING  # carries on
    assert "extraction_verified" in [e.action for e in w.audit.entries]


def test_discarding_leaves_the_extraction_out_of_valuation_and_ends_the_job():
    w = World(EXTRACT_CONTEXT)
    w.run(Extracting(0.6))
    (handoff,) = w.handoffs.open_ones()
    _resolve(w, handoff, "discard")
    (extraction,) = w.extractions.items.values()
    assert extraction.feeds_valuation is False and extraction.human_verified_by is None
    assert w.jobs.get(w.job.id).status is JobStatus.REJECTED


def _resolved_handoff_with(w, do_not_revisit, decision="approve"):
    """A resolved handoff on this deal whose directive forbids revisiting a task type."""
    w.run(Gating())
    (handoff,) = w.handoffs.open_ones()
    directive = {"decision": decision,
                 "reasoning": "We decided this once and the answer will not change.",
                 "new_constraints": {"do_not_revisit": do_not_revisit},
                 "next_checkpoint": {"condition": "Reply received", "escalate_if": "n/a"}}
    resolve_handoff(handoff.id, directive, "bhavesh", Role.DEALMAKER, w.jobs, w.segments,
                    w.tasks, w.handoffs, w.documents, w.audit, w.events, now=NOW)
    return handoff


def test_do_not_revisit_skips_the_new_handoff_and_applies_the_earlier_approval():
    w = World()
    first = _resolved_handoff_with(w, ["send_email"])
    # the approved job carries on into a new segment, which gates the same kind of action
    w.new_segment({})
    before = len(w.handoffs.items)
    w.run(Gating())
    assert len(w.handoffs.items) == before  # no new handoff
    skipped = [e for e in w.audit.entries if e.action == "handoff_skipped_per_directive"]
    assert len(skipped) == 1
    assert skipped[0].payload == {"task_type": "send_email", "source_handoff_id": first.id,
                                  "decision": "approve", "approved": True}
    assert w.segments.get(w.seg.id).status is SegmentStatus.DONE
    assert w.jobs.get(w.job.id).status is JobStatus.PENDING  # the earlier approval applies


def test_do_not_revisit_applies_an_earlier_rejection_too():
    w = World()
    _resolved_handoff_with(w, ["send_email"], decision="reject")
    w.job = w.jobs.add(Job(id=None, status=JobStatus.PENDING, inputs={}, deal_id=1,
                           result=None, created_at=NOW, created_by="asha"))
    w.new_segment({})
    w.run(Gating())
    assert w.jobs.get(w.job.id).status is JobStatus.REJECTED
    assert [e.action for e in w.audit.entries].count("handoff_skipped_per_directive") == 1


def test_a_directive_about_another_task_type_does_not_skip():
    w = World()
    _resolved_handoff_with(w, ["draft_nda"])
    w.new_segment({})
    w.run(Gating())
    assert len(w.handoffs.open_ones()) == 1
    assert "handoff_skipped_per_directive" not in [e.action for e in w.audit.entries]


def test_a_directive_on_another_deal_does_not_skip():
    w = World()
    first = _resolved_handoff_with(w, ["send_email"])
    first.deal_id = 99  # that decision was about a different deal
    w.new_segment({})
    w.run(Gating())
    assert len(w.handoffs.open_ones()) == 1