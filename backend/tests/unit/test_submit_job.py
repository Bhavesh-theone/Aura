from datetime import datetime, timezone

import pytest

from aura.core.domain.deal import Deal
from aura.core.domain.enums import (DealStage, JobStatus, Role, SegmentStatus,
                                    TransactionClass)
from aura.core.domain.errors import Forbidden, NotFound, RuleViolation
from aura.core.services.submit_job import submit_job
from tests.unit.fakes import (FakeAuditRepo, FakeDealRepo, FakeEvents, FakeJobRepo,
                              FakeSegmentRepo)


def test_submit_creates_job_and_first_segment():
    jobs, segments, audit, events = FakeJobRepo(), FakeSegmentRepo(), FakeAuditRepo(), FakeEvents()
    deals = FakeDealRepo()
    deals.add(Deal(id=None, external_id="D-002", name="x", stage=DealStage.ORIGINATED,
                   transaction_class=TransactionClass.DEBT, owner="u", outcome=None,
                   opened_at=datetime.now(timezone.utc)))

    job = submit_job(inputs={"brief": "draft intro to D-002"}, deal_id=1, actor="bhavesh", actor_role=Role.DEALMAKER,
                     jobs=jobs, segments=segments, audit=audit, events=events, deals=deals)

    assert job.id == 1
    assert job.status is JobStatus.PENDING

    segs = segments.list_for_job(job.id)
    assert len(segs) == 1
    assert segs[0].seq == 1
    assert segs[0].status is SegmentStatus.QUEUED
    assert segs[0].context_in == {"brief": "draft intro to D-002"}


def test_submit_writes_audit_entry():
    jobs, segments, audit, events = FakeJobRepo(), FakeSegmentRepo(), FakeAuditRepo(), FakeEvents()
    submit_job(inputs={}, deal_id=None, actor="bhavesh", actor_role=Role.DEALMAKER,
               jobs=jobs, segments=segments, audit=audit, events=events, deals=FakeDealRepo())
    assert audit.entries[0].action == "job_submitted"
    assert audit.entries[0].actor == "bhavesh"


def test_submit_publishes_event():
    jobs, segments, audit, events = FakeJobRepo(), FakeSegmentRepo(), FakeAuditRepo(), FakeEvents()
    submit_job(inputs={}, deal_id=None, actor="bhavesh", actor_role=Role.DEALMAKER,
               jobs=jobs, segments=segments, audit=audit, events=events, deals=FakeDealRepo())
    assert events.published[0][0] == "job_submitted"


def _submit(inputs, deal_id, deals=None):
    return submit_job(inputs=inputs, deal_id=deal_id, actor="asha", actor_role=Role.ANALYST, jobs=FakeJobRepo(),
                      segments=FakeSegmentRepo(), audit=FakeAuditRepo(), events=FakeEvents(),
                      deals=deals or FakeDealRepo())


def test_job_on_a_deal_the_submitter_cannot_see_is_not_found():
    with pytest.raises(NotFound):
        _submit({"brief": "x"}, deal_id=42)


def test_job_records_who_submitted_it():
    jobs = FakeJobRepo()
    job = submit_job(inputs={}, deal_id=None, actor="asha", actor_role=Role.ANALYST, jobs=jobs,
                     segments=FakeSegmentRepo(), audit=FakeAuditRepo(), events=FakeEvents(),
                     deals=FakeDealRepo())
    assert job.created_by == "asha"


def test_capability_needs_a_deal_and_must_be_known():
    with pytest.raises(RuleViolation):
        _submit({"capability": "classify_document", "document_id": 1}, deal_id=None)
    with pytest.raises(RuleViolation):
        _submit({"capability": "wire_money"}, deal_id=None)


@pytest.mark.parametrize("role", [Role.ADMIN, Role.COMPLIANCE])
def test_only_dealmakers_and_analysts_run_jobs(role):
    jobs = FakeJobRepo()
    with pytest.raises(Forbidden):
        submit_job(inputs={}, deal_id=None, actor="x", actor_role=role, jobs=jobs,
                   segments=FakeSegmentRepo(), audit=FakeAuditRepo(), events=FakeEvents(),
                   deals=FakeDealRepo())
    assert jobs.items == {}


def test_extract_financials_is_a_known_capability_that_loads_its_document():
    from aura.core.domain.document import Document
    from aura.core.domain.enums import DocClass
    from tests.unit.fakes import FakeDocumentRepo
    deals = FakeDealRepo()
    deals.add(Deal(id=None, external_id="D-1", name="x", stage=DealStage.ORIGINATED,
                   transaction_class=TransactionClass.DEBT, owner="u", outcome=None,
                   opened_at=datetime.now(timezone.utc)))
    doc = Document(id=7, deal_id=1, doc_class=DocClass.FINANCIAL_STATEMENT, filename="f.txt",
                   sha256="x", byte_size=1, current_version=3, contains_upsi=False,
                   sensitivity=2, uploaded_by="u", uploaded_at=datetime.now(timezone.utc))
    segments = FakeSegmentRepo()
    job = submit_job(inputs={"capability": "extract_financials", "document_id": 7},
                     deal_id=1, actor="asha", actor_role=Role.ANALYST, jobs=FakeJobRepo(),
                     segments=segments, audit=FakeAuditRepo(), events=FakeEvents(),
                     deals=deals, documents=FakeDocumentRepo([doc]))
    context = segments.list_for_job(job.id)[0].context_in
    assert context["document"]["id"] == 7 and context["document"]["version"] == 3
