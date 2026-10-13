"""Deal intake (phase 3): create a deal by uploading its documents.

    POST /api/intakes            -> a private draft (row-level security: its creator only)
    POST .../files               -> staged documents, indexed by the normal queue
    (worker)                     -> extraction once every file is indexed (intake_extraction)
    PATCH                        -> the creator's edits, accepts and conflict choices
    POST .../confirm             -> the deal, through create_deal and the other services

A staged file is an ordinary document row with no deal and the intake's id; confirming
creates the deal with create_deal (so the stage machine, its first history row, the wall and
the audit are exactly those of any new deal), links the parties, opens the mandate, saves the
validated profile, and re-points the documents, their chunks, index jobs and model runs to
the deal in the same unit of work - nothing is parsed twice. Every step is audited; a draft's
audit rows name only ids, and its live events reach its creator alone.
"""
import copy
import re
from dataclasses import dataclass, field

from aura.core.clock import utcnow
from aura.core.domain.audit import AuditEntry
from aura.core.domain.document import Document
from aura.core.domain.enums import (CriterionHardness, CriterionOperator, DocClass,
                                    IdentifierScheme, MandateSide, MandateStatus, PartyRole,
                                    PartyType, Role, TransactionClass)
from aura.core.domain.errors import Conflict, NotFound, RuleViolation
from aura.core.domain.intake import Intake
from aura.core.domain.mandate import MandateCriterion
from aura.core.domain.party import PartyIdentifier
from aura.core.policy.rbac_policy import Capability, can, require
from aura.core.ports.ingest import DocumentIndexState, IndexQueue
from aura.core.ports.intake import IntakeRepository
from aura.core.ports.repositories import (AuditRepository, DealRepository, FileStore,
                                          MandateRepository, PartyRepository,
                                          StageHistoryRepository, UserRepository,
                                          WallRepository)
from aura.core.services import intake_fields as F
from aura.core.services.compliance import set_regulatory_flags
from aura.core.services.create_deal import create_deal
from aura.core.services.deal_profile import (CURRENT_PROFILE_VERSION, get_schema,
                                             profile_errors)
from aura.core.services.indexing import enqueue
from aura.core.services.intake_extraction import ExtractionResult
from aura.core.services.mandates import create_mandate
from aura.core.services.parties import create_party, link_party

OPEN = ("draft", "processing", "review")
ROLE_FOR_CLASS = {"DEBT": "issuer", "EQUITY": "issuer", "HYBRID": "issuer", "MNA": "target",
                  "JV": "issuer", "ALLIANCE": "issuer", "LPGP": "issuer"}
_EXTERNAL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$")
_CLASS_BY_NAME = [
    (r"term[\s_-]*sheet", DocClass.TERM_SHEET),
    (r"board|resolution|minutes", DocClass.BOARD_RESOLUTION),
    (r"cap[\s_-]*table|shareholding", DocClass.CAP_TABLE),
    (r"\bspa\b|share[\s_-]*purchase", DocClass.SPA),
    (r"\bsha\b|shareholders?[\s_-]*agreement", DocClass.SHPA),
    (r"valuation", DocClass.VALUATION_REPORT),
    (r"\bnda\b|non[\s_-]*disclosure|confidentiality", DocClass.NDA),
    (r"engagement|mandate[\s_-]*letter", DocClass.ENGAGEMENT_LETTER),
    (r"\bgst", DocClass.GST_RETURN),
    (r"bank[\s_-]*statement", DocClass.BANK_STATEMENT),
    (r"charge|hypothecation|mortgage", DocClass.CHARGE_DOCUMENT),
    (r"\bitr\b|tax[\s_-]*return", DocClass.TAX_RETURN),
    (r"moa|aoa|articles|memorandum[\s_-]*of[\s_-]*association", DocClass.MOA_AOA),
    (r"litigation", DocClass.LITIGATION_SUMMARY),
    (r"title|land", DocClass.LAND_TITLE),
]


def guess_doc_class(filename: str) -> DocClass:
    """A first guess from the file name (unconfirmed; the review step or the classifier
    agent can change it). Financial statements, models, IMs and teasers default to
    financial_statement."""
    low = filename.lower().replace("_", " ")
    for pattern, cls in _CLASS_BY_NAME:
        if re.search(pattern, low):
            return cls
    return DocClass.FINANCIAL_STATEMENT


def _audit(audit: AuditRepository, actor: str, action: str, intake: Intake, **payload) -> None:
    audit.append(AuditEntry(id=None, job_id=None, deal_id=None, actor=actor, action=action,
                            created_at=utcnow(),
                            payload={"intake_id": intake.id, "recipient": intake.created_by,
                                     **payload}))


def _get(intake_id: int, intakes: IntakeRepository, for_update: bool = False) -> Intake:
    intake = intakes.get(intake_id, for_update=for_update)
    if intake is None:
        raise NotFound("Intake not found")
    return intake


def _open(intake: Intake) -> None:
    if intake.status == "confirmed":
        raise Conflict(f"Intake {intake.id} is already confirmed (deal "
                       f"{intake.confirmed_deal_id})")
    if intake.status == "discarded":
        raise Conflict(f"Intake {intake.id} was discarded")


def schema_for(transaction_class: str | None) -> dict | None:
    if not transaction_class:
        return None
    try:
        return get_schema(transaction_class)
    except (NotFound, ValueError):
        return None


def specs_for(intake: Intake) -> list[F.FieldSpec]:
    return F.specs_for(schema_for(intake.transaction_class))


def spec_by_key(intake: Intake) -> dict[str, F.FieldSpec]:
    return {s.key: s for s in specs_for(intake)}


# ---------------------------------------------------------------------------- create

def create_intake(hints: dict | None, actor: str, actor_role: Role, intakes: IntakeRepository,
                  audit: AuditRepository) -> Intake:
    """A private draft. Hints the creator typed (company name, CIN, class) are kept as the
    creator's own values: extraction never overwrites them."""
    require(actor_role, Capability.CREATE_DEAL, "create deal intakes")
    hints = {k: (str(v).strip() if v is not None else None)
             for k, v in (hints or {}).items()
             if k in ("company_name", "cin", "transaction_class_hint")}
    intake = Intake(id=None, created_by=actor, hints=hints)
    _apply_hints(intake)
    intake = intakes.add(intake)
    _audit(audit, actor, "intake_created", intake)
    return intake


def _user_record(value, previous: dict | None = None, error: str | None = None) -> dict:
    prev = previous or {}
    auto = prev.get("auto_value")
    return {**{"auto_value": None, "confidence": None, "citations": [], "note": None},
            **prev, "value": value, "source": "user", "accepted": True,
            "edited": auto is not None and value != auto, "error": error,
            "conflict_id": None}


def _apply_hints(intake: Intake) -> None:
    hints = intake.hints or {}
    for key, hint in (("company_name", "company_name"), ("cin", "cin"),
                      ("transaction_class", "transaction_class_hint")):
        raw = hints.get(hint)
        if not raw or (intake.fields.get(key) or {}).get("source") == "user":
            continue
        spec = F.BASE_BY_KEY[key]
        value, error = F.normalise_value(spec, raw)
        if error:
            raise RuleViolation(f"{spec.label}: {error}")
        intake.fields[key] = _user_record(value, intake.fields.get(key))
    cls = (intake.fields.get("transaction_class") or {}).get("value")
    intake.transaction_class = cls if cls in {c.value for c in TransactionClass} else None


# ---------------------------------------------------------------------------- files

@dataclass
class StagedFile:
    document: Document
    duplicate: bool


def stage_files(intake_id: int, uploads: list[tuple[str, bytes]], actor: str,
                actor_role: Role, intakes: IntakeRepository, store: FileStore,
                audit: AuditRepository, queue: IndexQueue, state: DocumentIndexState,
                max_files: int = 30) -> list[StagedFile]:
    """Stage files on the intake and queue them for indexing. The same bytes twice is a
    no-op (duplicate); the same file name with new bytes adds a version. Extraction is
    queued too: the worker starts it once every staged file is indexed."""
    require(actor_role, Capability.CREATE_DEAL, "add files to a deal intake")
    intake = _get(intake_id, intakes, for_update=True)
    _open(intake)
    existing = intakes.files(intake_id)
    out: list[StagedFile] = []
    now = utcnow()
    for filename, content in uploads:
        sha = store.put(content)
        same = next((d for d in existing if d.sha256 == sha), None)
        if same is not None:
            out.append(StagedFile(same, True))
            continue
        named = next((d for d in existing if d.filename == filename), None)
        if named is not None:
            doc = intakes.add_file_version(named.id, sha, len(content), actor, now)
        else:
            if len(existing) >= max_files:
                raise RuleViolation(f"An intake takes at most {max_files} files")
            doc = intakes.add_file(Document(
                id=None, deal_id=None, intake_id=intake.id,
                doc_class=guess_doc_class(filename), filename=filename, sha256=sha,
                byte_size=len(content), current_version=1, contains_upsi=False,
                sensitivity=2, uploaded_by=actor, uploaded_at=now))
        enqueue(doc, actor, queue, state)
        existing = [d for d in existing if d.id != doc.id] + [doc]
        out.append(StagedFile(doc, False))
        _audit(audit, actor, "intake_file_staged", intake, document_id=doc.id, sha256=sha,
               version=doc.current_version)
    if any(not f.duplicate for f in out):
        intake.status = "processing"
        _queue_extraction(intake)
        intakes.save(intake)
    return out


def _queue_extraction(intake: Intake) -> None:
    """Extraction runs once every staged file is indexed (the worker's claim waits)."""
    if intake.extract_status != "running":
        intake.extract_status = "queued"
        intake.extract_attempts = 0
        intake.extract_not_before = None
        intake.extract_error = None
    intake.progress = {**(intake.progress or {}), "stage": "indexing",
                       "message": "Reading the documents"}


def remove_file(intake_id: int, document_id: int, actor: str, actor_role: Role,
                intakes: IntakeRepository, audit: AuditRepository) -> Intake:
    require(actor_role, Capability.CREATE_DEAL, "remove files from a deal intake")
    intake = _get(intake_id, intakes, for_update=True)
    _open(intake)
    if not intakes.delete_file(intake_id, document_id):
        raise NotFound("File not found on this intake")
    _audit(audit, actor, "intake_file_removed", intake, document_id=document_id)
    # The removed file's values and citations must go: extract again from what is left.
    _drop_citations(intake, document_id)
    if intakes.files(intake_id):
        intake.status = "processing"
        _queue_extraction(intake)
    else:
        intake.status, intake.extract_status = "draft", "idle"
        intake.progress = {}
    return intakes.save(intake)


def _drop_citations(intake: Intake, document_id: int) -> None:
    for rec in intake.fields.values():
        rec["citations"] = [c for c in rec.get("citations") or []
                            if c.get("document_id") != document_id]
    for conflict in intake.conflicts:
        for cand in conflict.get("candidates") or []:
            cand["citations"] = [c for c in cand.get("citations") or []
                                 if c.get("document_id") != document_id]


def request_extraction(intake_id: int, actor: str, actor_role: Role,
                       intakes: IntakeRepository, audit: AuditRepository) -> Intake:
    require(actor_role, Capability.CREATE_DEAL, "extract a deal intake")
    intake = _get(intake_id, intakes, for_update=True)
    _open(intake)
    if not intakes.files(intake_id):
        raise RuleViolation("Add at least one document before extracting")
    if intake.extract_status == "running":
        raise Conflict("Extraction is already running")
    intake.status = "processing"
    _queue_extraction(intake)
    _audit(audit, actor, "intake_extraction_requested", intake)
    return intakes.save(intake)


# ---------------------------------------------------------------------------- extraction

def apply_extraction(intake: Intake, result: ExtractionResult) -> Intake:
    """Fold an extraction into the intake without losing the creator's work: their own
    values stay (the new extraction becomes their auto_value), an accept survives when the
    value did not change, and a conflict they resolved stays resolved while their pick is
    still among the candidates."""
    old_fields, old_conflicts = intake.fields or {}, intake.conflicts or []
    fields: dict[str, dict] = {}
    for key, rec in result.fields.items():
        fields[key] = {**rec, "accepted": False, "edited": False,
                       "conflict_id": rec.get("conflict_id")}
    cls = result.transaction_class
    specs = {s.key: s for s in F.specs_for(schema_for(cls))}
    for key, old in old_fields.items():
        new = fields.get(key)
        if old.get("source") == "user":
            base = new or {"auto_value": None, "confidence": None, "citations": [],
                           "note": None}
            spec = specs.get(key)
            auto = base.get("auto_value")
            fields[key] = {**base, "value": old.get("value"), "source": "user",
                           "accepted": True, "error": old.get("error"), "conflict_id": None,
                           "edited": auto is not None and not (
                               spec and F.same_value(spec, old.get("value"), auto))}
        elif new is not None and old.get("accepted") and key in specs \
                and F.same_value(specs[key], old.get("value"), new.get("value")):
            new["accepted"] = True
    conflicts = []
    for conflict in result.conflicts:
        key = conflict["field"]
        rec = fields.get(key) or {}
        spec = specs.get(key)
        if rec.get("source") == "user":
            continue    # the creator's own value settles it
        previous = next((c for c in old_conflicts if c.get("field") == key
                         and c.get("resolved") and c.get("chosen") is not None), None)
        if previous is not None and spec is not None:
            picked = previous["candidates"][previous["chosen"]]["value"]
            idx = next((i for i, cand in enumerate(conflict["candidates"])
                        if F.same_value(spec, cand["value"], picked)), None)
            if idx is not None:
                _choose(rec, conflict, idx, spec)
        conflicts.append(conflict)
    intake.fields, intake.conflicts = fields, conflicts
    intake.transaction_class = (fields.get("transaction_class") or {}).get("value") or cls
    return intake


def _choose(rec: dict, conflict: dict, idx: int, spec: F.FieldSpec) -> None:
    cand = conflict["candidates"][idx]
    conflict["chosen"], conflict["resolved"] = idx, True
    rec.update(value=cand["value"], source=cand["source"], confidence=cand["confidence"],
               citations=cand["citations"], accepted=True, conflict_id=None,
               edited=not F.same_value(spec, cand["value"], rec.get("auto_value")))


# ---------------------------------------------------------------------------- edits

def update_intake(intake_id: int, patch: dict, actor: str, actor_role: Role,
                  intakes: IntakeRepository, audit: AuditRepository) -> Intake:
    """The creator's edits (autosaved). A value they type is theirs (source 'user'), kept
    as typed when it does not validate (with the error, so nothing is lost); choosing a
    conflict candidate or accepting a value marks it accepted."""
    require(actor_role, Capability.CREATE_DEAL, "edit a deal intake")
    intake = _get(intake_id, intakes, for_update=True)
    _open(intake)
    changed: list[str] = []
    if "hints" in patch and isinstance(patch["hints"], dict):
        intake.hints = {**(intake.hints or {}), **{
            k: v for k, v in patch["hints"].items()
            if k in ("company_name", "cin", "transaction_class_hint")}}
        changed.append("hints")
    if "external_id" in patch:
        ext = (patch["external_id"] or "").strip() or None
        if ext is not None and not _EXTERNAL_ID.match(ext):
            raise RuleViolation("external_id: letters, digits, '-' and '_' only, at most 32")
        intake.external_id = ext
        changed.append("external_id")
    if patch.get("transaction_class") is not None:
        patch.setdefault("fields", {})["transaction_class"] = {
            "value": patch["transaction_class"]}
    for key, change in (patch.get("fields") or {}).items():
        specs = spec_by_key(intake)
        spec = specs.get(key)
        if spec is None:
            raise RuleViolation(f"Unknown field {key!r}")
        if not isinstance(change, dict):
            raise RuleViolation(f"{key}: give an object with 'value' and/or 'accepted'")
        rec = intake.fields.get(key)
        if "value" in change:
            raw = change["value"]
            value, error = F.normalise_value(spec, raw)
            if error is None and spec.type in ("text", "textarea") and raw not in (None, ""):
                value = F._clean_text(raw, spec.max_length)
            intake.fields[key] = _user_record(raw if error else value, rec, error)
            if spec.key in ("company_name", "cin", "transaction_class"):
                intake.fields[key]["edited"] = rec is not None and rec.get(
                    "auto_value") is not None and not F.same_value(
                        spec, intake.fields[key]["value"], rec.get("auto_value"))
            else:
                intake.fields[key]["edited"] = (rec or {}).get("auto_value") is not None \
                    and not F.same_value(spec, intake.fields[key]["value"],
                                         (rec or {}).get("auto_value"))
            for conflict in intake.conflicts:
                if conflict["field"] == key and not conflict.get("resolved"):
                    conflict["resolved"], conflict["chosen"] = True, None
            if key == "transaction_class":
                intake.transaction_class = value if error is None else None
                _derive_profile(intake)
        if "accepted" in change and key in intake.fields:
            intake.fields[key]["accepted"] = bool(change["accepted"])
        changed.append(key)
    for cid, choice in (patch.get("conflicts") or {}).items():
        conflict = next((c for c in intake.conflicts if c["id"] == cid), None)
        if conflict is None:
            raise RuleViolation(f"Unknown conflict {cid!r}")
        idx = (choice or {}).get("chosen")
        if not isinstance(idx, int) or not 0 <= idx < len(conflict["candidates"]):
            raise RuleViolation(f"{cid}: chosen must be a candidate index")
        spec = spec_by_key(intake).get(conflict["field"])
        rec = intake.fields.setdefault(conflict["field"], {"auto_value": None})
        _choose(rec, conflict, idx, spec or F.BASE_BY_KEY["company_name"])
        changed.append(f"conflict:{cid}")
    files = {d.id: d for d in intakes.files(intake_id)}
    for file_id, change in (patch.get("files") or {}).items():
        doc = files.get(int(file_id))
        if doc is None:
            raise NotFound(f"File {file_id} not found on this intake")
        if (change or {}).get("doc_class"):
            try:
                intakes.set_file_class(doc.id, DocClass(change["doc_class"]).value)
            except ValueError:
                raise RuleViolation(f"Unknown doc_class {change['doc_class']!r}") from None
            changed.append(f"file:{doc.id}")
    saved = intakes.save(intake)
    if changed:
        _audit(audit, actor, "intake_updated", saved, changed=sorted(set(changed))[:50])
    return saved


def _derive_profile(intake: Intake) -> None:
    """After a class change, prefill the new class's profile from the common fields."""
    from aura.core.services.intake_extraction import derived_profile_candidates
    specs = F.profile_fields(schema_for(intake.transaction_class))
    for cand in derived_profile_candidates(intake.fields, specs):
        if intake.fields.get(cand.key, {}).get("value") is None:
            intake.fields[cand.key] = {
                "value": cand.value, "auto_value": cand.value, "confidence": cand.confidence,
                "source": cand.source, "citations": [c.as_dict() for c in cand.citations],
                "accepted": False, "edited": False, "error": None, "note": None,
                "conflict_id": None}


def discard_intake(intake_id: int, actor: str, actor_role: Role, intakes: IntakeRepository,
                   audit: AuditRepository) -> None:
    """Discard a draft: its staged documents, chunks and index jobs are deleted (the stored
    bytes stay in the content-addressed store, which other documents may share)."""
    require(actor_role, Capability.CREATE_DEAL, "discard a deal intake")
    intake = _get(intake_id, intakes, for_update=True)
    _open(intake)
    for doc in intakes.files(intake_id):
        intakes.delete_file(intake_id, doc.id)
    intake.status, intake.extract_status = "discarded", "idle"
    intakes.save(intake)
    _audit(audit, actor, "intake_discarded", intake)


# ---------------------------------------------------------------------------- review

def file_stage(doc: Document, job_status: str | None) -> str:
    if doc.index_status == "indexed":
        return "indexed"
    if doc.index_status == "failed":
        return "failed"
    return "parsing" if job_status == "running" else "uploaded"


@dataclass
class Review:
    needs_review: int
    unresolved_conflicts: int
    missing_required: list[str]
    errors: dict[str, str]
    unaccepted: list[str]
    files_pending: int
    ready: bool
    field_flags: dict[str, tuple[bool, bool]] = field(default_factory=dict)


def review(intake: Intake, stages: dict[int, str], threshold: float) -> Review:
    specs = specs_for(intake)
    values = {k: r.get("value") for k, r in intake.fields.items()}
    errors: dict[str, str] = {}
    flags: dict[str, tuple[bool, bool]] = {}
    unaccepted: list[str] = []
    for spec in specs:
        rec = intake.fields.get(spec.key)
        if not rec:
            continue
        value = rec.get("value")
        if rec.get("error") and value is not None:
            errors[spec.key] = rec["error"]
        auto = rec.get("source") != "user"
        conf = rec.get("confidence")
        needs = auto and value is not None and conf is not None and conf < threshold
        confirm = auto and spec.valuation and value is not None and (conf or 0) < \
            F.VALUATION_CONFIDENCE
        flags[spec.key] = (needs, confirm)
        if (needs or confirm) and not rec.get("accepted"):
            unaccepted.append(spec.key)
    for key, message in F.sanity_errors(values).items():
        if (intake.fields.get(key) or {}).get("source") == "user" or key not in errors:
            errors.setdefault(key, message)
    missing = [s.key for s in specs if s.required and values.get(s.key) in (None, "", [])]
    unresolved = sum(1 for c in intake.conflicts if not c.get("resolved"))
    pending = sum(1 for s in stages.values() if s in ("uploaded", "parsing"))
    busy = intake.extract_status in ("queued", "running")
    ready = not (errors or missing or unresolved or unaccepted or pending or busy)
    return Review(needs_review=len(unaccepted), unresolved_conflicts=unresolved,
                  missing_required=missing, errors=errors, unaccepted=unaccepted,
                  files_pending=pending, ready=ready, field_flags=flags)


def progress_view(intake: Intake, files: list[Document], stages: dict[int, str]) -> dict:
    total = len(files)
    indexed = sum(1 for s in stages.values() if s == "indexed")
    failed = sum(1 for s in stages.values() if s == "failed")
    stored = intake.progress or {}
    groups_total, groups_done = int(stored.get("groups_total") or 0), \
        int(stored.get("groups_done") or 0)
    if total and indexed + failed < total:
        stage = "indexing"
        percent = int(45 * (indexed + failed) / total)
        message = f"Reading {total} file{'s' if total != 1 else ''}: {indexed + failed} done"
    elif intake.extract_status in ("queued", "running"):
        stage = "extracting"
        frac = groups_done / groups_total if groups_total else 0
        percent = 50 + int(48 * frac)
        message = stored.get("message") or "Extracting fields"
    elif intake.extract_status == "dead_letter":
        stage, percent, message = "failed", 100, intake.extract_error or "Extraction failed"
    elif intake.extract_status == "done":
        stage, percent, message = "ready", 100, "Ready for review"
    else:
        stage, percent, message = "idle", 0, "Add documents to begin" if not total else ""
    return {"stage": stage, "percent": percent, "message": message, "files_total": total,
            "files_indexed": indexed, "files_failed": failed, "groups_total": groups_total,
            "groups_done": groups_done}


# ---------------------------------------------------------------------------- confirm

@dataclass
class ConfirmResult:
    deal: object
    warnings: list[str]
    intake: Intake


class IntakeInvalid(RuleViolation):
    """422 with the problems field by field."""

    def __init__(self, field_errors: dict[str, str]):
        n = len(field_errors)
        super().__init__(f"{n} field{'s' if n != 1 else ''} need{'s' if n == 1 else ''} "
                         "attention before the deal can be created")
        self.field_errors = field_errors


def confirm_errors(intake: Intake, stages: dict[int, str], threshold: float
                   ) -> tuple[dict[str, str], dict]:
    """Every reason the intake cannot become a deal yet, by field (or 'conflict:<id>'),
    and the validated profile."""
    r = review(intake, stages, threshold)
    errors: dict[str, str] = dict(r.errors)
    for key in r.missing_required:
        errors.setdefault(key, "Required")
    for key in r.unaccepted:
        errors.setdefault(key, "Confirm this value: it was extracted with low confidence"
                          if not F.BASE_BY_KEY.get(key, F.BASE_BY_KEY["revenue_inr"]).valuation
                          else "Confirm this value: valuation inputs need 95% confidence "
                               "or a person's confirmation")
    for c in intake.conflicts:
        if not c.get("resolved"):
            errors[f"conflict:{c['id']}"] = f"Pick the right {c['label']}"
    if r.files_pending:
        errors["files"] = "Some documents are still being read"
    if intake.extract_status in ("queued", "running"):
        errors["extraction"] = "Extraction is still running"
    specs = spec_by_key(intake)
    for key, rec in intake.fields.items():   # re-validate everything that will be saved
        spec = specs.get(key)
        if spec is None or rec.get("value") is None:
            continue
        _, error = F.normalise_value(spec, rec["value"])
        if error:
            errors.setdefault(key, error)
    profile = {}
    if intake.transaction_class:
        schema = schema_for(intake.transaction_class)
        profile = F.build_profile({k: r.get("value") for k, r in intake.fields.items()},
                                  schema)
        for path, message in profile_errors(intake.transaction_class, profile):
            key = F.PROFILE_PREFIX + path.split(".")[0] if path else "profile"
            if path and F.PROFILE_PREFIX + path in specs:
                key = F.PROFILE_PREFIX + path
            errors.setdefault(key, message)
    return errors, profile


def override_summary(intake: Intake) -> dict:
    """Auto-filled fields (extraction gave a value) and how many the creator changed."""
    auto = [k for k, r in intake.fields.items() if r.get("auto_value") not in (None, [], "")]
    changed = [k for k in auto if intake.fields[k].get("edited")]
    return {"auto_filled": len(auto), "changed": len(changed), "changed_fields": changed[:60]}


def confirm_intake(intake_id: int, external_id: str | None, name: str | None, actor: str,
                   actor_role: Role, threshold: float, intakes: IntakeRepository,
                   deals: DealRepository, history: StageHistoryRepository,
                   audit: AuditRepository, walls: WallRepository, users: UserRepository,
                   parties: PartyRepository, mandates: MandateRepository) -> ConfirmResult:
    """Create the deal from the intake, in the caller's unit of work: all or nothing."""
    require(actor_role, Capability.CREATE_DEAL, "create deals")
    intake = _get(intake_id, intakes, for_update=True)
    _open(intake)
    files = intakes.files(intake_id)
    stages = {d.id: file_stage(d, s) for d, s in
              ((d, intakes.file_stages(intake_id).get(d.id)) for d in files)}
    if name:
        intake.fields["deal_name"] = _user_record(name.strip()[:200],
                                                  intake.fields.get("deal_name"))
    errors, profile = confirm_errors(intake, stages, threshold)
    ext = (external_id or intake.external_id or "").strip() or None
    if ext is not None and not _EXTERNAL_ID.match(ext):
        errors["external_id"] = "Letters, digits, '-' and '_' only, at most 32"
    if errors:
        raise IntakeInvalid(errors)
    v = {k: r.get("value") for k, r in intake.fields.items()}
    cls = TransactionClass(intake.transaction_class)
    warnings: list[str] = []

    deal = None
    for _ in range(20 if ext is None else 1):
        candidate = ext or intakes.next_external_id()
        try:
            deal = create_deal(candidate, v["deal_name"], cls, actor, actor_role, deals,
                               history, audit, walls, users, profile=profile,
                               profile_schema_version=CURRENT_PROFILE_VERSION)
            break
        except Conflict:
            if ext is not None:
                raise IntakeInvalid({"external_id": f"Deal {ext} already exists"}) from None
    if deal is None:
        raise Conflict("Could not find a free deal id")

    # The company and the other parties: matched by identifier first, else created.
    company_ids = [PartyIdentifier(IdentifierScheme(s.upper()), v[s])
                   for s in ("cin", "pan", "gstin", "llpin") if v.get(s)]
    company_type = PartyType.LLP if v.get("llpin") and not v.get("cin") else PartyType.COMPANY
    linked: set[tuple[int, str]] = set()
    party_ids: list[int] = []

    def attach(display: str, ptype: PartyType, idents: list[PartyIdentifier], role: str):
        party = None
        for ident in idents:
            party = parties.find_by_identifier(ident.scheme.value, ident.value)
            if party is not None:
                break
        if party is None and not idents:
            party = next((p for p in parties.list_all()
                          if F.canonical_text(p.display_name) == F.canonical_text(display)),
                         None)
        if party is None:
            party = create_party(ptype, display, idents, actor, actor_role, parties, audit)
        if (party.id, role) not in linked:
            link_party(deal.id, party.id, PartyRole(role), actor, actor_role, deals,
                       parties, audit)
            linked.add((party.id, role))
            party_ids.append(party.id)

    attach(v["company_name"], company_type, company_ids, ROLE_FOR_CLASS[cls.value])
    for p in v.get("parties") or []:
        if not p.get("include") or F.canonical_text(p["name"]) == F.canonical_text(
                v["company_name"]):
            continue
        idents = [PartyIdentifier(IdentifierScheme(i["scheme"]), i["value"])
                  for i in p.get("identifiers") or []]
        try:
            attach(p["name"], PartyType(p.get("party_type") or "company"), idents, p["role"])
        except (Conflict, RuleViolation, ValueError) as exc:
            warnings.append(f"Party {p['name']} was not added: {exc}")

    criteria = [MandateCriterion(c["criterion_key"], CriterionOperator(c["operator"]),
                                 c["value"], CriterionHardness(c["hardness"]), c.get("weight"))
                for c in F.clean_criteria(v.get("mandate_criteria") or []) if c.get("include")]
    side = v.get("side")
    if side or criteria:
        try:
            create_mandate(deal.id, f"{v['deal_name']} mandate",
                           (v.get("purpose") or "")[:2000],
                           MandateSide(side or "raise"), MandateStatus.DRAFT, criteria, actor,
                           actor_role, deals, mandates, audit)
        except RuleViolation as exc:
            raise IntakeInvalid({"mandate_criteria": str(exc)}) from None

    flags = [f["flag"] for f in v.get("regulatory_flags") or [] if f.get("include")]
    if flags:
        if can(actor_role, Capability.EDIT_REGULATORY_FLAGS):
            deal = set_regulatory_flags(deal.id, flags, actor, actor_role, deals, audit)
        else:
            warnings.append("Regulatory flags " + ", ".join(flags) + " were not set: the "
                            f"{actor_role.value} role cannot set them; ask a dealmaker or "
                            "compliance")

    moved = intakes.move_to_deal(intake_id, deal.id)
    now = utcnow()
    for doc in moved:
        audit.append(AuditEntry(id=None, job_id=None, deal_id=deal.id, actor=actor,
                                action="document_uploaded", created_at=now,
                                payload={"document_id": doc.id, "sha256": doc.sha256,
                                         "doc_class": doc.doc_class.value,
                                         "version": doc.current_version,
                                         "from_intake": intake_id}))
    overrides = override_summary(intake)
    intake.status, intake.confirmed_deal_id = "confirmed", deal.id
    intake.extract_meta = {**(intake.extract_meta or {}), "override": overrides,
                           "confirmed_at": now.isoformat()}
    intake = intakes.save(intake)
    audit.append(AuditEntry(id=None, job_id=None, deal_id=deal.id, actor=actor,
                            action="intake_confirmed", created_at=now,
                            payload={"intake_id": intake_id, "deal_id": deal.id,
                                     "external_id": deal.external_id,
                                     "documents": len(moved), "parties": len(party_ids),
                                     **overrides}))
    return ConfirmResult(deal=deal, warnings=warnings, intake=intake)


def copy_fields(intake: Intake) -> dict:
    return copy.deepcopy(intake.fields)
