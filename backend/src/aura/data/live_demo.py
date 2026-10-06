"""Watch a live workflow: one fresh deal, driven step by step through the public HTTP API.

    uv run python -m aura.data.live_demo [--api URL] [--pace S | --fast] [--until STAGE]
                                         [--auto-resolve-after S | --wait-for-human]

Every step is an ordinary API call made with a real login (dealmaker bhavesh, analyst asha,
compliance priya), so it goes through authentication, walls, guards, the audit chain and
the WebSocket feed exactly as a click in the portal would. Nothing here touches the
database or the services directly, and everything happens in real time.

Open the portal as bhavesh and keep the deal page, Decisions and Activity open while it
runs. Agent jobs run on whatever orchestrator the backend has (CrewAI + Ollama when it is
up, the stub otherwise). When an agent hands a decision over, the script waits for you to
resolve it in Decisions, and resolves it itself as bhavesh after --auto-resolve-after
seconds unless --wait-for-human is given. Ctrl+C stops between steps; the deal is left in
whatever valid stage it reached.
"""
from __future__ import annotations

import argparse
import random
import string
import sys
import time
from datetime import datetime

import httpx

from aura.data.pdf import pdf_bytes

STAGES = ["ORIGINATED", "QUALIFIED", "MANDATED", "PREPARED", "MARKETED", "MATCHED",
          "BID_AUCTION", "NEGOTIATION", "DILIGENCE", "DOCUMENTATION", "CONDITIONS_PRECEDENT",
          "CLOSED"]
LOGINS = {"bhavesh": "admin123", "asha": "analyst123", "priya": "compliance123"}
CLIENT = "Godavari Polymers Pvt Ltd"


class LiveError(RuntimeError):
    pass


class StopHere(Exception):
    """--until reached."""


def _rand(chars: str, n: int) -> str:
    return "".join(random.choice(chars) for _ in range(n))


class Driver:
    def __init__(self, api: str, ui: str, pace: float, until: str,
                 auto_resolve_after: float | None):
        self.api, self.ui, self.pace, self.until = api.rstrip("/"), ui.rstrip("/"), pace, until
        self.auto_resolve_after = auto_resolve_after
        self.http = httpx.Client(base_url=self.api, timeout=60)
        self.tokens: dict[str, str] = {}
        self.deal_id: int | None = None
        self.docs: dict[str, int] = {}
        self.parties: dict[str, int] = {}
        self.stage = "ORIGINATED"

    # ----------------------------------------------------------------- plumbing

    def say(self, actor: str, text: str, look: str | None = None) -> None:
        print(f"[{datetime.now():%H:%M:%S}] {actor:<8} {text}", flush=True)
        if look:
            print(f"{'':20}look: {self.ui}{look}", flush=True)

    def deal_url(self) -> str:
        return f"/deals/{self.deal_id}"

    def wait(self, factor: float = 1.0) -> None:
        time.sleep(self.pace * factor)

    def login(self, user: str) -> None:
        try:
            r = self.http.post("/api/auth/login",
                               json={"username": user, "password": LOGINS[user]})
        except httpx.HTTPError as exc:
            raise LiveError(f"Cannot reach the backend at {self.api} ({exc}). Start it with "
                            "`uv run uvicorn aura.api.main:app --port 8000`.") from None
        if r.status_code != 200:
            raise LiveError(f"Login as {user} failed ({r.status_code}): {r.text}. The demo "
                            "uses the seeded logins (see RUNNING.md).")
        self.tokens[user] = r.json()["access_token"]

    def call(self, user: str, method: str, path: str, ok=(200, 201, 202), **kw):
        r = self.http.request(method, path,
                              headers={"Authorization": f"Bearer {self.tokens[user]}"}, **kw)
        if r.status_code not in ok:
            raise LiveError(f"{user} {method} {path} -> {r.status_code}: {r.text[:400]}")
        return r.json() if r.content else None

    # ----------------------------------------------------------------- building blocks

    def move(self, to: str, why: str, override: str | None = None) -> None:
        body = {"to_stage": to}
        if override:
            body["override_justification"] = override
        res = self.call("bhavesh", "POST", f"/api/deals/{self.deal_id}/transition", json=body)
        passed = [e["guard_name"] for e in res["evaluations"]]
        over = [e["guard_name"] for e in res["evaluations"] if e.get("overridden_by")]
        note = f" (overrode {', '.join(over)})" if over else \
            (f" (guards passed: {', '.join(passed)})" if passed else "")
        self.stage = to
        self.say("bhavesh", f"moved the deal to {to} - {why}{note}", self.deal_url())
        if to == self.until and to != "CLOSED":
            raise StopHere
        self.wait()

    def upload(self, user: str, key: str, filename: str, doc_class: str, lines: list[str],
               executed: bool = False, sensitivity: int = 2) -> None:
        content = pdf_bytes(filename.rsplit(".", 1)[0],
                            [*lines, "", "Live demo placeholder - fictional entity."])
        doc = self.call(user, "POST", f"/api/deals/{self.deal_id}/documents",
                        files={"file": (filename, content, "application/pdf")},
                        data={"doc_class": doc_class, "sensitivity": str(sensitivity)})
        self.docs[key] = doc["id"]
        if executed:
            self.call(user, "PATCH", f"/api/documents/{doc['id']}", json={"is_executed": True})
        self.say(user, f"uploaded \"{filename}\"" + (" and marked it executed"
                                                     if executed else ""), self.deal_url())
        self.wait(0.5)

    def find_or_create_party(self, name: str, party_type: str, idents) -> int:
        for p in self.call("asha", "GET", "/api/parties"):
            if p["display_name"] == name:
                return p["id"]
        for _ in range(5):
            r = self.http.post("/api/parties", headers={
                "Authorization": f"Bearer {self.tokens['asha']}"},
                json={"party_type": party_type, "display_name": name,
                      "identifiers": idents()})
            if r.status_code == 201:
                return r.json()["id"]
            if r.status_code != 409:
                raise LiveError(f"creating party {name}: {r.status_code} {r.text}")
        raise LiveError(f"could not find free identifiers for {name}")

    def link(self, key: str, name: str, party_type: str, role: str, idents) -> None:
        pid = self.find_or_create_party(name, party_type, idents)
        self.parties[key] = pid
        self.call("asha", "POST", f"/api/deals/{self.deal_id}/parties",
                  json={"party_id": pid, "role": role})
        self.say("asha", f"linked {name} as {role}", self.deal_url())
        self.wait(0.5)

    def agent(self, inputs: dict, what: str) -> None:
        """Submit an agent job as the analyst, then wait for its handoff and its decision."""
        job = self.call("asha", "POST", "/api/jobs", json={"inputs": inputs,
                                                           "deal_id": self.deal_id})
        self.say("asha", f"asked the agents to {what} (job {job['id']}); on CPU this takes "
                 "30 s - 3 min", "/jobs")
        started, handoff, last_note = time.monotonic(), None, 0.0
        while handoff is None:
            time.sleep(3)
            state = self.call("asha", "GET", f"/api/jobs/{job['id']}")
            for h in self.call("bhavesh", "GET", "/api/handoffs?status=open"):
                if h.get("job_id") == job["id"]:
                    handoff = h
            if handoff is None and state["status"] in ("complete", "failed", "rejected"):
                self.say("agent", f"job {job['id']} ended '{state['status']}' without "
                         "proposing anything for a human (a small model sometimes does); "
                         "carrying on", "/jobs")
                return
            elapsed = time.monotonic() - started
            if elapsed - last_note >= 20:
                last_note = elapsed
                self.say("agent", f"still working on job {job['id']} ({int(elapsed)} s)")
            if elapsed > 900:
                self.say("agent", f"job {job['id']} is taking over 15 min; carrying on "
                         "without it")
                return
        self.decide(handoff)

    def decide(self, handoff: dict) -> None:
        dr = handoff["context_package"]["decision_required"]
        self.say("agent", f"handed a decision to the desk: \"{dr['question'][:110]}\"",
                 "/decisions")
        if self.auto_resolve_after is None:
            print(f"{'':20}Waiting for your decision in Decisions inbox (log in as "
                  "bhavesh) - no auto-resolve.", flush=True)
        else:
            print(f"{'':20}Waiting for your decision in Decisions inbox (log in as "
                  f"bhavesh) - or auto-resolving in {int(self.auto_resolve_after)} s",
                  flush=True)
        deadline = None if self.auto_resolve_after is None \
            else time.monotonic() + self.auto_resolve_after
        while deadline is None or time.monotonic() < deadline:
            h = self.call("bhavesh", "GET", f"/api/handoffs/{handoff['id']}")
            if h["status"] == "resolved":
                self.say(h["resolved_by"], f"resolved it in the portal: "
                         f"{h['directive']['decision']}", "/decisions")
                self.after_decision(handoff)
                return
            time.sleep(3)
        offered = [o["id"] for o in dr["options"]]
        decision = next((d for d in ("confirm", "approve", "verify") if d in offered),
                        dr.get("recommendation") or offered[0])
        self.call("bhavesh", "POST", f"/api/handoffs/{handoff['id']}/resolve", json={
            "decision": decision,
            "reasoning": "Auto-resolved by the live demo after the waiting window; the "
                         "proposal was read and is consistent with the deal file.",
            "new_constraints": {"do_not_revisit": []},
            "next_checkpoint": {"condition": "Next stage gate",
                                "escalate_if": "The proposal turns out to be wrong"}})
        self.say("bhavesh", f"resolved it (auto, after the waiting window): {decision}",
                 "/decisions")
        self.after_decision(handoff)

    def after_decision(self, handoff: dict) -> None:
        if not handoff.get("job_id"):
            return
        started = time.monotonic()
        while time.monotonic() - started < 300:
            state = self.call("asha", "GET", f"/api/jobs/{handoff['job_id']}")
            if state["status"] in ("complete", "rejected", "failed"):
                self.say("agent", f"job {handoff['job_id']} is now '{state['status']}'",
                         "/jobs")
                break
            time.sleep(3)
        self.wait()

    def diligence_item(self, keyword: str) -> dict | None:
        for item in self.call("asha", "GET", f"/api/deals/{self.deal_id}/diligence"):
            if keyword.lower() in item["prompt"].lower():
                return item
        return None

    # ----------------------------------------------------------------- the story

    def run(self) -> None:
        for user in LOGINS:
            self.login(user)
        ext = f"LIVE-{datetime.now():%Y%m%d-%H%M%S}"
        deal = self.call("bhavesh", "POST", "/api/deals", json={
            "external_id": ext, "transaction_class": "DEBT",
            "name": f"LIVE — {CLIENT.replace(' Pvt Ltd', '')} ₹60 Cr senior "
                    "secured debt"})
        self.deal_id = deal["id"]
        self.say("bhavesh", f"opened {ext}: {deal['name']}", self.deal_url())
        print(f"{'':20}open side by side: {self.ui}{self.deal_url()} , {self.ui}/decisions"
              f" , {self.ui}/activity (logged in as bhavesh)", flush=True)
        self.wait()
        self.call("priya", "POST", f"/api/deals/{self.deal_id}/members",
                  json={"username": "asha"})
        self.say("priya", "added asha (analyst) to the deal wall", self.deal_url())
        self.wait()

        r = self.http.post(f"/api/deals/{self.deal_id}/transition",
                           headers={"Authorization": f"Bearer {self.tokens['bhavesh']}"},
                           json={"to_stage": "QUALIFIED"})
        failed = [e["guard_name"] for e in r.json().get("evaluations", []) if not e["result"]]
        self.say("bhavesh", f"tried to qualify the deal - BLOCKED by {', '.join(failed)} "
                 "(no party with a statutory identifier yet); see Activity", "/activity")
        self.wait()

        pan = f"A{_rand(string.ascii_uppercase, 2)}CG{_rand(string.digits, 4)}" \
              f"{_rand(string.ascii_uppercase, 1)}"
        self.link("client", CLIENT, "company", "issuer", lambda: [
            {"scheme": "CIN", "value": f"U22209AP{random.randint(2005, 2018)}PTC"
                                       f"{_rand(string.digits, 6)}"},
            {"scheme": "PAN", "value": pan},
            {"scheme": "GSTIN", "value": f"37{pan}1Z{_rand(string.digits, 1)}"}])
        self.move("QUALIFIED", "the client now has a CIN, PAN and GSTIN on file")

        self.upload("asha", "engagement", "Engagement Letter - Godavari Polymers - "
                    "countersigned.pdf", "engagement_letter",
                    ["Debt advisory mandate for a INR 60 Cr senior secured facility"],
                    executed=True)
        self.move("MANDATED", "engagement letter executed")

        self.call("asha", "POST", f"/api/deals/{self.deal_id}/mandates", json={
            "title": "Raise ₹60 Cr senior secured term debt", "side": "raise",
            "notes": "Capex for a 24,000 TPA PET resin line in Kakinada.",
            "criteria": [
                {"criterion_key": "facility_amount_inr", "operator": "between",
                 "value": [550000000, 650000000], "hardness": "hard"},
                {"criterion_key": "tenor_months", "operator": "gte", "value": 60,
                 "hardness": "hard"},
                {"criterion_key": "pricing_pct", "operator": "lte", "value": 10.5,
                 "hardness": "soft", "weight": 0.7}]})
        self.say("asha", "recorded the mandate with two hard criteria", self.deal_url())
        self.wait(0.5)
        self.move("PREPARED", "mandate has a hard criterion")

        self.upload("asha", "fs", "FY26 Audited Financial Statements - Godavari "
                    "Polymers.pdf", "financial_statement",
                    ["Revenue from operations: 2,86,40,00,000", "EBITDA: 37,90,00,000",
                     "Net debt: 92,10,00,000"])
        self.agent({"capability": "classify_document", "document_id": self.docs["fs"]},
                   "classify the financial statements")
        self.move("MARKETED", "financial statements on file")

        def trust_pan():
            return [{"scheme": "PAN", "value": f"AA{_rand(string.ascii_uppercase, 1)}T"
                     f"N{_rand(string.digits, 4)}{_rand(string.ascii_uppercase, 1)}"}]
        self.link("lender1", "Narmada Credit Fund", "fund", "lender", trust_pan)
        self.upload("asha", "nda", "NDA - Narmada Credit Fund and Godavari Polymers - "
                    "executed.pdf", "nda", ["Mutual NDA, 24 months"], executed=True)
        self.move("MATCHED", "a lender is linked and the NDA is executed")
        self.agent({"capability": "draft_email", "party_id": self.parties["lender1"],
                    "brief": "Share the credit summary and ask for indicative terms."},
                   "draft an intro email to Narmada Credit Fund")

        self.link("lender2", "Vindhya Capital Partners", "fund", "lender", trust_pan)
        self.move("BID_AUCTION", "two lenders in the process")
        self.upload("asha", "valuation", "Techno-Economic Viability Study - Godavari "
                    "Polymers.pdf", "valuation_report", ["DSCR 1.52x, asset cover 1.7x"])
        self.move("NEGOTIATION", "valuation report on file")
        self.upload("asha", "term_sheet", "Term Sheet - Narmada Credit Fund - signed.pdf",
                    "term_sheet", ["INR 60 Cr, 72 months, 10.2%"], executed=True,
                    sensitivity=3)
        self.move("DILIGENCE", "term sheet executed; the checklist is created")

        flags = ["Environment: plastic EPR registration (CPCB)"]
        self.call("priya", "PATCH", f"/api/deals/{self.deal_id}",
                  json={"regulatory_flags": flags})
        self.say("priya", f"flagged the deal: {flags[0]}", self.deal_url())
        self.wait(0.5)
        evidence = [("incorporation", "moa", "Certificate of Incorporation and MoA-AoA - "
                     "Godavari Polymers.pdf", "moa_aoa"),
                    ("litigation", "lit", "Litigation Schedule - Godavari Polymers.pdf",
                     "litigation_summary"),
                    ("tax returns", "tax", "ITR AY2024-26 - Godavari Polymers.pdf",
                     "tax_return"),
                    ("board and shareholder", "board", "Board Resolution - Godavari "
                     "Polymers.pdf", "board_resolution"),
                    ("security documents", "sec", "Deed of Hypothecation - Godavari "
                     "Polymers.pdf", "charge_document"),
                    ("debt schedule", "bank", "Debt Schedule and Bank Statements - Godavari "
                     "Polymers.pdf", "bank_statement")]
        for keyword, key, fname, dclass in evidence:
            self.upload("asha", key, fname, dclass, [fname.rsplit(".", 1)[0]])
            item = self.diligence_item(keyword)
            if item:
                self.call("asha", "PATCH", f"/api/diligence/{item['id']}",
                          json={"status": "satisfied", "evidence_doc_ids": [self.docs[key]]})
                self.say("asha", f"diligence item satisfied: {item['prompt']}",
                         self.deal_url())
                self.wait(0.3)
        item = self.diligence_item("audited financial")
        if item:
            self.call("asha", "PATCH", f"/api/diligence/{item['id']}",
                      json={"status": "satisfied", "evidence_doc_ids": [self.docs["fs"]]})
            self.call("asha", "POST", f"/api/deals/{self.deal_id}/findings", json={
                "diligence_item_id": item["id"], "finding_type": "adjustment",
                "description": "Capex creditors of ₹4.2 Cr classified as trade payables; "
                               "net debt restated upward.",
                "quantified_impact_inr": 42000000, "affects_valuation": True})
            self.say("asha", "raised a finding: ₹4.2 Cr net-debt adjustment",
                     self.deal_url())
            self.wait(0.5)
        self.call("priya", "POST", f"/api/deals/{self.deal_id}/signoffs", json={
            "note": "EPR registration and consent to operate checked; no objection."})
        self.say("priya", "signed the deal off for compliance", self.deal_url())
        self.wait(0.5)
        self.move("DOCUMENTATION", "no open blockers and compliance has signed off")

        self.upload("asha", "definitive", "Facility Agreement and Deed of Hypothecation - "
                    "Narmada Credit Fund - executed.pdf", "charge_document",
                    ["Executed loan and security documents"], executed=True, sensitivity=3)
        self.move("CONDITIONS_PRECEDENT", "loan documents executed", override=(
            f"Debt deal: the definitive documents are the facility agreement and deed of "
            f"hypothecation (document #{self.docs['definitive']}, executed). T10 only "
            f"recognises an SPA or SHPA."))
        cps = []
        for desc, kind in [("Creation of charge and Form CHG-1 filing", "regulatory"),
                           ("Insurance of plant with lender as loss payee", "commercial")]:
            cp = self.call("asha", "POST", f"/api/deals/{self.deal_id}/conditions",
                           json={"description": desc, "cp_type": kind})
            cps.append(cp)
            self.say("asha", f"added condition precedent: {desc}", self.deal_url())
            self.wait(0.3)
        for cp in cps:
            self.call("asha", "PATCH", f"/api/conditions/{cp['id']}",
                      json={"status": "satisfied"})
            self.say("asha", f"condition satisfied: {cp['description']}", self.deal_url())
            self.wait(0.3)
        self.move("CLOSED", "every condition precedent is satisfied")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m aura.data.live_demo", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--api", default="http://localhost:8000")
    ap.add_argument("--ui", default="http://localhost:3000", help="portal URL to print")
    ap.add_argument("--pace", type=float, default=8.0, help="seconds between steps")
    ap.add_argument("--fast", action="store_true", help="same as --pace 2")
    ap.add_argument("--until", choices=STAGES[1:], default="CLOSED",
                    help="stop once the deal reaches this stage")
    ap.add_argument("--auto-resolve-after", type=float, default=120.0,
                    help="seconds to wait for a human decision before resolving as bhavesh")
    ap.add_argument("--wait-for-human", action="store_true",
                    help="never auto-resolve; wait for a decision in the portal")
    args = ap.parse_args(argv)
    driver = Driver(args.api, args.ui, 2.0 if args.fast else args.pace, args.until,
                    None if args.wait_for_human else args.auto_resolve_after)
    try:
        driver.run()
        print(f"Done: the deal is at {driver.stage}. {args.ui}{driver.deal_url()}")
        return 0
    except StopHere:
        print(f"Stopped at {driver.stage} as asked (--until). {args.ui}{driver.deal_url()}")
        return 0
    except KeyboardInterrupt:
        where = f" {args.ui}{driver.deal_url()}" if driver.deal_id else ""
        print(f"\nStopped by you. The deal is valid and stays at {driver.stage}.{where}")
        return 130
    except LiveError as exc:
        print(f"Live demo stopped: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
