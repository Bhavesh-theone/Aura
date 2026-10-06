import itertools

from sqlalchemy import text

from aura.worker.runner import run_once
from aura.worker.stub_orchestrator import StubOrchestrator

DIRECTIVE = {"decision": "approve",
             "reasoning": "The proposal matches what the deal team agreed on Monday.",
             "new_constraints": {"do_not_revisit": []},
             "next_checkpoint": {"condition": "Counterparty replies", "escalate_if": "No reply"}}


class NullEvents:
    def publish(self, event_type: str, payload: dict) -> None:
        pass


def run_worker(api, orchestrator=None, limit: int = 10) -> int:
    """Run the queued segments on the test session, the way the worker loop would."""
    ran = 0
    while ran < limit and run_once(api.session, orchestrator or StubOrchestrator(),
                                   NullEvents()):
        ran += 1
    return ran


def make_deal(api, external_id="H-1", user="bhavesh") -> int:
    r = api.call("POST", "/api/deals", user=user,
                 json={"external_id": external_id, "name": f"Deal {external_id}",
                       "transaction_class": "DEBT"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def upload(api, deal_id, filename="doc.pdf", doc_class="nda", content=b"hello", user="bhavesh"):
    r = api.call("POST", f"/api/deals/{deal_id}/documents", user=user,
                 files={"file": (filename, content)}, data={"doc_class": doc_class})
    assert r.status_code == 201, r.text
    return r.json()


def submit(api, inputs, deal_id=None, user="bhavesh"):
    r = api.call("POST", "/api/jobs", user=user, json={"inputs": inputs, "deal_id": deal_id})
    assert r.status_code == 202, r.text
    return r.json()


def set_stage(api, deal_id, stage):
    """Put a deal at a stage directly, for tests that are not about the guards on the way."""
    api.session.execute(text("UPDATE deals SET stage = :s WHERE id = :i"),
                        {"s": stage, "i": deal_id})
    api.session.commit()


def mark_executed(api, doc_id, user="bhavesh", value=True):
    r = api.call("PATCH", f"/api/documents/{doc_id}", user=user, json={"is_executed": value})
    assert r.status_code == 200, r.text
    return r.json()


def upload_executed(api, deal_id, filename, doc_class, user="bhavesh"):
    doc = upload(api, deal_id, filename, doc_class, content=filename.encode(), user=user)
    return mark_executed(api, doc["id"], user=user)


_pans = itertools.count(1)


def party(api, name="Acme Capital", pan="auto", user="bhavesh"):
    """A party with a unique PAN (pan=None for none at all)."""
    if pan == "auto":
        pan = f"ABCDE{next(_pans):04d}F"
    body = {"party_type": "company", "display_name": name,
            "identifiers": [{"scheme": "PAN", "value": pan}] if pan else []}
    r = api.call("POST", "/api/parties", user=user, json=body)
    assert r.status_code == 201, r.text
    return r.json()


def link(api, deal_id, party_id, role, user="bhavesh"):
    r = api.call("POST", f"/api/deals/{deal_id}/parties", user=user,
                 json={"party_id": party_id, "role": role})
    assert r.status_code == 201, r.text
    return r.json()


def move(api, deal_id, to, user="bhavesh", **body):
    return api.call("POST", f"/api/deals/{deal_id}/transition", user=user,
                    json={"to_stage": to, **body})
