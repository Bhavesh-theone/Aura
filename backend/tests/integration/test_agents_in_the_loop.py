"""M3 exit: a job proposes a document class and a draft email; both arrive as valid handoffs
and agent_run traces each one. Everything runs on the deterministic stub orchestrator."""
import hashlib
import json

from sqlalchemy import text

from aura.core.policy.handoff_policy import validate_bot_to_human
from aura.data.repositories.sql import SqlAgentRunRepository
from tests.integration.helpers import (DIRECTIVE, make_deal, run_worker, set_stage,
                                       submit, upload)


def _open_handoffs(api, user="bhavesh"):
    return api.call("GET", "/api/handoffs", user=user, params={"status": "open"}).json()


def _resolve(api, handoff_id, decision):
    r = api.call("POST", f"/api/handoffs/{handoff_id}/resolve",
                 json={**DIRECTIVE, "decision": decision})
    assert r.status_code == 200, r.text
    return r.json()


def _doc(api, deal, doc_id):
    return next(d for d in api.call("GET", f"/api/deals/{deal}/documents").json()
                if d["id"] == doc_id)


def test_classify_document_arrives_as_a_handoff_and_confirming_sets_the_class(api):
    deal = make_deal(api)
    doc = upload(api, deal, "Acme_TermSheet_v2.pdf", "nda", b"Indicative terms ...")
    assert doc["class_confirmed"] is False
    job = submit(api, {"capability": "classify_document", "document_id": doc["id"]}, deal)
    assert run_worker(api) == 1

    (h,) = _open_handoffs(api)
    validate_bot_to_human(h["context_package"])
    assert h["task_type"] == "classify_document" and h["deal_id"] == deal
    assert h["trigger"] == "confidence_below_threshold"  # 0.9 is under the 0.95 bar
    decision = h["context_package"]["decision_required"]
    assert [o["id"] for o in decision["options"]] == ["confirm", "keep"]
    assert decision["recommendation"] == "confirm" and decision["confidence"] == 0.9
    args = h["context_package"]["proposed_action"]["arguments"]
    assert args["proposed_class"] == "term_sheet" and args["current_class"] == "nda"

    # nothing changes until a human decides
    assert _doc(api, deal, doc["id"])["doc_class"] == "nda"
    _resolve(api, h["id"], "confirm")
    after = _doc(api, deal, doc["id"])
    assert after["doc_class"] == "term_sheet" and after["class_confirmed"] is True

    assert run_worker(api) == 1
    assert api.call("GET", f"/api/jobs/{job['id']}").json()["status"] == "complete"


def test_keeping_the_current_class_confirms_it_without_changing_it(api):
    deal = make_deal(api)
    doc = upload(api, deal, "Acme_TermSheet_v2.pdf", "nda")
    submit(api, {"capability": "classify_document", "document_id": doc["id"]}, deal)
    run_worker(api)
    (h,) = _open_handoffs(api)
    _resolve(api, h["id"], "keep")
    after = _doc(api, deal, doc["id"])
    assert after["doc_class"] == "nda" and after["class_confirmed"] is True


def test_an_unrecognisable_document_proposes_keeping_its_class(api):
    deal = make_deal(api)
    doc = upload(api, deal, "scan0001.pdf", "tax_return")
    submit(api, {"capability": "classify_document", "document_id": doc["id"]}, deal)
    run_worker(api)
    (h,) = _open_handoffs(api)
    decision = h["context_package"]["decision_required"]
    assert decision["recommendation"] == "keep" and decision["confidence"] == 0.3


def test_classification_needs_a_document_on_the_deal(api):
    deal, other = make_deal(api, "A-1"), make_deal(api, "A-2")
    doc = upload(api, other, "x.pdf", "nda")
    r = api.call("POST", "/api/jobs", json={
        "inputs": {"capability": "classify_document", "document_id": doc["id"]},
        "deal_id": deal})
    assert r.status_code == 404
    r = api.call("POST", "/api/jobs", json={
        "inputs": {"capability": "classify_document", "document_id": doc["id"]}})
    assert r.status_code == 422
    r = api.call("POST", "/api/jobs", json={"inputs": {"capability": "dance"}, "deal_id": deal})
    assert r.status_code == 422


def test_email_draft_is_always_a_handoff_and_is_never_sent(api):
    deal = make_deal(api)
    party = api.call("POST", "/api/parties", json={"party_type": "company",
                                                   "display_name": "Acme Capital"}).json()
    api.call("POST", f"/api/deals/{deal}/parties", json={"party_id": party["id"],
                                                         "role": "lender"})
    job = submit(api, {"capability": "draft_email", "party_id": party["id"],
                       "brief": "Introduce the mandate."}, deal)
    assert run_worker(api) == 1

    (h,) = _open_handoffs(api)
    validate_bot_to_human(h["context_package"])
    assert h["task_type"] == "draft_email" and h["trigger"] == "policy_required"
    action = h["context_package"]["proposed_action"]
    assert action["category"] == "outbound"
    assert "Acme Capital" in action["arguments"]["body"]
    assert [o["id"] for o in h["context_package"]["decision_required"]["options"]] == [
        "approve", "reject"]
    assert api.call("GET", f"/api/jobs/{job['id']}").json()["status"] == "awaiting_approval"

    _resolve(api, h["id"], "approve")
    run_worker(api)
    done = api.call("GET", f"/api/jobs/{job['id']}").json()
    assert done["status"] == "complete" and "sent" not in done["result"]


def test_email_draft_needs_a_party_on_the_deal(api):
    deal = make_deal(api)
    party = api.call("POST", "/api/parties", json={"party_type": "company",
                                                   "display_name": "Elsewhere Ltd"}).json()
    r = api.call("POST", "/api/jobs", json={
        "inputs": {"capability": "draft_email", "party_id": party["id"]}, "deal_id": deal})
    assert r.status_code == 404


def test_every_run_is_recorded_and_traceable_to_its_exact_prompt(api):
    deal = make_deal(api)
    doc = upload(api, deal, "Acme_TermSheet_v2.pdf", "nda")
    submit(api, {"capability": "classify_document", "document_id": doc["id"]}, deal)
    run_worker(api)

    runs = api.call("GET", "/api/agent-runs", params={"deal_id": deal}).json()
    assert len(runs) == 1
    run = runs[0]
    assert {"id", "model_id", "prompt_template_id", "prompt_hash", "latency_ms", "tokens_in",
            "tokens_out", "confidence", "started_at"} <= set(run)
    assert run["model_id"] == "stub" and run["prompt_template_id"] == "stub.classify_document.v1"
    assert run["confidence"] == 0.9 and run["tokens_in"] == 0 and run["cost_inr"] == 0

    detail = api.call("GET", f"/api/agent-runs/{run['id']}").json()
    messages = detail["input_digest"]["messages"]
    canonical = json.dumps(messages, sort_keys=True, separators=(",", ":"))
    assert hashlib.sha256(canonical.encode()).hexdigest() == run["prompt_hash"]
    assert json.loads(detail["output"]["text"])["tool"] == "classify_document"
    assert detail["tool_calls"][0]["tool"] == "classify_document"

    assert api.call("GET", "/api/agent-runs", params={"deal_id": 9999}).status_code == 404


def test_each_segment_run_writes_a_row_and_resuming_writes_none(api):
    submit(api, {"brief": "intro"})
    run_worker(api)
    assert api.session.execute(text("SELECT COUNT(*) FROM agent_run")).scalar() == 1
    (h,) = _open_handoffs(api)
    _resolve(api, h["id"], "approve")
    run_worker(api)  # the resumed segment only completes; no model is called
    assert api.session.execute(text("SELECT COUNT(*) FROM agent_run")).scalar() == 1


def test_if_the_run_cannot_be_recorded_its_output_is_not_used(api, monkeypatch):
    def broken(self, run):
        raise RuntimeError("agent_run table unavailable")

    monkeypatch.setattr(SqlAgentRunRepository, "add", broken)
    job = submit(api, {"brief": "intro"})
    run_worker(api)

    assert api.call("GET", f"/api/jobs/{job['id']}").json()["status"] == "failed"
    assert _open_handoffs(api) == []
    assert api.session.execute(text("SELECT COUNT(*) FROM handoff")).scalar() == 0
    assert api.session.execute(text("SELECT COUNT(*) FROM task")).scalar() == 0
    assert api.session.execute(text("SELECT COUNT(*) FROM agent_run")).scalar() == 0
    err = api.session.execute(text("SELECT payload FROM audit_entries "
                                   "WHERE action = 'segment_failed'")).scalar()
    assert "could not write agent_run" in err["error"]


def test_stage_guard_evaluations_carry_plain_english_descriptions(api):
    deal = make_deal(api)
    set_stage(api, deal, "QUALIFIED")
    text_ = "An engagement letter is on file and marked executed"

    dry = api.call("GET", f"/api/deals/{deal}/guards", params={"to_stage": "MANDATED"}).json()
    assert dry[0]["description"] == text_
    blocked = api.call("POST", f"/api/deals/{deal}/transition", json={"to_stage": "MANDATED"})
    assert blocked.status_code == 409
    assert blocked.json()["evaluations"][0]["description"] == text_
    ok = api.call("POST", f"/api/deals/{deal}/transition",
                  json={"to_stage": "MANDATED", "override_justification": "signed on paper"})
    assert ok.json()["evaluations"][0]["description"] == text_
    names = api.session.execute(text("SELECT guard_name FROM stage_guard WHERE description = ''"
                                     )).scalars().all()
    assert names == []  # every seeded guard has one
