"""Assemble a deal export (aura.core.domain.export.DealExportBundle).

Everything is read through the viewer's wall-scoped repositories, so an export can never
show more than the deal page does: a deal the viewer cannot see is NotFound (404), and
admins, who hold no deal powers, are Forbidden (403) before anything is read. Contact
emails are masked unless the viewer is a dealmaker or compliance. Pure: rendering to files
is aura.exports; auditing and rate limiting are the caller's (the API route)."""
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Callable

from aura.core.clock import utcnow
from aura.core.domain.deal import Deal
from aura.core.domain.enums import DiligenceSeverity, Role
from aura.core.domain.errors import NotFound, RuleViolation
from aura.core.domain.export import (DEFAULT_SECTIONS, EXPORT_SCHEMA_VERSION, SECTIONS,
                                     Column, DealExportBundle, ExportSection, ExportTable)
from aura.core.money import format_inr_compact, to_inr_int
from aura.core.policy.rbac_policy import Capability, require
from aura.core.ports.repositories import (AgentRunRepository, ConditionRepository,
                                          ContactRepository, DealRepository,
                                          DiligenceRepository, DocumentRepository,
                                          ExportReader, ExtractionRepository,
                                          FindingRepository, HandoffRepository,
                                          MandateRepository, PartyRepository,
                                          SignoffRepository, StageHistoryRepository,
                                          WallRepository)

C = Column
SEVERITY_ORDER = [s.value for s in (DiligenceSeverity.BLOCKER, DiligenceSeverity.MATERIAL,
                                    DiligenceSeverity.STANDARD,
                                    DiligenceSeverity.INFORMATIONAL)]
# Who sees contact emails in full. Everyone else gets a***@domain.
EMAIL_ROLES = {Role.DEALMAKER, Role.COMPLIANCE}
MAX_ROWS = 5000


@dataclass
class ExportSources:
    """The viewer's repositories (each built for the viewer, so walls apply)."""
    deals: DealRepository
    history: StageHistoryRepository
    walls: WallRepository
    parties: PartyRepository
    contacts: ContactRepository
    mandates: MandateRepository
    documents: DocumentRepository
    diligence: DiligenceRepository
    findings: FindingRepository
    conditions: ConditionRepository
    signoffs: SignoffRepository
    extractions: ExtractionRepository
    handoffs: HandoffRepository
    agent_runs: AgentRunRepository
    reader: ExportReader
    # () -> {"ok", "broken_at", "head_id", "head_hash", "anchor_head_id"}: verified at export
    audit_status: Callable[[], dict] | None = None
    # (transaction_class, version) -> JSON Schema of the deal profile, or None
    profile_schema: Callable[[str, int], dict | None] | None = None


# --------------------------------------------------------------------------- helpers

def parse_sections(raw: str | list[str] | None) -> list[str]:
    """'parties,documents' (or a list) -> the known sections in report order. Empty or
    None means all. An unknown name is a RuleViolation (422). The summary always leads."""
    if raw is None:
        return list(DEFAULT_SECTIONS)
    names = raw.split(",") if isinstance(raw, str) else list(raw)
    wanted = {n.strip().lower() for n in names if n and n.strip()}
    if not wanted or "all" in wanted:
        return list(DEFAULT_SECTIONS)
    unknown = sorted(wanted - set(SECTIONS))
    if unknown:
        raise RuleViolation(f"Unknown export section(s): {', '.join(unknown)}. "
                            f"Known: {', '.join(SECTIONS)}")
    wanted.add("summary")
    return [s for s in SECTIONS if s in wanted]


def mask_email(email: str | None) -> str:
    """'priya.shah@kaveri.in' -> 'p***@kaveri.in'."""
    if not email:
        return ""
    local, _, domain = email.partition("@")
    return f"{local[:1]}***@{domain}" if domain else "***"


def iso(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


IST = timezone(timedelta(hours=5, minutes=30))


def when(value) -> str:
    """A timestamp for people: '13 Oct 2026, 15:00 IST'; '—' for none."""
    if value is None:
        return "—"
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(IST).strftime("%d %b %Y, %H:%M IST")


def _label(value: str | None) -> str:
    if not value:
        return ""
    text = value.replace("_", " ").replace("-", " ")
    return text[:1].upper() + text[1:].lower()


def _num(value) -> str:
    if isinstance(value, float) and not value.is_integer():
        return f"{value:,.2f}".rstrip("0").rstrip(".")
    return f"{int(value):,}"


def _cap(rows: list[dict]) -> tuple[list[dict], bool]:
    return (rows[:MAX_ROWS], True) if len(rows) > MAX_ROWS else (rows, False)


def _table(key: str, title: str, columns: list[Column], rows: list[dict],
           note: str | None = None) -> ExportTable:
    rows, truncated = _cap(rows)
    return ExportTable(key=key, title=title, columns=columns, rows=rows, note=note,
                       truncated=truncated)


# --------------------------------------------------------------------------- sections

def _summary(deal: Deal, members, history) -> ExportSection:
    first = min((h.entered_at for h in history), default=None)
    last = max((h.entered_at for h in history), default=None)
    facts = [("Reference", deal.external_id), ("Name", deal.name),
             ("Transaction class", deal.transaction_class.value),
             ("Stage", _label(deal.stage.value)),
             ("Outcome", _label(deal.outcome.value) if deal.outcome else "Open"),
             ("Owner", deal.owner or "Unassigned"),
             ("Opened", when(deal.opened_at)),
             ("Closed", when(deal.closed_at)),
             ("Last stage move", when(last)),
             ("Team", ", ".join(m.username for m in members) or "—"),
             ("Regulatory flags", ", ".join(deal.regulatory_flags) or "None")]
    team = _table("team", "Deal team (wall)",
                  [C("username", "Member", width=2), C("added_at", "On the wall since",
                                                       "datetime", 1.5)],
                  [{"username": m.username, "added_at": iso(m.added_at)} for m in members])
    sec = ExportSection("summary", SECTIONS["summary"], tables=[team], facts=facts)
    sec.data = {"first_history_at": iso(first)}
    return sec


def _stages(deal_id: int, history, evaluations) -> ExportSection:
    moves = [{"entered_at": iso(h.entered_at),
              "from_stage": h.from_stage.value if h.from_stage else None,
              "to_stage": h.to_stage.value, "actor": h.actor, "reason_code": h.reason_code,
              "is_regression": h.is_regression}
             for h in sorted(history, key=lambda h: (h.entered_at, h.id or 0))]
    guards = [{"attempted_at": iso(e.attempted_at), "guard_name": e.guard_name,
               "severity": e.severity.value, "result": e.result, "actor": e.actor,
               "overridden_by": e.overridden_by,
               "override_justification": e.override_justification,
               "override_role": e.override_role,
               "led_to_move": e.history_id is not None,
               "description": e.description}
              for e in evaluations]
    overrides = sum(1 for g in guards if g["overridden_by"])
    regressions = sum(1 for m in moves if m["is_regression"])
    return ExportSection("stages", SECTIONS["stages"], tables=[
        _table("moves", "Stage moves", [
            C("entered_at", "When", "datetime", 1.4), C("from_stage", "From", "enum", 1.3),
            C("to_stage", "To", "enum", 1.3), C("actor", "By"),
            C("reason_code", "Reason", "enum", 1.2), C("is_regression", "Regression", "bool",
                                                       0.8)], moves),
        _table("guard_evaluations", "Guard evaluations", [
            C("attempted_at", "When", "datetime", 1.6), C("guard_name", "Guard", width=2.0),
            C("severity", "Severity", "enum", 0.9), C("result", "Passed", "bool", 0.7),
            C("actor", "By", width=0.9), C("overridden_by", "Overridden by", width=1.0),
            C("override_justification", "Justification", width=2.0),
            C("led_to_move", "Moved", "bool", 0.75)], guards),
    ], facts=[("Moves", str(len(moves))), ("Regressions", str(regressions)),
              ("Guard evaluations", str(len(guards))), ("Overrides", str(overrides))])


def _parties(deal_id: int, src: ExportSources, role: Role) -> ExportSection:
    links = src.parties.list_for_deal(deal_id)
    parties, identifiers, contacts = [], [], []
    masked = role not in EMAIL_ROLES
    for link in links:
        party = src.parties.get(link.party_id)
        parties.append({"party_id": link.party_id, "name": link.display_name,
                        "role": link.role.value,
                        "party_type": party.party_type.value if party else None})
        for ident in (party.identifiers if party else []):
            identifiers.append({"party": link.display_name, "scheme": ident.scheme.value,
                                "value": ident.value})
        for c in src.contacts.list_for_party(link.party_id):
            contacts.append({"party": link.display_name, "name": c.name,
                             "email": mask_email(c.email) if masked else c.email,
                             "primary": c.is_primary, "verified": c.verified_at is not None})
    note = ("Email addresses are masked for your role." if masked and contacts else None)
    return ExportSection("parties", SECTIONS["parties"], tables=[
        _table("parties", "Parties on the deal", [
            C("name", "Party", width=2.4), C("role", "Role", "enum"), C("party_type", "Type", "enum"),
            C("party_id", "Party id", "int", 0.6)], parties),
        _table("identifiers", "Identifiers", [
            C("party", "Party", width=2.2), C("scheme", "Scheme", width=0.8),
            C("value", "Value", width=1.8)], identifiers),
        _table("contacts", "Contacts", [
            C("party", "Party", width=1.8), C("name", "Name", width=1.4),
            C("email", "Email", width=2.0), C("primary", "Primary", "bool", 0.6),
            C("verified", "Verified", "bool", 0.6)], contacts, note=note),
    ])


def _display(value, prop: dict) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "Yes" if value else "No"
    labels = prop.get("x-enum-labels") or {}
    if isinstance(value, str):
        return labels.get(value, value if prop.get("enum") is None else _label(value))
    if isinstance(value, (int, float)):
        return format_inr_compact(value) if prop.get("_inr") else _num(value)
    if isinstance(value, list):
        item = prop.get("items") or {}
        return "; ".join(_display(v, item) for v in value)
    if isinstance(value, dict):
        sub = prop.get("properties") or {}
        return ", ".join(f"{(sub.get(k) or {}).get('title', _label(k))}: "
                         f"{_display(v, {**(sub.get(k) or {}), '_inr': k.endswith('_inr')})}"
                         for k, v in value.items() if v not in (None, "", []))
    return str(value)


def _profile_rows(profile: dict, schema: dict | None) -> list[dict]:
    props = (schema or {}).get("properties") or {}
    order = [k for k in props if k in profile] + [k for k in profile if k not in props]
    rows = []
    for key in order:
        prop = {**(props.get(key) or {}), "_inr": key.endswith("_inr")}
        value = profile[key]
        if value in (None, "", [], {}):
            continue
        rows.append({"key": key, "field": prop.get("title") or _label(key),
                     "value": _display(value, prop),
                     "amount_inr": to_inr_int(value) if prop["_inr"] else None})
    return rows


def _profile(deal: Deal, src: ExportSources) -> ExportSection:
    schema = (src.profile_schema(deal.transaction_class.value, deal.profile_schema_version)
              if src.profile_schema else None)
    rows = _profile_rows(deal.profile or {}, schema)
    sec = ExportSection("profile", SECTIONS["profile"], tables=[
        _table("terms", (schema or {}).get("title") or "Deal profile", [
            C("field", "Term", width=1.6), C("value", "Value", width=3.0),
            C("amount_inr", "Amount (INR)", "inr", 1.2, human=False)], rows)])
    sec.data = {"profile": deal.profile or {},
                "profile_schema_version": deal.profile_schema_version}
    return sec


def _cite(citations) -> str:
    parts = []
    for c in citations or []:
        name = c.get("filename") if isinstance(c, dict) else None
        if not name:
            continue
        page = c.get("page_from")
        parts.append(f"{name} p.{page}" if page else name)
    return "; ".join(dict.fromkeys(parts))


def _financials(deal: Deal, src: ExportSources) -> ExportSection:
    from aura.core.services.intake_fields import BASE_BY_KEY
    rows: list[dict] = []
    intake = src.reader.confirmed_intake(deal.id)
    if intake is not None:
        for key, rec in (intake.fields or {}).items():
            spec = BASE_BY_KEY.get(key)
            if spec is None or not (spec.group == "financials" or spec.type == "inr"):
                continue
            value = (rec or {}).get("value")
            if value in (None, "", []):
                continue
            inr = spec.type == "inr"
            rows.append({"metric": spec.label, "key": key,
                         "amount_inr": to_inr_int(value) if inr else None,
                         "value": None if inr else str(value),
                         "source": f"Intake ({rec.get('source') or 'extracted'})",
                         "evidence": _cite(rec.get("citations")),
                         "confidence": rec.get("confidence"),
                         "verified": bool(rec.get("accepted"))})
    for e in src.extractions.list_for_deal(deal.id):
        for key, value in (e.payload or {}).items():
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            spec = BASE_BY_KEY.get(key)
            inr = key.endswith("_inr")
            rows.append({"metric": spec.label if spec else _label(key.removesuffix("_inr")),
                         "key": key, "amount_inr": to_inr_int(value) if inr else None,
                         "value": None if inr else _num(value),
                         "source": f"Extraction #{e.id} ({e.schema_name}, document "
                                   f"{e.document_id} v{e.version})",
                         "evidence": "", "confidence": e.confidence,
                         "verified": e.human_verified_by is not None})
    for row in _profile_rows(deal.profile or {}, None):
        if row["amount_inr"] is not None:
            rows.append({"metric": row["field"], "key": f"profile.{row['key']}",
                         "amount_inr": row["amount_inr"], "value": None,
                         "source": "Deal profile", "evidence": "", "confidence": None,
                         "verified": True})
    if src.profile_schema:
        schema = src.profile_schema(deal.transaction_class.value,
                                    deal.profile_schema_version) or {}
        titles = {f"profile.{k}": p.get("title") for k, p in
                  (schema.get("properties") or {}).items() if p.get("title")}
        for row in rows:
            row["metric"] = titles.get(row["key"], row["metric"])
    return ExportSection("financials", SECTIONS["financials"], tables=[
        _table("figures", "Figures and their sources", [
            C("metric", "Metric", width=1.6), C("amount_inr", "Amount (INR)", "inr", 1.3),
            C("value", "Other value", width=0.9), C("source", "Source", width=2.0),
            C("evidence", "Evidence", width=1.6), C("confidence", "Conf.", "pct", 0.6),
            C("verified", "Verified", "bool", 0.7)], rows)])


def _mandate(deal_id: int, src: ExportSources) -> ExportSection:
    mandates, criteria = [], []
    for m in src.mandates.list_for_deal(deal_id):
        mandates.append({"mandate_id": m.id, "title": m.title, "side": m.side.value,
                         "status": m.status.value, "created_at": iso(m.created_at),
                         "notes": m.notes})
        for c in m.criteria:
            value = c.value
            money = c.criterion_key.endswith("_inr")

            def one(v):
                return format_inr_compact(v) if money and isinstance(v, (int, float))                     and not isinstance(v, bool) else str(v)
            shown = (", ".join(one(v) for v in value) if isinstance(value, list)
                     else one(value))
            criteria.append({"mandate": m.title, "criterion": c.criterion_key,
                             "operator": getattr(c.operator, "value", c.operator),
                             "value": shown, "raw_value": value,
                             "hardness": getattr(c.hardness, "value", c.hardness),
                             "weight": c.weight})
    return ExportSection("mandate", SECTIONS["mandate"], tables=[
        _table("mandates", "Mandates", [
            C("title", "Mandate", width=2.2), C("side", "Side", "enum", 0.7),
            C("status", "Status", "enum", 0.8), C("created_at", "Created", "datetime", 1.3),
            C("notes", "Notes", width=2.4)], mandates),
        _table("criteria", "Criteria", [
            C("mandate", "Mandate", width=1.6), C("criterion", "Criterion", width=1.6),
            C("operator", "Operator", "enum", 0.8), C("value", "Value", width=1.8),
            C("hardness", "Hardness", "enum", 0.8), C("weight", "Weight", "float", 0.6)],
            criteria),
    ])


def _documents(docs) -> ExportSection:
    rows = [{"document_id": d.id, "filename": d.filename, "doc_class": d.doc_class.value,
             "version": d.current_version, "sensitivity": d.sensitivity,
             "contains_upsi": d.contains_upsi, "executed": d.is_executed,
             "index_status": d.index_status, "pages": d.page_count,
             "byte_size": d.byte_size, "uploaded_by": d.uploaded_by,
             "uploaded_at": iso(d.uploaded_at), "sha256": d.sha256}
            for d in sorted(docs, key=lambda d: d.id or 0)]
    return ExportSection("documents", SECTIONS["documents"], tables=[
        _table("documents", "Documents (metadata only; no file contents)", [
            C("filename", "File", width=2.4), C("doc_class", "Class", "enum", 1.3),
            C("version", "Ver", "int", 0.4), C("sensitivity", "Sens.", "int", 0.5),
            C("contains_upsi", "UPSI", "bool", 0.5), C("executed", "Executed", "bool", 0.7),
            C("index_status", "Index", "enum", 0.7), C("uploaded_by", "Uploaded by", width=0.9),
            C("uploaded_at", "Uploaded", "datetime", 1.3)], rows)],
        facts=[("Documents", str(len(rows))),
               ("UPSI or sensitivity 4+", str(sum(1 for d in docs if _is_upsi(d)))),
               ("Executed", str(sum(1 for d in docs if d.is_executed)))])


def _diligence(deal_id: int, src: ExportSources) -> ExportSection:
    items = src.diligence.list_items(deal_id)
    rank = {s: i for i, s in enumerate(SEVERITY_ORDER)}
    rows = [{"item_id": i.id, "severity": i.severity.value, "status": i.status.value,
             "prompt": i.prompt, "evidence_documents": len(i.evidence_doc_ids),
             "waiver_justification": i.waiver_justification}
            for i in sorted(items, key=lambda i: (rank.get(i.severity.value, 9), i.id or 0))]
    prompts = {i.id: i.prompt for i in items}
    findings = [{"finding_id": f.id, "type": f.finding_type.value,
                 "description": f.description,
                 "impact_inr": to_inr_int(f.quantified_impact_inr),
                 "affects_valuation": f.affects_valuation, "raised_by": f.raised_by,
                 "raised_at": iso(f.raised_at),
                 "diligence_item": prompts.get(f.diligence_item_id, "")}
                for f in src.findings.list_for_deal(deal_id)]
    by_sev = Counter(r["severity"] for r in rows)
    open_blockers = sum(1 for i in items if i.severity is DiligenceSeverity.BLOCKER
                        and i.status.value not in ("satisfied", "waived"))
    impact = sum(f["impact_inr"] or 0 for f in findings)
    return ExportSection("diligence", SECTIONS["diligence"], tables=[
        _table("items", "Checklist by severity", [
            C("severity", "Severity", "enum", 0.9), C("status", "Status", "enum", 0.9),
            C("prompt", "Item", width=4.0), C("evidence_documents", "Docs", "int", 0.5),
            C("waiver_justification", "Waiver", width=1.6)], rows),
        _table("findings", "Findings", [
            C("type", "Type", "enum", 0.9), C("description", "Finding", width=3.0),
            C("impact_inr", "Impact (INR)", "inr", 1.2),
            C("affects_valuation", "Valuation", "bool", 0.7),
            C("raised_by", "Raised by", width=0.8),
            C("raised_at", "Raised", "datetime", 1.3)], findings),
    ], facts=[*((_label(s), str(by_sev.get(s, 0))) for s in SEVERITY_ORDER),
              ("Open blockers", str(open_blockers)), ("Findings", str(len(findings))),
              ("Quantified impact", format_inr_compact(impact) if findings else "—")])


def _conditions(deal_id: int, src: ExportSources) -> ExportSection:
    rows = [{"cp_id": c.id, "description": c.description, "cp_type": c.cp_type,
             "status": c.status.value, "waiver_justification": c.waiver_justification}
            for c in src.conditions.list_for_deal(deal_id)]
    return ExportSection("conditions", SECTIONS["conditions"], tables=[
        _table("conditions", "Conditions precedent", [
            C("description", "Condition", width=3.4), C("cp_type", "Type", "enum", 1.0),
            C("status", "Status", "enum", 0.9),
            C("waiver_justification", "Waiver", width=1.6)], rows)],
        facts=[("Conditions", str(len(rows))),
               ("Outstanding", str(sum(1 for r in rows
                                       if r["status"] not in ("satisfied", "waived"))))])


def _compliance(deal: Deal, src: ExportSources) -> ExportSection:
    signoffs = [{"signed_by": s.signed_by, "signed_at": iso(s.signed_at), "note": s.note}
                for s in src.signoffs.list_for_deal(deal.id)]
    flags = [{"flag": f} for f in deal.regulatory_flags]
    return ExportSection("compliance", SECTIONS["compliance"], tables=[
        _table("flags", "Regulatory flags", [C("flag", "Flag")], flags),
        _table("signoffs", "Compliance sign-offs", [
            C("signed_by", "Signed by"), C("signed_at", "When", "datetime", 1.3),
            C("note", "Note", width=3.0)], signoffs)],
        facts=[("Regulatory flags", ", ".join(deal.regulatory_flags) or "None"),
               ("Sign-offs", str(len(signoffs)))])


def _decisions(deal_id: int, src: ExportSources) -> ExportSection:
    rows = []
    for h in sorted((h for h in src.handoffs.list_all() if h.deal_id == deal_id),
                    key=lambda h: (h.created_at, h.id or 0)):
        package = h.context_package or {}
        question = ((package.get("decision_required") or {}).get("question")
                    or package.get("summary") or h.task_type or "")
        directive = h.directive or {}
        rows.append({"handoff_id": h.id, "created_at": iso(h.created_at),
                     "task_type": h.task_type, "trigger": h.trigger.value,
                     "status": h.status.value, "question": question,
                     "decision": directive.get("decision"),
                     "reasoning": directive.get("reasoning"),
                     "resolved_by": h.resolved_by, "resolved_at": iso(h.resolved_at)})
    return ExportSection("decisions", SECTIONS["decisions"], tables=[
        _table("handoffs", "Decisions and handoffs", [
            C("created_at", "Raised", "datetime", 1.2), C("question", "Question", width=2.6),
            C("status", "Status", "enum", 0.95), C("decision", "Decision", "enum", 0.9),
            C("reasoning", "Reasoning", width=2.4), C("resolved_by", "By", width=0.8),
            C("resolved_at", "When", "datetime", 1.2)], rows)],
        facts=[("Handoffs", str(len(rows))),
               ("Resolved", str(sum(1 for r in rows if r["status"] == "resolved"))),
               ("Waiting", str(sum(1 for r in rows if r["status"] != "resolved")))])


def _agent_runs(deal_id: int, src: ExportSources) -> ExportSection:
    runs = src.agent_runs.list_for(deal_id, limit=MAX_ROWS)
    groups: dict[tuple[str, str], dict] = {}
    for r in runs:
        model = f"{r.model_id} {r.model_version}".strip()
        g = groups.setdefault((r.archetype, model), {
            "archetype": r.archetype, "model": model, "runs": 0, "tokens_in": 0,
            "tokens_out": 0, "latency_ms_total": 0, "first_at": None, "last_at": None})
        g["runs"] += 1
        g["tokens_in"] += r.tokens_in or 0
        g["tokens_out"] += r.tokens_out or 0
        g["latency_ms_total"] += r.latency_ms or 0
        at = iso(r.started_at)
        g["first_at"] = min(filter(None, [g["first_at"], at]), default=at)
        g["last_at"] = max(filter(None, [g["last_at"], at]), default=at)
    rows = []
    for g in sorted(groups.values(), key=lambda g: (-g["runs"], g["archetype"])):
        g["avg_latency_ms"] = round(g.pop("latency_ms_total") / g["runs"]) if g["runs"] else 0
        rows.append(g)
    return ExportSection("agent_runs", SECTIONS["agent_runs"], tables=[
        _table("by_model", "Runs by archetype and model", [
            C("archetype", "Archetype", width=1.4), C("model", "Model", width=1.6),
            C("runs", "Runs", "int", 0.5), C("tokens_in", "Tokens in", "int", 0.8),
            C("tokens_out", "Tokens out", "int", 0.8),
            C("avg_latency_ms", "Avg ms", "int", 0.7),
            C("last_at", "Last run", "datetime", 1.3)], rows)],
        facts=[("Model calls", str(len(runs))),
               ("Models", ", ".join(sorted({r["model"] for r in rows})) or "—"),
               ("Tokens", f"{sum(r.tokens_in + r.tokens_out for r in runs):,}")])


def _audit(status: dict) -> ExportSection:
    facts = [("Chain verified", "Yes" if status.get("ok") else "NO — see broken_at"),
             ("Head entry", str(status.get("head_id") or "—")),
             ("Head hash (SHA-256)", status.get("head_hash") or "—"),
             ("Verified at", status.get("verified_at") or "")]
    if status.get("message") and not status.get("ok"):
        facts.append(("Detail", str(status["message"])))
    if status.get("broken_at"):
        facts.append(("Broken at entry", str(status["broken_at"])))
    return ExportSection("audit", SECTIONS["audit"], facts=facts, data={"status": status})


def _is_upsi(doc) -> bool:
    return bool(doc.contains_upsi) or (doc.sensitivity or 0) >= 4


# --------------------------------------------------------------------------- entry point

def build_deal_export(deal_id: int, viewer: str, viewer_role: Role,
                      sections: list[str] | str | None, src: ExportSources,
                      now: datetime | None = None) -> DealExportBundle:
    """The deal's export bundle for this viewer. Forbidden (403) for a role without deal
    powers; NotFound (404) when the deal is not on the viewer's wall."""
    require(viewer_role, Capability.EXPORT_DEAL, "export deals")
    wanted = parse_sections(sections)
    deal = src.deals.get(deal_id)
    if deal is None:
        raise NotFound("Deal not found")
    now = now or utcnow()
    members = src.walls.members(deal_id)
    history = src.history.list_for_deal(deal_id)
    docs = src.documents.list_for_deal(deal_id)
    status = {"ok": None, "broken_at": None, "head_id": None, "head_hash": None,
              "verified_at": iso(now)}
    if src.audit_status is not None:
        status.update(src.audit_status())

    builders = {
        "summary": lambda: _summary(deal, members, history),
        "stages": lambda: _stages(deal_id, history, src.reader.guard_evaluations(deal_id)),
        "parties": lambda: _parties(deal_id, src, viewer_role),
        "profile": lambda: _profile(deal, src),
        "financials": lambda: _financials(deal, src),
        "mandate": lambda: _mandate(deal_id, src),
        "documents": lambda: _documents(docs),
        "diligence": lambda: _diligence(deal_id, src),
        "conditions": lambda: _conditions(deal_id, src),
        "compliance": lambda: _compliance(deal, src),
        "decisions": lambda: _decisions(deal_id, src),
        "agent_runs": lambda: _agent_runs(deal_id, src),
        "audit": lambda: _audit(status),
    }
    header = {"id": deal.id, "external_id": deal.external_id, "name": deal.name,
              "transaction_class": deal.transaction_class.value, "stage": deal.stage.value,
              "outcome": deal.outcome.value if deal.outcome else None, "owner": deal.owner,
              "opened_at": iso(deal.opened_at), "closed_at": iso(deal.closed_at),
              "regulatory_flags": list(deal.regulatory_flags),
              "team": [m.username for m in members]}
    return DealExportBundle(
        schema_version=EXPORT_SCHEMA_VERSION, generated_at=iso(now), generated_by=viewer,
        generated_by_role=viewer_role.value, deal=header,
        sections=[builders[s]() for s in wanted], upsi=any(_is_upsi(d) for d in docs),
        audit=status)


# --------------------------------------------------------------------------- deals list

DEAL_LIST_COLUMNS = [
    C("external_id", "Reference", width=1.0), C("name", "Deal", width=2.4),
    C("transaction_class", "Class", width=0.8), C("stage", "Stage", "enum", 1.3),
    C("outcome", "Outcome", "enum", 0.9), C("owner", "Owner", width=0.9),
    C("opened_at", "Opened", "datetime", 1.3), C("closed_at", "Closed", "datetime", 1.3),
    C("regulatory_flags", "Flags", width=1.0), C("headline_inr", "Headline (INR)", "inr", 1.2),
]
# Profile keys that carry a deal's headline amount, by preference.
_HEADLINE = ("amount_inr", "enterprise_value_inr", "equity_value_inr", "post_money_inr",
             "commitment_inr", "target_corpus_inr", "investment_inr", "ticket_size_inr")


def _headline(profile: dict) -> int | None:
    for key in _HEADLINE:
        if isinstance(profile.get(key), (int, float)):
            return to_inr_int(profile[key])
    return next((to_inr_int(v) for k, v in profile.items()
                 if k.endswith("_inr") and isinstance(v, (int, float))), None)


def filter_deals(deals: list[Deal], q: str | None = None,
                 classes: list[str] | None = None, stages: list[str] | None = None,
                 outcomes: list[str] | None = None) -> list[Deal]:
    """The deals list's own filters (frontend DealsTable): text, class, stage, outcome
    ('OPEN' for none). Case-insensitive."""
    q = (q or "").strip().lower()
    cls = {c.upper() for c in classes or [] if c}
    stg = {s.upper() for s in stages or [] if s}
    out = {o.upper() for o in outcomes or [] if o}

    def keep(d: Deal) -> bool:
        text = f"{d.name} {d.external_id} {d.owner or ''} {d.stage.value} " \
               f"{d.transaction_class.value}".lower()
        outcome = d.outcome.value.upper() if d.outcome else "OPEN"
        return ((not q or q in text) and (not cls or d.transaction_class.value in cls)
                and (not stg or d.stage.value in stg) and (not out or outcome in out))
    return [d for d in deals if keep(d)]


def deals_list_table(deals: list[Deal], viewer_role: Role) -> ExportTable:
    """The deals the viewer can see (the repository is walled) as one export table."""
    require(viewer_role, Capability.EXPORT_DEAL, "export deals")
    rows = [{"deal_id": d.id, "external_id": d.external_id, "name": d.name,
             "transaction_class": d.transaction_class.value, "stage": d.stage.value,
             "outcome": d.outcome.value if d.outcome else None, "owner": d.owner,
             "opened_at": iso(d.opened_at), "closed_at": iso(d.closed_at),
             "regulatory_flags": ", ".join(d.regulatory_flags),
             "headline_inr": _headline(d.profile or {})} for d in deals]
    return _table("deals", "Deals", list(DEAL_LIST_COLUMNS), rows)
