"""Deal intake end to end on PostgreSQL with the real parsers (PyMuPDF, DOCX, XLSX, PPTX) on
the Project Kaveri fixtures and a scripted stand-in for the local model: upload -> index ->
extract -> review edits -> confirm -> a deal with its parties, profile, mandate and the very
same documents and chunks; row-level security on drafts; idempotent uploads; 409 and 422."""
from pathlib import Path

import pytest
from sqlalchemy import text

from aura.agents.llm.intake_extractor import ScriptedFieldExtractor
from aura.core.ports.orchestrator import TransientModelError
from aura.core.policy.retry_policy import RetryPolicy
from aura.ingest.embedder import FakeEmbedder
from aura.worker.intake import extract_once
from tests.integration.helpers import NullEvents
from tests.integration.test_indexing_search import Recorder, run_indexer

KAVERI = Path(__file__).resolve().parents[1] / "fixtures" / "parsing"
PACK = ("kaveri_audited_financials_fy24.pdf", "kaveri_ncd_term_sheet.pdf",
        "kaveri_information_memorandum.docx", "kaveri_financial_model.xlsx",
        "kaveri_teaser.pptx")

# What the stand-in model "reads": a sector the documents support, an incorporation year
# only (refused: not a full date), parties, and a deliberately different instrument to force
# a conflict with the regex reading.
ANSWERS = {
    "identity": {"sector": {"value": "Auto components", "confidence": 0.8, "chunk": "C1",
                            "quote": "precision machined components"},
                 "incorporation_date": {"value": "2011", "confidence": 0.9}},
    "transaction": {"subclass": {"value": "Term loan", "confidence": 0.7, "chunk": "C1",
                                 "quote": "Term loan"},
                    "purpose": {"value": "Refinancing of existing term loans and capex",
                                "confidence": 0.8, "chunk": "C1",
                                "quote": "Refinancing of existing term loans"}},
    "parties": {"parties": [{"name": "Deccan Growth Fund II", "role": "investor",
                             "party_type": "fund", "chunk": "C1",
                             "quote": "Deccan Growth Fund II"}]},
    "terms": {"security": {"value": "First ranking exclusive charge over movable fixed "
                                    "assets", "confidence": 0.9, "chunk": "C1",
                           "quote": "First ranking exclusive charge"},
              "covenants": {"value": ["Minimum DSCR of 1.25x",
                                      "Net debt to EBITDA not exceeding 2.5x"],
                            "confidence": 0.8, "chunk": "C1", "quote": "Minimum DSCR"}},
    "regulatory": {"regulatory_flags": [{"flag": "SEBI", "reason": "Listed NCDs on BSE",
                                         "chunk": "C1", "quote": "listed"}]},
    "profile": {"repayment": {"value": "bullet", "confidence": 0.9, "chunk": "C1",
                              "quote": "bullet redemption"}},
}


def _create(api, user="bhavesh", **body):
    r = api.call("POST", "/api/intakes", user=user, json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _upload(api, intake_id, names, user="bhavesh"):
    files = [("files", (n, (KAVERI / n).read_bytes())) for n in names]
    r = api.call("POST", f"/api/intakes/{intake_id}/files", user=user, files=files)
    assert r.status_code == 201, r.text
    return r.json()


def _extract(api, extractor=None, policy=None, events=None):
    """One worker step; by default the scripted model, recorded like the real one."""
    return extract_once(api.session, events or NullEvents(), worker_id="test-intake",
                        extractor=extractor, embedder=FakeEmbedder(), policy=policy,
                        extractor_for=lambda recorder: ScriptedFieldExtractor(ANSWERS,
                                                                              recorder))


def _get(api, intake_id, user="bhavesh"):
    r = api.call("GET", f"/api/intakes/{intake_id}", user=user)
    assert r.status_code == 200, r.text
    return r.json()


def _scalar(api, sql, **params):
    return api.session.execute(text(sql), params).scalar()


def test_full_intake_flow_creates_the_deal_with_its_documents(api):
    intake = _create(api, transaction_class_hint="DEBT")
    assert intake["status"] == "draft" and intake["fields"]["transaction_class"]["value"] == \
        "DEBT"
    body = _upload(api, intake["id"], PACK)
    assert len(body["files"]) == 5 and not any(f["duplicate"] for f in body["files"])
    assert body["intake"]["status"] == "processing"
    assert {f["stage"] for f in body["intake"]["files"]} == {"uploaded"}
    # the same bytes again: nothing new
    again = _upload(api, intake["id"], PACK[:1])
    assert again["files"][0]["duplicate"] is True
    assert _scalar(api, "SELECT count(*) FROM document WHERE intake_id = :i",
                   i=intake["id"]) == 5
    # extraction waits for the files
    assert _extract(api) is None
    events = Recorder()
    assert run_indexer(api, events=events) == ["indexed"] * 5
    assert any(p.get("kind") == "intake" and p.get("recipient") == "bhavesh"
               for _, p in events.events)
    assert _extract(api, events=events) == "extracted"
    got = _get(api, intake["id"])
    assert got["status"] == "review" and got["progress"]["stage"] == "ready"
    f = got["fields"]
    assert f["cin"]["value"] == "U29253MH2011PTC215478" and f["cin"]["source"] == "regex"
    assert f["pan"]["value"] == "AAFCK4821M"
    assert f["company_name"]["value"] == "Kaveri Precision Components Private Limited"
    assert f["revenue_inr"]["value"] == 4_123_800_000
    assert f["ebitda_inr"]["value"] == 681_500_000
    assert f["net_debt_inr"]["value"] == 964_000_000
    assert f["ticket_size_inr"]["value"] == 1_500_000_000
    assert f["tenor_months"]["value"] == 60 and f["coupon_pct"]["value"] == 11.25
    cite = f["revenue_inr"]["citations"][0]
    assert "412.38" in cite["quote"] and cite["chunk_id"] and cite["filename"]
    assert f["incorporation_date"]["value"] is None
    assert "year" in (f["incorporation_date"]["error"] or "")
    assert f["profile.amount_inr"]["value"] == 1_500_000_000
    assert f["profile.repayment"]["value"] == "bullet"
    # the cited passage, with its page text, for the citation pane
    r = api.call("GET", f"/api/intakes/{intake['id']}/chunks/{cite['chunk_id']}")
    assert r.status_code == 200 and "412.38" in r.json()["page_text"]
    # the model's instrument disagrees with the regex reading: a conflict to resolve
    conflict = next(c for c in got["conflicts"] if c["field"] == "subclass")
    assert len(conflict["candidates"]) == 2 and not got["review"]["ready"]
    # model runs recorded as intake_extractor, private to the intake
    assert _scalar(api, "SELECT count(*) FROM agent_run WHERE intake_id = :i "
                        "AND archetype = 'intake_extractor' AND deal_id IS NULL",
                   i=intake["id"]) >= 5
    # the review: pick the regex instrument, change the deal name, accept what needs it
    regex_idx = next(i for i, c in enumerate(conflict["candidates"]) if c["source"] == "regex")
    patch = {"conflicts": {conflict["id"]: {"chosen": regex_idx}},
             "fields": {"deal_name": {"value": "Kaveri NCD 2024"},
                        "incorporation_date": {"value": None}}}
    r = api.call("PATCH", f"/api/intakes/{intake['id']}", json=patch)
    assert r.status_code == 200, r.text
    review = r.json()
    accept = {k: {"accepted": True} for k, v in review["fields"].items()
              if (v["needs_review"] or v["requires_confirmation"]) and not v["accepted"]}
    r = api.call("PATCH", f"/api/intakes/{intake['id']}", json={"fields": accept})
    assert r.status_code == 200 and r.json()["review"]["ready"], r.json()["review"]
    r = api.call("POST", f"/api/intakes/{intake['id']}/confirm", json={})
    assert r.status_code == 201, r.text
    deal_id = r.json()["deal_id"]
    assert r.json()["external_id"].startswith("AUR-")
    deal = api.call("GET", f"/api/deals/{deal_id}").json()
    assert deal["name"] == "Kaveri NCD 2024" and deal["transaction_class"] == "DEBT"
    assert deal["stage"] == "ORIGINATED" and deal["regulatory_flags"] == ["SEBI"]
    assert deal["profile"]["amount_inr"] == 1_500_000_000
    assert deal["profile"]["tenor_months"] == 60
    roles = {(p["display_name"], p["role"]) for p in deal["parties"]}
    assert ("Kaveri Precision Components Private Limited", "issuer") in roles
    parties = api.call("GET", "/api/parties").json()
    kaveri = next(p for p in parties if p["display_name"].startswith("Kaveri"))
    assert {"scheme": "CIN", "value": "U29253MH2011PTC215478"} in kaveri["identifiers"]
    mandates = api.call("GET", f"/api/deals/{deal_id}/mandates").json()
    assert mandates and mandates[0]["side"] == "raise" and mandates[0]["criteria"]
    docs = api.call("GET", f"/api/deals/{deal_id}/documents").json()
    assert len(docs) == 5 and all(d["index_status"] == "indexed" and d["chunk_count"]
                                  for d in docs)
    # the same chunks, re-pointed, not re-parsed
    assert _scalar(api, "SELECT count(*) FROM doc_chunk WHERE intake_id = :i "
                        "AND deal_id IS NULL", i=intake["id"]) == 0
    assert _scalar(api, "SELECT count(*) FROM doc_chunk WHERE deal_id = :d",
                   d=deal_id) > 0
    assert _scalar(api, "SELECT count(*) FROM agent_run WHERE intake_id = :i "
                        "AND deal_id = :d", i=intake["id"], d=deal_id) >= 5
    hits = api.call("GET", f"/api/deals/{deal_id}/search?q=revenue%20from%20operations").json()
    assert hits["results"]
    assert _scalar(api, "SELECT count(*) FROM audit_entries WHERE action = "
                        "'intake_confirmed' AND deal_id = :d", d=deal_id) == 1
    # confirmed twice -> 409; it is no longer an open draft
    assert api.call("POST", f"/api/intakes/{intake['id']}/confirm",
                    json={}).status_code == 409
    assert api.call("GET", "/api/intakes").json() == []
    # the override metric: deal_name and incorporation_date... deal_name was auto-filled
    m = api.call("GET", "/api/metrics").json()["evaluation"]["intake"]
    assert m["intakes_confirmed"] == 1 and m["fields_changed"] >= 1
    assert 0 < m["override_rate"] < 1


def test_a_draft_is_private_to_its_creator(api):
    intake = _create(api, company_name="Kaveri Precision Components Private Limited")
    _upload(api, intake["id"], PACK[:1])
    run_indexer(api)
    chunk_id = _scalar(api, "SELECT min(id) FROM doc_chunk WHERE intake_id = :i",
                       i=intake["id"])
    assert chunk_id
    for path in (f"/api/intakes/{intake['id']}",
                 f"/api/intakes/{intake['id']}/chunks/{chunk_id}"):
        assert api.call("GET", path, user="asha").status_code == 404
    assert api.call("GET", "/api/intakes", user="asha").json() == []
    assert api.call("PATCH", f"/api/intakes/{intake['id']}", user="asha",
                    json={"external_id": "X-1"}).status_code == 404
    doc_id = _scalar(api, "SELECT min(id) FROM document WHERE intake_id = :i",
                     i=intake["id"])
    assert api.call("GET", f"/api/documents/{doc_id}", user="asha").status_code == 404
    # row-level security itself, not just the repository filter
    api.session.commit()
    api.session.execute(text("SELECT set_config('aura.viewer', 'asha', true)"))
    assert api.session.execute(text("SELECT count(*) FROM doc_chunk WHERE intake_id = :i"),
                               {"i": intake["id"]}).scalar() == 0
    assert api.session.execute(text("SELECT count(*) FROM deal_intake")).scalar() == 0
    api.session.rollback()
    # compliance cannot create intakes
    assert api.call("POST", "/api/intakes", user="priya", json={}).status_code == 403


def test_confirm_refuses_an_incomplete_intake_with_field_errors(api):
    intake = _create(api)
    r = api.call("PATCH", f"/api/intakes/{intake['id']}",
                 json={"fields": {"cin": {"value": "NOT-A-CIN"},
                                  "revenue_inr": {"value": "12 crore"}}})
    assert r.status_code == 200
    f = r.json()["fields"]
    assert f["cin"]["value"] == "NOT-A-CIN" and "CIN" in f["cin"]["error"]
    assert f["revenue_inr"]["value"] == 120_000_000 and f["revenue_inr"]["source"] == "user"
    r = api.call("POST", f"/api/intakes/{intake['id']}/confirm", json={})
    assert r.status_code == 422
    errors = r.json()["field_errors"]
    assert {"cin", "company_name", "transaction_class", "deal_name"} <= set(errors)
    assert _scalar(api, "SELECT count(*) FROM deals") == 0
    # a deal can be made from typed values alone
    r = api.call("PATCH", f"/api/intakes/{intake['id']}", json={"fields": {
        "cin": {"value": "U29253MH2011PTC215478"}, "company_name": {"value": "Kaveri P Ltd"},
        "transaction_class": {"value": "EQUITY"}, "deal_name": {"value": "Project K"},
        "profile.round_type": {"value": "not-a-round"}}})
    assert r.status_code == 200
    r = api.call("POST", f"/api/intakes/{intake['id']}/confirm", json={"external_id": "K-1"})
    assert r.status_code == 422 and "profile.round_type" in r.json()["field_errors"]
    api.call("PATCH", f"/api/intakes/{intake['id']}",
             json={"fields": {"profile.round_type": {"value": None}}})
    r = api.call("POST", f"/api/intakes/{intake['id']}/confirm", json={"external_id": "K-1"})
    assert r.status_code == 201, r.text
    assert r.json()["external_id"] == "K-1"


def test_uploads_are_checked_and_a_discard_removes_the_staged_files(api):
    intake = _create(api)
    r = api.call("POST", f"/api/intakes/{intake['id']}/files",
                 files=[("files", ("virus.exe", b"MZ\x90\x00"))])
    assert r.status_code == 415
    body = _upload(api, intake["id"], PACK[2:4])
    file_id = body["files"][0]["id"]
    r = api.call("DELETE", f"/api/intakes/{intake['id']}/files/{file_id}")
    assert r.status_code == 200 and len(r.json()["files"]) == 1
    assert api.call("DELETE", f"/api/intakes/{intake['id']}").status_code == 204
    assert _scalar(api, "SELECT count(*) FROM document WHERE intake_id = :i",
                   i=intake["id"]) == 0
    assert _scalar(api, "SELECT status FROM deal_intake WHERE id = :i",
                   i=intake["id"]) == "discarded"
    assert api.call("POST", f"/api/intakes/{intake['id']}/confirm",
                    json={}).status_code == 409


class DownModel(ScriptedFieldExtractor):
    def extract(self, *a, **k):
        raise TransientModelError("Ollama unreachable: connection refused")


def test_a_model_outage_is_retried_then_falls_back_to_deterministic_extraction(api):
    intake = _create(api)
    _upload(api, intake["id"], PACK[1:2])
    run_indexer(api)
    policy = RetryPolicy(max_attempts=2, base_backoff_seconds=0, lease_seconds=60)
    assert _extract(api, extractor=DownModel(), policy=policy) == "retry"
    got = _get(api, intake["id"])
    assert got["extraction"]["status"] == "queued" and got["status"] == "processing"
    # last attempt: no model, the deterministic extractors still fill the form
    assert _extract(api, extractor=DownModel(), policy=policy) == "extracted"
    got = _get(api, intake["id"])
    assert got["status"] == "review" and got["fields"]["cin"]["value"]
    assert any("deterministic" in w for w in got["extraction"]["warnings"])
    assert got["extraction"]["llm_used"] is False
