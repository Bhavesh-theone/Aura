"""The Story DSL for the demo dataset: one Story per deal, each step a scheduled event that
calls a real core service as a named user. See aura.data.demo for the scenarios."""
from __future__ import annotations

from datetime import date, datetime
from typing import Callable

from aura.api.security import hash_password
from aura.config import get_settings
from aura.core.domain.enums import (AssignmentMode, CPStatus, CriterionHardness,
                                    CriterionOperator, DealStage, DiligenceStatus, DocClass,
                                    FindingType, HandoffDirection, HandoffStatus,
                                    HandoffTrigger, MandateSide, MandateStatus, PartyRole,
                                    PartyType, Role, SegmentStatus, TransactionClass)
from aura.core.domain.mandate import MandateCriterion
from aura.core.domain.party import PartyIdentifier
from aura.core.domain.enums import IdentifierScheme
from aura.core.policy.rbac_policy import Capability, require
from aura.core.services import (compliance, create_deal, diligence, documents, handoffs,
                                mandates, parties, submit_job, transition_deal, users, walls)
from aura.core.services.run_segment import run_segment
from aura.data.demo_engine import Desk, NullEvents, at
from aura.data.run_sink import SqlAgentRunSink
from aura.data.uow import SqlUnitOfWork
from aura.data.walls import SYSTEM

S = DealStage

# username -> (password, role). The seeded four plus the demo team.
TEAM = {
    "bhavesh": ("admin123", Role.DEALMAKER),
    "asha": ("analyst123", Role.ANALYST),
    "priya": ("compliance123", Role.COMPLIANCE),
    "admin": ("admin123", Role.ADMIN),
    "vikram": ("dealmaker123", Role.DEALMAKER),
    "neha": ("dealmaker123", Role.DEALMAKER),
    "rohan": ("analyst123", Role.ANALYST),
    "kavya": ("analyst123", Role.ANALYST),
    "meera": ("compliance123", Role.COMPLIANCE),
}
NEW_USERS = ["vikram", "neha", "rohan", "kavya", "meera"]


def role_of(username: str) -> Role:
    return TEAM[username][1]


def add_users(desk: Desk, day: date) -> None:
    """The admin onboards the demo team. Skips anyone who already exists."""
    def run():
        r = desk.repos(SYSTEM)
        for name in NEW_USERS:
            if r.users.get_by_username(name) is None:
                password, role = TEAM[name]
                users.create_user(name, password, role, "admin", Role.ADMIN, r.users,
                                  r.audit, hash_password)
    desk.schedule(at(day, "09:10"), "team onboarded", run)


# --------------------------------------------------------------------------- parties

PT, ID = PartyType, IdentifierScheme

# key -> (type, display name, short name, [(scheme, value)]). All fictional.
PARTIES: dict[str, tuple[PartyType, str, str, list[tuple[IdentifierScheme, str]]]] = {
    "saurashtra": (PT.COMPANY, "Saurashtra Spinning Mills Pvt Ltd", "Saurashtra Spinning",
                   [(ID.CIN, "U13111GJ2009PTC057814"), (ID.PAN, "AAKCS4821M"),
                    (ID.GSTIN, "24AAKCS4821M1Z3")]),
    "narmada": (PT.FUND, "Narmada Credit Fund", "Narmada Credit Fund",
                [(ID.PAN, "AAATN7310Q")]),
    "ujjayini": (PT.COMPANY, "Ujjayini Small Finance Bank Ltd", "Ujjayini SFB",
                 [(ID.CIN, "U65923MP2016PLC041276"), (ID.PAN, "AABCU6502H")]),
    "desai_mehta": (PT.PARTNERSHIP, "Desai Mehta & Associates", "Desai Mehta & Associates",
                    [(ID.PAN, "AAFFD3318L")]),
    "panchal": (PT.COMPANY, "Panchal Ceramica Pvt Ltd", "Panchal Ceramica",
                [(ID.CIN, "U23931GJ2012PTC071406"), (ID.PAN, "AAGCP9184E"),
                 (ID.GSTIN, "24AAGCP9184E1Z8")]),
    "vindhya": (PT.FUND, "Vindhya Capital Partners", "Vindhya Capital",
                [(ID.PAN, "AAATV2207N")]),
    "tungabhadra": (PT.COMPANY, "Tungabhadra Fincorp Pvt Ltd", "Tungabhadra Fincorp",
                    [(ID.CIN, "U65921KA2014PTC093117"), (ID.PAN, "AAFCT5560R"),
                     (ID.GSTIN, "29AAFCT5560R1Z2")]),
    "shivneri": (PT.COMPANY, "Shivneri Cloud Systems Pvt Ltd", "Shivneri Cloud",
                 [(ID.CIN, "U62011MH2017PTC298345"), (ID.PAN, "ABACS7719K"),
                  (ID.GSTIN, "27ABACS7719K1ZQ")]),
    "lumen_ridge": (PT.FOREIGN_ENTITY, "Lumen Ridge Ventures Pte Ltd (Singapore)",
                    "Lumen Ridge", []),
    "aravalli": (PT.FUND, "Aravalli Growth Opportunities Fund (Category II AIF)",
                 "Aravalli Growth Fund", [(ID.PAN, "AACTA4590D")]),
    "sahyadri": (PT.FUND, "Sahyadri Impact Fund", "Sahyadri Impact Fund",
                 [(ID.PAN, "AACTS6098K")]),
    "malabar": (PT.COMPANY, "Malabar Spice & Condiments Ltd", "Malabar Spice",
                [(ID.CIN, "U10795KL2008PLC022931"), (ID.PAN, "AAECM3346G"),
                 (ID.GSTIN, "32AAECM3346G1ZK")]),
    "coromandel": (PT.FUND, "Coromandel Early Stage Fund", "Coromandel Fund",
                   [(ID.PAN, "AACTC8812F")]),
    "nilgiri": (PT.LLP, "Nilgiri Family Office LLP", "Nilgiri Family Office",
                [(ID.LLPIN, "AAN-4821"), (ID.PAN, "AAOFN4821B")]),
    "ankleshwar": (PT.COMPANY, "Ankleshwar Organics Ltd", "Ankleshwar Organics",
                   [(ID.CIN, "L20119GJ1994PLC021587"), (ID.PAN, "AAACA6123P"),
                    (ID.GSTIN, "24AAACA6123P1ZM")]),
    "bharuch": (PT.COMPANY, "Bharuch Fine Chemicals Pvt Ltd", "Bharuch Fine Chemicals",
                [(ID.CIN, "U20119GJ2011PTC064802"), (ID.PAN, "AADCB8840J")]),
    "vapi": (PT.COMPANY, "Vapi Speciality Molecules Pvt Ltd", "Vapi Speciality Molecules",
             [(ID.CIN, "U20299GJ2015PTC083356"), (ID.PAN, "AAHCV1172C")]),
    "pranhita": (PT.COMPANY, "Pranhita Steel Re-Rollers Pvt Ltd", "Pranhita Steel",
                 [(ID.CIN, "U24106TG2007PTC054418"), (ID.PAN, "AAFCP2290L")]),
    "gondwana": (PT.COMPANY, "Gondwana Metals Ltd", "Gondwana Metals",
                 [(ID.CIN, "U24109MH2005PLC151760"), (ID.PAN, "AABCG6635A")]),
    "deccan": (PT.COMPANY, "Deccan Agro Foods Ltd", "Deccan Agro Foods",
               [(ID.CIN, "U10612TG2010PLC067743"), (ID.PAN, "AACCD4417H"),
                (ID.GSTIN, "36AACCD4417H1ZT")]),
    "satpura": (PT.COMPANY, "Satpura Motion Controls Pvt Ltd", "Satpura Motion Controls",
                [(ID.CIN, "U27101MP2013PTC031920"), (ID.PAN, "AAKCS6650D"),
                 (ID.GSTIN, "23AAKCS6650D1Z9")]),
    "rheintal": (PT.FOREIGN_ENTITY, "Rheintal Antriebstechnik GmbH (Germany)", "Rheintal",
                 []),
    "noyyal": (PT.COMPANY, "Noyyal Knit Exports Pvt Ltd", "Noyyal Knit Exports",
               [(ID.CIN, "U14301TN2006PTC060215"), (ID.PAN, "AACCN5108G"),
                (ID.GSTIN, "33AACCN5108G1ZB")]),
    "brahmaputra": (PT.COMPANY, "Brahmaputra Retail Distribution Pvt Ltd",
                    "Brahmaputra Retail", [(ID.CIN, "U47190AS2014PTC015542"),
                                           (ID.PAN, "AAGCB3391E")]),
    "vidarbha": (PT.COMPANY, "Vidarbha Apparel Retail Pvt Ltd", "Vidarbha Apparel Retail",
                 [(ID.CIN, "U47711MH2016PTC284409"), (ID.PAN, "AAHCV9037M")]),
    "sabarmati": (PT.COMPANY, "Sabarmati Corrugated Packaging Pvt Ltd", "Sabarmati Packaging",
                  [(ID.CIN, "U17021GJ2010PTC060933"), (ID.PAN, "AAICS2245Q")]),
    "kalinga": (PT.COMPANY, "Kalinga Consumer Products Ltd", "Kalinga Consumer",
                [(ID.CIN, "U20231OR2003PLC007218"), (ID.PAN, "AABCK7314N")]),
    "kutch": (PT.COMPANY, "Kutch Marine Salts Pvt Ltd", "Kutch Marine Salts",
              [(ID.CIN, "U08931GJ2011PTC066190"), (ID.PAN, "AAJCK1820H")]),
    "chambal": (PT.COMPANY, "Chambal Agro Warehousing Pvt Ltd", "Chambal Agro Warehousing",
                [(ID.CIN, "U52109RJ2015PTC048871"), (ID.PAN, "AAMCC4467P")]),
    "chilika": (PT.COMPANY, "Chilika Aqua Exports Pvt Ltd", "Chilika Aqua",
                [(ID.CIN, "U10202OR2009PTC010954"), (ID.PAN, "AADCC7781J")]),
    "bundelkhand": (PT.COMPANY, "Bundelkhand Solar Parks Pvt Ltd", "Bundelkhand Solar",
                    [(ID.CIN, "U35106UP2019PTC118342"), (ID.PAN, "AAKCB5529F")]),
    "konkan": (PT.LLP, "Konkan Coastal Logistics LLP", "Konkan Coastal Logistics",
               [(ID.LLPIN, "AAQ-7716"), (ID.PAN, "AAUFK7716C")]),
    "sindhu_law": (PT.PARTNERSHIP, "Sindhu Legal LLP Advocates", "Sindhu Legal",
                   [(ID.PAN, "AAFFS2614R")]),
}

# Default deliverable that the T10 guard needs, by class; others are overridden.
DEFINITIVE = {DocClass.SPA, DocClass.SHPA}


def directive(decision: str, reasoning: str, condition: str, escalate_if: str,
              do_not_revisit: list[str] | None = None) -> dict:
    return {"decision": decision, "reasoning": reasoning,
            "new_constraints": {"do_not_revisit": do_not_revisit or []},
            "next_checkpoint": {"condition": condition, "escalate_if": escalate_if}}


def crit(key, op, value, hardness="hard", weight=None) -> MandateCriterion:
    return MandateCriterion(key, CriterionOperator(op), value, CriterionHardness(hardness),
                            weight)


class Story:
    """One deal's events. Every step acts as a named user, through the services."""

    def __init__(self, desk: Desk, days: list[date], ext: str, name: str,
                 cls: TransactionClass, owner: str, analyst: str, client: str,
                 client_role: PartyRole, counterparties: list[tuple[str, PartyRole]] = (),
                 counsel: str | None = None):
        self.desk, self.days, self.ext, self.name, self.cls = desk, days, ext, name, cls
        self.owner, self.analyst, self.client, self.client_role = owner, analyst, client, \
            client_role
        self.counterparties, self.counsel = list(counterparties), counsel
        self.short = PARTIES[client][2]
        self.deal_id: int | None = None
        self.docs: dict[str, int] = {}
        self.party_ids: dict[str, int] = {}
        self.doc_names: dict[str, str] = {}
        self.cps: dict[str, int] = {}
        self.jobs: dict[str, int] = {}
        self.handoffs: dict[str, int | None] = {}
        self._prepared: set[DealStage] = set()
        self.final_stage: DealStage | None = None

    # ------------------------------------------------------------------ plumbing

    def when(self, day: int, hhmm: str) -> datetime:
        return at(self.days[day], hhmm)

    def _at(self, day: int, hhmm: str, label: str, fn: Callable[[], None],
            expect_block: bool = False) -> None:
        self.desk.schedule(self.when(day, hhmm), f"{self.ext} {label}", fn, expect_block)

    def r(self, user):
        return self.desk.repos(user)

    def date_str(self, day: int) -> str:
        return self.days[day].strftime("%d %b %Y")

    # ------------------------------------------------------------------ steps

    def create(self, day: int, hhmm: str = "10:00") -> None:
        def run():
            r = self.r(self.owner)
            deal = create_deal.create_deal(self.ext, self.name, self.cls, self.owner,
                                           role_of(self.owner), r.deals, r.history, r.audit,
                                           r.walls, r.users)
            self.deal_id = deal.id
        self._at(day, hhmm, "created", run)

    def staff(self, day: int, add: list[str] = (), remove: list[str] = (),
              by: str = "priya", hhmm: str = "10:20") -> None:
        def run():
            r = self.r(by)
            for u in add:
                walls.add_member(self.deal_id, u, by, role_of(by), r.deals, r.walls, r.users,
                                 r.audit)
            for u in remove:
                walls.remove_member(self.deal_id, u, by, role_of(by), r.deals, r.walls,
                                    r.audit)
        self._at(day, hhmm, "wall staffed", run)

    def party(self, day: int, key: str, role: PartyRole, by: str | None = None,
              hhmm: str = "10:30") -> None:
        by = by or self.analyst

        def run():
            r = self.r(by)
            ptype, display, _, idents = PARTIES[key]
            party = None
            for scheme, value in idents:
                party = r.parties.find_by_identifier(scheme.value, value)
                if party:
                    break
            if party is None and not idents:
                party = next((p for p in r.parties.list_all()
                              if p.display_name == display), None)
            if party is None:
                party = parties.create_party(ptype, display,
                                             [PartyIdentifier(s, v) for s, v in idents],
                                             by, role_of(by), r.parties, r.audit)
            self.party_ids[key] = party.id
            if any(p.party_id == party.id and p.role is role
                   for p in r.parties.list_for_deal(self.deal_id)):
                return
            parties.link_party(self.deal_id, party.id, role, by, role_of(by), r.deals,
                               r.parties, r.audit)
        self._at(day, hhmm, f"party {key} as {role.value}", run)

    def doc(self, day: int, key: str, filename: str, doc_class: DocClass,
            lines: list[str] | Callable[[], list[str]], executed: bool = False,
            upsi: bool = False, sensitivity: int = 2, by: str | None = None,
            hhmm: str = "11:00") -> None:
        by = by or self.analyst

        def run():
            from aura.data.pdf import pdf_bytes
            r = self.r(by)
            body = lines() if callable(lines) else lines
            title = filename.rsplit(".", 1)[0]
            content = pdf_bytes(title, [*body, "",
                                        f"Deal reference: {self.ext}",
                                        f"Dated: {self.date_str(day)}",
                                        "Demo placeholder - all entities and figures are "
                                        "fictional."])
            doc = documents.upload_document(self.deal_id, filename, content, doc_class, upsi,
                                            sensitivity, by, role_of(by), r.deals,
                                            r.documents, self.desk.store, r.audit)
            self.docs[key], self.doc_names[key] = doc.id, filename
            if executed:
                documents.update_document(doc.id, True, None, by, role_of(by), r.documents,
                                          r.audit)
        self._at(day, hhmm, f"document {key}", run)

    def execute(self, day: int, key: str, by: str | None = None, hhmm: str = "15:00") -> None:
        by = by or self.analyst

        def run():
            r = self.r(by)
            documents.update_document(self.docs[key], True, None, by, role_of(by),
                                      r.documents, r.audit)
        self._at(day, hhmm, f"document {key} executed", run)

    def view(self, day: int, key: str, by: str, hhmm: str = "12:15") -> None:
        def run():
            r = self.r(by)
            documents.view_document(self.docs[key], by, r.documents, r.audit)
        self._at(day, hhmm, f"document {key} viewed", run)

    def mandate(self, day: int, title: str, side: MandateSide, criteria: list,
                notes: str, by: str | None = None, hhmm: str = "11:30") -> None:
        by = by or self.analyst

        def run():
            r = self.r(by)
            mandates.create_mandate(self.deal_id, title, notes, side, MandateStatus.ACTIVE,
                                    criteria, by, role_of(by), r.deals, r.mandates, r.audit)
        self._at(day, hhmm, "mandate", run)

    def move(self, day: int, to: DealStage, by: str | None = None, reason: str | None = None,
             override: str | Callable[[], str] | None = None, expect_block: bool = False,
             hhmm: str = "16:00") -> None:
        by = by or self.owner

        def run():
            r = self.r(by)
            justification = override() if callable(override) else override
            transition_deal.transition_deal(self.deal_id, to, by, role_of(by), reason,
                                            justification, r.deals, r.history, r.guards,
                                            r.diligence, r.audit)
        if not expect_block:
            self.final_stage = to
        self._at(day, hhmm, f"move to {to.value}", run, expect_block)

    def flags(self, day: int, flags: list[str], by: str | None = None,
              hhmm: str = "12:00") -> None:
        by = by or self.owner

        def run():
            r = self.r(by)
            compliance.set_regulatory_flags(self.deal_id, flags, by, role_of(by), r.deals,
                                            r.audit)
        self._at(day, hhmm, "regulatory flags", run)

    def signoff(self, day: int, note: str, by: str = "priya", hhmm: str = "15:30") -> None:
        def run():
            r = self.r(by)
            compliance.add_signoff(self.deal_id, note, by, role_of(by), r.deals, r.signoffs,
                                   r.audit)
        self._at(day, hhmm, "compliance sign-off", run)

    def _item(self, r, keyword: str):
        for item in r.diligence.list_items(self.deal_id):
            if keyword.lower() in item.prompt.lower():
                return item
        return None

    def dd(self, day: int, keyword: str, status: str, evidence: list[str] = (),
           waiver: str | None = None, by: str | None = None, hhmm: str = "14:00") -> None:
        by = by or self.analyst

        def run():
            r = self.r(by)
            item = self._item(r, keyword)
            if item is None:
                self.desk.log(f"  {self.ext}: no diligence item matching {keyword!r}; skipped")
                return
            diligence.update_diligence_item(
                item.id, DiligenceStatus(status),
                [self.docs[k] for k in evidence] if evidence else None, waiver, by,
                role_of(by), r.diligence, r.documents, r.audit)
        self._at(day, hhmm, f"diligence {keyword} -> {status}", run)

    def finding(self, day: int, keyword: str, ftype: FindingType, description: str,
                impact_inr: int | None, affects_valuation: bool, by: str | None = None,
                hhmm: str = "15:10") -> None:
        by = by or self.analyst

        def run():
            r = self.r(by)
            item = self._item(r, keyword)
            if item is None:
                return
            diligence.add_finding(self.deal_id, item.id, ftype, description, impact_inr,
                                  affects_valuation, by, role_of(by), r.deals, r.diligence,
                                  r.findings, r.audit)
        self._at(day, hhmm, f"finding on {keyword}", run)

    def cp(self, day: int, key: str, description: str, cp_type: str, by: str | None = None,
           hhmm: str = "15:00") -> None:
        by = by or self.analyst

        def run():
            r = self.r(by)
            self.cps[key] = diligence.add_condition(self.deal_id, description, cp_type, by,
                                                    role_of(by), r.deals, r.conditions,
                                                    r.audit).id
        self._at(day, hhmm, f"condition {key}", run)

    def cp_set(self, day: int, key: str, status: str, waiver: str | None = None,
               by: str | None = None, hhmm: str = "13:00") -> None:
        by = by or self.analyst

        def run():
            r = self.r(by)
            diligence.update_condition(self.cps[key], CPStatus(status), waiver, by,
                                       role_of(by), r.conditions, r.audit)
        self._at(day, hhmm, f"condition {key} -> {status}", run)

    # ------------------------------------------------------------------ agents

    def _run_queued(self, job_id: int, live: bool) -> None:
        desk = self.desk
        orch = desk.live_orchestrator if (live and desk.live_orchestrator) else desk.orchestrator
        sysr = desk.repos(SYSTEM)
        for _ in range(5):  # a decision can queue a follow-on segment; run that too
            queued = [g for g in sysr.segments.list_for_job(job_id)
                      if g.status is SegmentStatus.QUEUED]
            if not queued:
                return
            for seg in queued:
                run_segment(seg.id, orch, sysr.jobs, sysr.segments, sysr.tasks,
                            sysr.handoffs, sysr.audit, NullEvents(),
                            SqlAgentRunSink(desk.s), SqlUnitOfWork(desk.s),
                            materiality_cap_inr=get_settings().materiality_cap_inr,
                            extractions=sysr.extractions, documents=sysr.documents)

    def job(self, day: int, key: str, inputs: Callable[[], dict], by: str | None = None,
            live: bool = False, hhmm: str = "12:40") -> None:
        """Submit an agent job on the deal and run it the way the worker would."""
        by = by or self.analyst

        def run():
            r = self.r(by)
            job = submit_job.submit_job(inputs(), self.deal_id, by, role_of(by), r.jobs,
                                        r.segments, r.audit, NullEvents(), r.deals,
                                        r.documents, r.parties, self.desk.store)
            self.desk.s.commit()
            if live and self.desk.live_orchestrator:
                self.desk.log(f"  {self.ext}: running job {job.id} on the live model "
                              "(this takes 30 s - 3 min on CPU)...")
            self._run_queued(job.id, live)
            self.jobs[key] = job.id
            sysr = self.desk.repos(SYSTEM)
            self.handoffs[key] = next((h.id for h in sysr.handoffs.list_all(False)
                                       if h.job_id == job.id), None)
        self._at(day, hhmm, f"agent job {key}", run)

    def resolve(self, day: int, key: str, decisions: list[str], reasoning: str,
                condition: str, escalate_if: str, do_not_revisit: list[str] | None = None,
                by: str | None = None, hhmm: str = "17:30") -> None:
        """Resolve the handoff a job (or a manual brief) produced, choosing the first of
        `decisions` that the handoff offers. A job that produced no handoff is left be."""
        by = by or self.owner

        def run():
            hid = self.handoffs.get(key)
            if hid is None:
                return
            r = self.r(by)
            h = r.handoffs.get(hid)
            if h is None or h.status is HandoffStatus.RESOLVED:
                return
            offered = [o["id"] for o in h.context_package["decision_required"]["options"]]
            decision = next((d for d in decisions if d in offered), offered[0])
            handoffs.resolve_handoff(hid, directive(decision, reasoning, condition,
                                                    escalate_if, do_not_revisit),
                                     by, role_of(by), r.jobs, r.segments, r.tasks, r.handoffs,
                                     r.documents, r.audit, NullEvents(),
                                     extractions=r.extractions)
            if h.job_id is not None:
                self.desk.s.commit()
                self._run_queued(h.job_id, False)
        self._at(day, hhmm, f"resolve {key}", run)

    def brief(self, day: int, key: str, task_type: str, trigger: HandoffTrigger,
              package: Callable[[datetime], dict], materiality_inr: int | None,
              by: str | None = None, hhmm: str = "11:45") -> None:
        """A decision brief prepared for a human, through the handoff service."""
        by = by or self.analyst

        def run():
            r = self.r(by)
            require(role_of(by), Capability.EDIT_DEAL_DATA, "create handoffs")
            created = self.desk.clock.now()
            h = handoffs.create_handoff(
                deal_id=self.deal_id, job_id=None, task_type=task_type,
                assignment_mode=AssignmentMode.HUMAN_REQUIRED,
                direction=HandoffDirection.BOT_TO_HUMAN, trigger=trigger,
                context_package=package(created), directive=None,
                materiality_inr=materiality_inr, actor=by, tasks=r.tasks, handoffs=r.handoffs,
                audit=r.audit, events=NullEvents(), deals=r.deals, now=created)
            self.handoffs[key] = h.id
        self._at(day, hhmm, f"decision brief {key}", run)

    def ev(self, key: str, note: str) -> dict:
        return {"type": "document", "document_id": self.docs[key],
                "summary": f"Document #{self.docs[key]} - {self.doc_names[key]}: {note}"}

    # ------------------------------------------------------------------ the spine

    def walk(self, plan: list[tuple[int, DealStage]], *, mandate: tuple | None = None,
             financials: list[tuple[str, str, DocClass, list[str]]] = (),
             valuation: tuple[str, list[str], bool] | None = None,
             term_sheet: tuple[str, list[str]] | None = None,
             definitive: tuple[str, DocClass, list[str]] | None = None,
             overrides: dict[DealStage, str | Callable[[], str]] | None = None,
             movers: dict[DealStage, str] | None = None) -> None:
        """Move forward stage by stage, putting in place what each guard asks for first.
        A stage reached a second time (after a regression) is just moved to."""
        overrides, movers = overrides or {}, movers or {}
        cps = [c for c in self.counterparties]
        for day, stage in plan:
            first = stage not in self._prepared
            self._prepared.add(stage)
            if first and stage is S.QUALIFIED:
                self.party(day, self.client, self.client_role, hhmm="10:30")
                if self.counsel:
                    self.party(day, self.counsel, PartyRole.COUNSEL, hhmm="10:40")
            elif first and stage is S.MANDATED:
                self.doc(day, "engagement", f"Engagement Letter - {self.short} - "
                         "countersigned.pdf", DocClass.ENGAGEMENT_LETTER,
                         [f"Engagement of the advisory desk by {PARTIES[self.client][1]}",
                          f"Scope: {self.name}",
                          "Retainer and success fee as per Schedule 1",
                          "Countersigned by both parties"], executed=True)
            elif first and stage is S.PREPARED and mandate:
                title, side, criteria, notes = mandate
                self.mandate(day, title, side, criteria, notes)
            elif first and stage is S.MARKETED:
                for i, (key, fname, dclass, lines) in enumerate(financials):
                    self.doc(day, key, fname, dclass, lines, hhmm=f"10:{45 + i * 5:02d}")
            elif first and stage is S.MATCHED and cps:
                key, role = cps[0]
                self.party(day, key, role, hhmm="11:00")
                self.doc(day, "nda", f"NDA - {PARTIES[key][2]} and {self.short} - "
                         "executed.pdf", DocClass.NDA,
                         [f"Mutual non-disclosure agreement between {PARTIES[key][1]} and "
                          f"{PARTIES[self.client][1]}", "Term: 24 months",
                          "Non-solicitation of employees: 12 months"],
                         executed=True, hhmm="12:30")
            elif first and stage is S.BID_AUCTION:
                for i, (key, role) in enumerate(cps[1:]):
                    self.party(day, key, role, hhmm=f"11:{i * 10:02d}")
            elif first and stage is S.NEGOTIATION and valuation:
                fname, lines, upsi = valuation
                self.doc(day, "valuation", fname, DocClass.VALUATION_REPORT, lines,
                         upsi=upsi, sensitivity=4 if upsi else 3, hhmm="12:00")
            elif first and stage is S.DILIGENCE and term_sheet:
                fname, lines = term_sheet
                self.doc(day, "term_sheet", fname, DocClass.TERM_SHEET, lines, executed=True,
                         sensitivity=3, hhmm="11:00")
            elif first and stage is S.CONDITIONS_PRECEDENT and definitive:
                fname, dclass, lines = definitive
                self.doc(day, "definitive", fname, dclass, lines, executed=True,
                         sensitivity=3, hhmm="11:30")
            self.move(day, stage, by=movers.get(stage), override=overrides.get(stage),
                      hhmm="16:30" if stage is not S.CONDITIONS_PRECEDENT else "14:00")

    def standard_diligence(self, d0: int, d1: int, skip: tuple[str, ...] = (),
                           by: str | None = None) -> None:
        """Upload the evidence the base checklist asks for, request every item, and work
        each to satisfied between d0 and d1. Items named in `skip` are left to the story."""
        by = by or self.analyst
        c = PARTIES[self.client][1]
        evidence = [
            ("incorporation", "moa", f"Certificate of Incorporation, MoA and AoA - "
             f"{self.short}.pdf", DocClass.MOA_AOA,
             [f"Certificate of incorporation of {c}", "Memorandum and Articles of "
              "Association as amended"]),
            ("litigation", "litigation", f"Litigation and Regulatory Proceedings Schedule - "
             f"{self.short}.pdf", DocClass.LITIGATION_SUMMARY,
             [f"Pending proceedings involving {c}", "Certified by the company secretary"]),
            ("tax returns", "tax", f"ITR and Assessment Orders AY2024-26 - {self.short}.pdf",
             DocClass.TAX_RETURN, ["Income tax returns AY 2024-25 and 2025-26",
                                   "Assessment orders under section 143(3)"]),
            ("board and shareholder", "board_res", f"Board Resolution approving the "
             f"transaction - {self.short}.pdf", DocClass.BOARD_RESOLUTION,
             [f"Certified true copy of the resolution of the board of {c}"]),
        ]
        if self.cls is TransactionClass.DEBT:
            evidence += [
                ("security documents", "security", f"Deed of Hypothecation and CHG-1 "
                 f"particulars - {self.short}.pdf", DocClass.CHARGE_DOCUMENT,
                 ["Draft deed of hypothecation over current assets",
                  "Particulars of charge for Form CHG-1"]),
                ("debt schedule", "bank", f"Bank Statements and Debt Schedule - "
                 f"{self.short}.pdf", DocClass.BANK_STATEMENT,
                 ["Twelve months' statements of the operating accounts",
                  "Schedule of existing borrowings and lender consents"]),
            ]
        span = max(1, d1 - d0)
        for i, (kw, key, fname, dclass, lines) in enumerate(evidence):
            if kw in skip:
                continue
            self.doc(d0, key, fname, dclass, lines, by=by, hhmm=f"11:{10 + i * 7:02d}")
            self.dd(d0, kw, "requested", by=by, hhmm=f"10:{5 + i * 5:02d}")
            self.dd(min(d1, d0 + 1 + (i * span) // len(evidence)), kw, "satisfied", [key],
                    by=by, hhmm="15:20")
        if "audited financial" not in skip:
            self.dd(d0, "audited financial", "under_review", by=by, hhmm="10:40")

            def satisfy_fs():
                r = self.r(by)
                item = self._item(r, "audited financial")
                key = next((k for k in ("fs", "fs2") if k in self.docs), None)
                if item is None or key is None:
                    return
                diligence.update_diligence_item(item.id, DiligenceStatus.SATISFIED,
                                                [self.docs[key]], None, by, role_of(by),
                                                r.diligence, r.documents, r.audit)
            self._at(min(d1, d0 + 2), "16:10", "diligence financials -> satisfied",
                     satisfy_fs)
        if self.cls is TransactionClass.ALLIANCE and "commercial agreements" not in skip:
            self.dd(d0 + 1, "commercial agreements", "waived",
                    waiver="Client confirmed in writing that it has no exclusive distribution "
                           "or supply agreements; covered by a warranty in the alliance "
                           "agreement.", by=by, hhmm="16:40")


def ensure_deal_exists(story: Story) -> bool:
    """Whether this story's deal is already in the database (then it is left alone)."""
    return story.desk.repos(SYSTEM).deals.get_by_external_id(story.ext) is not None

