from datetime import datetime, timezone

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import select
from sqlalchemy.orm import Session

from aura.api.security import hash_password
from aura.config import BACKEND_DIR, get_settings
from aura.core.domain.audit import AuditEntry
from aura.core.domain.enums import ChecklistLayer, Role
from aura.core.domain.enums import DealStage as S
from aura.core.domain.enums import TransactionClass
from aura.core.services.create_deal import create_deal
from aura.core.services.deal_profile import (CURRENT_PROFILE_VERSION, changed_keys,
                                             validate_profile)
from aura.data.demo_profiles import DEMO_PROFILES, demo_profile
from aura.data.engine import SessionLocal, engine
from aura.data.models.tables import (ChecklistItemTemplateRow, ChecklistTemplateRow,
                                     StageGuardRow, UserRow, WallMemberRow, WallRow)
from aura.data.repositories.sql import SqlAuditRepository, SqlUserRepository
from aura.data.repositories.sql_deals import (SqlDealRepository, SqlStageHistoryRepository,
                                              SqlWallRepository)
from aura.data.walls import SYSTEM

USERS = [("bhavesh", "admin123", "dealmaker"), ("asha", "analyst123", "analyst"),
         ("priya", "compliance123", "compliance"), ("admin", "admin123", "admin")]
# Members of every seeded deal's wall.
DEMO_WALL_MEMBERS = ["bhavesh", "asha", "priya"]

_DOC = "SELECT EXISTS(SELECT 1 FROM document WHERE deal_id = :deal_id AND {})"
_PARTY_ROLES = "role IN ('buyer', 'investor', 'lender')"
_OPEN_BLOCKER_STATES = "'open', 'requested', 'received', 'under_review', 'failed'"

# (name, from, to, sql, plain-English description, override role). All blocking.
# One set of guards per forward move; regressions and exits need a reason code instead.
GUARDS = [
    ("T1_party_with_identifier", S.ORIGINATED, S.QUALIFIED,
     "SELECT EXISTS(SELECT 1 FROM deal_party dp JOIN party_identifier pi "
     "ON pi.party_id = dp.party_id WHERE dp.deal_id = :deal_id)",
     "At least one party is linked to the deal and has a statutory identifier", "dealmaker"),
    ("T2_engagement_letter", S.QUALIFIED, S.MANDATED,
     _DOC.format("doc_class = 'engagement_letter' AND is_executed"),
     "An engagement letter is on file and marked executed", "dealmaker"),
    ("T3_hard_criterion", S.MANDATED, S.PREPARED,
     "SELECT EXISTS(SELECT 1 FROM mandate m JOIN mandate_criteria c ON c.mandate_id = m.id "
     "WHERE m.deal_id = :deal_id AND c.hardness = 'hard')",
     "A mandate exists with at least one hard criterion", "dealmaker"),
    ("T4_financial_statement", S.PREPARED, S.MARKETED,
     _DOC.format("doc_class = 'financial_statement'"),
     "A financial statement is on file", "dealmaker"),
    ("T5_counterparty_and_nda", S.MARKETED, S.MATCHED,
     "SELECT EXISTS(SELECT 1 FROM deal_party WHERE deal_id = :deal_id AND "
     + _PARTY_ROLES + ") AND EXISTS(SELECT 1 FROM document WHERE deal_id = :deal_id "
     "AND doc_class = 'nda' AND is_executed)",
     "A buyer, investor or lender is linked and an NDA is on file and marked executed",
     "dealmaker"),
    ("T6_two_counterparties", S.MATCHED, S.BID_AUCTION,
     "SELECT COUNT(DISTINCT party_id) >= 2 FROM deal_party WHERE deal_id = :deal_id AND "
     + _PARTY_ROLES,
     "At least two buyers, investors or lenders are linked to the deal", "dealmaker"),
    ("T7_valuation_report", S.BID_AUCTION, S.NEGOTIATION,
     _DOC.format("doc_class = 'valuation_report'"),
     "A valuation report is on file", "dealmaker"),
    ("T8_term_sheet", S.NEGOTIATION, S.DILIGENCE,
     _DOC.format("doc_class = 'term_sheet' AND is_executed"),
     "A term sheet is on file and marked executed", "dealmaker"),
    ("T9_no_open_blockers", S.DILIGENCE, S.DOCUMENTATION,
     "SELECT EXISTS(SELECT 1 FROM diligence_item WHERE deal_id = :deal_id) AND NOT "
     "EXISTS(SELECT 1 FROM diligence_item WHERE deal_id = :deal_id AND severity = 'blocker' "
     "AND status IN (" + _OPEN_BLOCKER_STATES + "))",
     "The diligence checklist exists and no blocker-severity item is still open", "compliance"),
    ("T9_compliance_signoff", S.DILIGENCE, S.DOCUMENTATION,
     "SELECT (SELECT jsonb_array_length(regulatory_flags) FROM deals WHERE id = :deal_id) = 0 "
     "OR EXISTS(SELECT 1 FROM deal_signoff WHERE deal_id = :deal_id)",
     "The deal has no regulatory flags, or compliance has signed it off", "compliance"),
    ("T10_definitive_agreement", S.DOCUMENTATION, S.CONDITIONS_PRECEDENT,
     _DOC.format("doc_class IN ('spa', 'shpa') AND is_executed"),
     "A definitive agreement (SPA or SHPA) is on file and marked executed", "dealmaker"),
    ("T11_all_cps_cleared", S.CONDITIONS_PRECEDENT, S.CLOSED,
     "SELECT EXISTS(SELECT 1 FROM condition_precedent WHERE deal_id = :deal_id) AND NOT "
     "EXISTS(SELECT 1 FROM condition_precedent WHERE deal_id = :deal_id "
     "AND status NOT IN ('satisfied', 'waived'))",
     "At least one condition precedent exists and every one is satisfied or waived",
     "compliance"),
]
# Guards an earlier seed created that a later one replaced. Kept (evaluation rows point at
# them) but switched off.
RETIRED_GUARDS = ["T3_has_document", "T5_counterparty_on_deal"]

# Checklist templates: (name, transaction class or None for all, layer).
CHECKLISTS = [
    ("Base diligence checklist", None, ChecklistLayer.BASE),
    ("Debt diligence checklist", "DEBT", ChecklistLayer.SUBCLASS),
    ("Alliance diligence checklist", "ALLIANCE", ChecklistLayer.SUBCLASS),
]
# (transaction_class or None for all, category, prompt, severity)
TEMPLATES = [
    (None, "corporate", "Certificate of incorporation and constitutional documents", "blocker"),
    (None, "legal", "Litigation and regulatory proceedings disclosure", "blocker"),
    (None, "financial", "Last three years audited financial statements", "material"),
    (None, "tax", "Tax returns and assessment orders", "material"),
    (None, "corporate", "Board and shareholder resolutions authorising the transaction",
     "standard"),
    ("DEBT", "security", "Security documents and charge registration", "material"),
    ("DEBT", "financial", "Debt schedule and existing lender consents", "standard"),
    ("ALLIANCE", "commercial", "Summary of existing commercial agreements", "informational"),
]

DEMO_DEALS = [("D-001", "Sunrise Infra", TransactionClass.DEBT),
              ("D-002", "Ravi Menon Ventures", TransactionClass.ALLIANCE)]


def alembic_config(url: str | None = None) -> Config:
    """Alembic, pointed at a database as its owner (default AURA_MIGRATION_DATABASE_URL)."""
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    url = url or get_settings().migration_database_url
    if url:
        cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return cfg


def migrate() -> None:
    """Bring the database to the latest revision as the schema owner. Without
    AURA_MIGRATION_DATABASE_URL the app cannot migrate (aura_app has no DDL rights), so it
    only checks the schema is already at head and refuses to start otherwise."""
    cfg = alembic_config()
    if get_settings().migration_database_url:
        command.upgrade(cfg, "head")
        return
    head = ScriptDirectory.from_config(cfg).get_current_head()
    with engine.connect() as conn:
        current = MigrationContext.configure(conn).get_current_revision()
    if current != head:
        raise RuntimeError(f"database is at revision {current}, code expects {head}: run "
                           "`uv run alembic upgrade head` with AURA_MIGRATION_DATABASE_URL")


def seed_reference(s: Session) -> None:
    """Users, stage guards and checklist templates. Idempotent."""
    existing = set(s.scalars(select(UserRow.username)))
    for username, password, role in USERS:
        if username not in existing:
            s.add(UserRow(username=username, password_hash=hash_password(password),
                          role=role, active=True))

    # Guards are reference data owned by the code: re-seeding brings an older database's
    # rows up to the current definition (same name, same row, same evaluation history).
    have_guards = {g.guard_name: g for g in s.scalars(select(StageGuardRow))}
    for name, frm, to, sql, description, override_role in GUARDS:
        guard = have_guards.get(name)
        if guard is None:
            s.add(StageGuardRow(guard_name=name, from_stage=frm.value, to_stage=to.value,
                                sql_text=sql, severity="blocking", override_role=override_role,
                                active=True, description=description))
            continue
        guard.from_stage, guard.to_stage = frm.value, to.value
        guard.sql_text, guard.description = sql, description
        guard.severity, guard.override_role, guard.active = "blocking", override_role, True
    for name in RETIRED_GUARDS:
        if name in have_guards:
            have_guards[name].active = False

    if s.scalars(select(ChecklistTemplateRow)).first() is None:
        for name, cls, layer in CHECKLISTS:
            s.add(ChecklistTemplateRow(name=name, transaction_class=cls, layer=layer.value,
                                       version=1))
        s.flush()
    if s.scalars(select(ChecklistItemTemplateRow)).first() is None:
        by_class = {t.transaction_class: t.id for t in s.scalars(select(ChecklistTemplateRow))}
        s.add_all(ChecklistItemTemplateRow(template_id=by_class[cls], transaction_class=cls,
                                           category=cat, prompt=prompt, default_severity=sev)
                  for cls, cat, prompt, sev in TEMPLATES)
    s.commit()


def _ensure_demo_membership(s: Session, deal_ids: list[int]) -> None:
    """The seeded users sit on the seeded deals' walls. A member who was removed on purpose
    stays removed: only users who never had a row are added."""
    audit, walls = SqlAuditRepository(s, SYSTEM), SqlWallRepository(s, SYSTEM)
    for deal_id in deal_ids:
        wall_id = s.scalar(select(WallRow.id).where(WallRow.deal_id == deal_id))
        for username in DEMO_WALL_MEMBERS:
            user_id = s.scalar(select(UserRow.id).where(UserRow.username == username))
            ever = s.scalar(select(WallMemberRow.id).where(
                WallMemberRow.wall_id == wall_id, WallMemberRow.user_id == user_id))
            if ever is None and walls.add_member(deal_id, username):
                audit.append(AuditEntry(id=None, job_id=None, deal_id=deal_id, actor="system",
                                        action="wall_member_added",
                                        created_at=datetime.now(timezone.utc),
                                        payload={"username": username, "reason": "seed"}))


def backfill_demo_profiles(s: Session) -> int:
    """Give demo deals created before deal profiles existed their demo profile. Only an
    empty profile is filled, so an edited one is never overwritten. Returns how many."""
    deals, audit = SqlDealRepository(s, SYSTEM), SqlAuditRepository(s, SYSTEM)
    filled = 0
    for external_id in DEMO_PROFILES:
        deal = deals.get_by_external_id(external_id)
        if deal is None or deal.profile:
            continue
        profile = demo_profile(external_id)
        validate_profile(deal.transaction_class, CURRENT_PROFILE_VERSION, profile)
        deal.profile, deal.profile_schema_version = profile, CURRENT_PROFILE_VERSION
        deals.update(deal)
        audit.append(AuditEntry(id=None, job_id=None, deal_id=deal.id, actor="system",
                                action="deal_profile_updated",
                                created_at=datetime.now(timezone.utc),
                                payload={"reason": "seed",
                                         "profile_schema_version": CURRENT_PROFILE_VERSION,
                                         "changed_keys": changed_keys({}, profile)}))
        filled += 1
    return filled


def seed() -> None:
    migrate()
    with SessionLocal() as s:
        seed_reference(s)
        deals, history, audit, walls = (SqlDealRepository(s, SYSTEM),
                                        SqlStageHistoryRepository(s, SYSTEM),
                                        SqlAuditRepository(s, SYSTEM),
                                        SqlWallRepository(s, SYSTEM))
        deal_ids = []
        for external_id, name, cls in DEMO_DEALS:
            deal = deals.get_by_external_id(external_id)
            if deal is None:
                # bhavesh creates the demo deals, so he is the first member of each wall
                deal = create_deal(external_id, name, cls, "bhavesh", Role.DEALMAKER, deals,
                                   history, audit, walls, SqlUserRepository(s),
                                   profile=demo_profile(external_id))
            deal_ids.append(deal.id)
        _ensure_demo_membership(s, deal_ids)
        backfill_demo_profiles(s)
        s.commit()
