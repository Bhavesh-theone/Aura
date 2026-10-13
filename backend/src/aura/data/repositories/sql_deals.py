"""SQL repositories for the deal spine (deals, stages, guards, parties, documents, diligence).

They flush but never commit (the unit of work does). Anything scoped to a deal takes a
`viewer` and filters by wall membership here, so no route can forget to."""
from datetime import datetime


from sqlalchemy import func, or_, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from aura.core.clock import utcnow
from aura.core.domain.deal import Deal, DealSignoff, StageHistoryEntry
from aura.core.domain.diligence import (ChecklistItemTemplate, ConditionPrecedent,
                                        DiligenceItem, Finding)
from aura.core.domain.document import Document, DocumentVersion
from aura.core.domain.extraction import Extraction
from aura.core.domain.enums import (CriterionHardness, CriterionOperator, DealStage,
                                    MandateSide, MandateStatus, PartyRole, TransactionClass)
from aura.core.domain.enums import DiligenceStatus, DocClass
from aura.core.domain.errors import Conflict, NotFound
from aura.core.domain.guard import GuardEvaluation, StageGuard
from aura.core.domain.mandate import Mandate, MandateCriterion
from aura.core.domain.party import DealParty, Party
from aura.core.domain.wall import WallMember
from aura.data import mappers
from aura.data.models.tables import (ChecklistItemTemplateRow, ConditionPrecedentRow, DealPartyRow,
                                     DealRow, DealSignoffRow, DealStageHistoryRow,
                                     DiligenceItemRow, DocAccessLogRow, DocVersionRow,
                                     DocumentRow, ExtractionRow, FindingRow, MandateCriteriaRow,
                                     MandateRow, PartyIdentifierRow, PartyRow, StageGuardRow,
                                     StageGuardEvaluationRow, UserRow, WallMemberRow, WallRow)
from aura.data.walls import SYSTEM, Viewer, bind_viewer, member_deal_ids, walled


class SqlDealRepository:
    def __init__(self, session: Session, viewer: Viewer):
        self.s, self.viewer = session, bind_viewer(session, viewer)

    def _row(self, deal_id: int) -> DealRow | None:
        return self.s.scalars(walled(select(DealRow).where(DealRow.id == deal_id),
                                     self.viewer, DealRow.id)).first()

    def add(self, deal: Deal) -> Deal:
        row = DealRow(external_id=deal.external_id, name=deal.name, stage=deal.stage.value,
                      transaction_class=deal.transaction_class.value, owner=deal.owner,
                      outcome=deal.outcome.value if deal.outcome else None,
                      opened_at=deal.opened_at, closed_at=deal.closed_at,
                      regulatory_flags=list(deal.regulatory_flags),
                      profile=dict(deal.profile),
                      profile_schema_version=deal.profile_schema_version)
        try:
            with self.s.begin_nested():
                self.s.add(row)
                self.s.flush()
        except IntegrityError:
            raise Conflict(f"Deal {deal.external_id} already exists") from None
        self.s.refresh(row)
        return mappers.deal_to_domain(row)

    def get(self, deal_id: int) -> Deal | None:
        row = self._row(deal_id)
        return mappers.deal_to_domain(row) if row else None

    def get_by_external_id(self, external_id: str) -> Deal | None:
        row = self.s.scalars(walled(select(DealRow).where(DealRow.external_id == external_id),
                                    self.viewer, DealRow.id)).first()
        return mappers.deal_to_domain(row) if row else None

    def update(self, deal: Deal) -> Deal:
        row = self._row(deal.id)
        if row is None:
            raise NotFound("Deal not found")
        row.stage = deal.stage.value
        row.outcome = deal.outcome.value if deal.outcome else None
        row.closed_at = deal.closed_at
        row.regulatory_flags = list(deal.regulatory_flags)
        row.profile = dict(deal.profile)
        row.profile_schema_version = deal.profile_schema_version
        self.s.flush()
        self.s.refresh(row)
        return mappers.deal_to_domain(row)

    def list_all(self) -> list[Deal]:
        rows = self.s.scalars(walled(select(DealRow), self.viewer, DealRow.id)
                              .order_by(DealRow.id)).all()
        return [mappers.deal_to_domain(r) for r in rows]


class SqlStageHistoryRepository:
    """Append-only by design; the table also has triggers rejecting UPDATE and DELETE."""

    def __init__(self, session: Session, viewer: Viewer):
        self.s, self.viewer = session, bind_viewer(session, viewer)

    def append(self, entry: StageHistoryEntry) -> StageHistoryEntry:
        row = DealStageHistoryRow(
            deal_id=entry.deal_id,
            from_stage=entry.from_stage.value if entry.from_stage else None,
            to_stage=entry.to_stage.value, entered_at=entry.entered_at, actor=entry.actor,
            reason_code=entry.reason_code, is_regression=entry.is_regression)
        self.s.add(row)
        self.s.flush()
        self.s.refresh(row)
        return mappers.history_to_domain(row)

    def list_for_deal(self, deal_id: int) -> list[StageHistoryEntry]:
        rows = self.s.scalars(walled(select(DealStageHistoryRow)
                                     .where(DealStageHistoryRow.deal_id == deal_id),
                                     self.viewer, DealStageHistoryRow.deal_id)
                              .order_by(DealStageHistoryRow.id)).all()
        return [mappers.history_to_domain(r) for r in rows]

    def list_all(self) -> list[StageHistoryEntry]:
        rows = self.s.scalars(walled(select(DealStageHistoryRow), self.viewer,
                                     DealStageHistoryRow.deal_id)
                              .order_by(DealStageHistoryRow.id)).all()
        return [mappers.history_to_domain(r) for r in rows]


class SqlGuardRepository:
    def __init__(self, session: Session):
        self.s = session

    def list_active(self, from_stage: DealStage, to_stage: DealStage,
                    transaction_class: TransactionClass) -> list[StageGuard]:
        rows = self.s.scalars(
            select(StageGuardRow).where(
                StageGuardRow.from_stage == from_stage.value,
                StageGuardRow.to_stage == to_stage.value,
                StageGuardRow.active.is_(True),
                or_(StageGuardRow.transaction_class.is_(None),
                    StageGuardRow.transaction_class == transaction_class.value),
            ).order_by(StageGuardRow.id)).all()
        return [mappers.guard_to_domain(r) for r in rows]

    def evaluate(self, guard: StageGuard, deal_id: int) -> tuple[bool, dict]:
        """Any exception, or anything but exactly one row and one column, fails."""
        try:
            # A savepoint, so a broken guard cannot roll back the caller's other writes.
            with self.s.begin_nested():
                rows = self.s.execute(text(guard.sql_text), {"deal_id": deal_id}).fetchall()
        except Exception as exc:  # a broken guard must fail closed, whatever went wrong
            return False, {"error": f"{type(exc).__name__}: {exc}"}
        if len(rows) != 1 or len(rows[0]) != 1:
            return False, {"error": "guard must return exactly one row and one column"}
        value = rows[0][0]
        return bool(value), {"value": value}

    def record(self, evaluation: GuardEvaluation) -> GuardEvaluation:
        row = StageGuardEvaluationRow(
            deal_id=evaluation.deal_id, guard_id=evaluation.guard_id,
            attempted_at=evaluation.attempted_at, result=evaluation.result,
            detail=evaluation.detail, actor=evaluation.actor,
            overridden_by=evaluation.overridden_by,
            override_justification=evaluation.override_justification)
        self.s.add(row)
        self.s.flush()
        self.s.refresh(row)
        evaluation.id = row.id
        return evaluation

    def attach_history(self, evaluation_ids: list[int], history_id: int) -> None:
        if not evaluation_ids:
            return
        self.s.execute(update(StageGuardEvaluationRow)
                       .where(StageGuardEvaluationRow.id.in_(evaluation_ids))
                       .values(history_id=history_id))
        self.s.flush()

    def linked_history_ids(self, history_ids: list[int]) -> set[int]:
        if not history_ids:
            return set()
        return set(self.s.scalars(
            select(StageGuardEvaluationRow.history_id).where(
                StageGuardEvaluationRow.history_id.in_(history_ids)).distinct()))


class SqlPartyRepository:
    """Parties are firm-wide; only their links to deals are walled."""

    def __init__(self, session: Session, viewer: Viewer):
        self.s, self.viewer = session, bind_viewer(session, viewer)

    def _identifiers(self, party_id: int) -> list[PartyIdentifierRow]:
        return list(self.s.scalars(select(PartyIdentifierRow)
                                   .where(PartyIdentifierRow.party_id == party_id)
                                   .order_by(PartyIdentifierRow.id)))

    def add(self, party: Party) -> Party:
        row = PartyRow(party_type=party.party_type.value, display_name=party.display_name,
                       created_at=party.created_at)
        try:
            # A savepoint: the unique constraint backstops racing inserts without
            # rolling back the caller's other writes.
            with self.s.begin_nested():
                self.s.add(row)
                self.s.flush()
                self.s.add_all([PartyIdentifierRow(party_id=row.id, scheme=i.scheme.value,
                                                   value=i.value) for i in party.identifiers])
                self.s.flush()
        except IntegrityError:
            raise Conflict("Identifier already registered") from None
        self.s.refresh(row)
        return mappers.party_to_domain(row, self._identifiers(row.id))

    def get(self, party_id: int) -> Party | None:
        row = self.s.get(PartyRow, party_id)
        return mappers.party_to_domain(row, self._identifiers(row.id)) if row else None

    def list_all(self) -> list[Party]:
        rows = self.s.scalars(select(PartyRow).order_by(PartyRow.id)).all()
        return [mappers.party_to_domain(r, self._identifiers(r.id)) for r in rows]

    def find_by_identifier(self, scheme: str, value: str) -> Party | None:
        ident = self.s.scalars(select(PartyIdentifierRow).where(
            PartyIdentifierRow.scheme == scheme, PartyIdentifierRow.value == value)).first()
        return self.get(ident.party_id) if ident else None

    def link(self, link: DealParty) -> DealParty:
        visible = self.s.scalars(walled(select(DealRow.id).where(DealRow.id == link.deal_id),
                                        self.viewer, DealRow.id)).first()
        if visible is None:
            raise NotFound("Deal not found")
        self.s.add(DealPartyRow(deal_id=link.deal_id, party_id=link.party_id,
                                role=link.role.value))
        self.s.flush()
        return link

    def list_for_deal(self, deal_id: int) -> list[DealParty]:
        rows = self.s.execute(
            select(DealPartyRow, PartyRow.display_name)
            .join(PartyRow, PartyRow.id == DealPartyRow.party_id)
            .where(DealPartyRow.deal_id == deal_id,
                   *([] if self.viewer is SYSTEM
                     else [DealPartyRow.deal_id.in_(member_deal_ids(self.viewer))]))
            .order_by(PartyRow.id)).all()
        return [DealParty(deal_id=r.deal_id, party_id=r.party_id, role=PartyRole(r.role),
                          display_name=name) for r, name in rows]


class SqlMandateRepository:
    def __init__(self, session: Session, viewer: Viewer):
        self.s, self.viewer = session, bind_viewer(session, viewer)

    def _to_domain(self, row: MandateRow) -> Mandate:
        crit = self.s.scalars(select(MandateCriteriaRow)
                              .where(MandateCriteriaRow.mandate_id == row.id)
                              .order_by(MandateCriteriaRow.id)).all()
        return Mandate(id=row.id, deal_id=row.deal_id, title=row.title, notes=row.notes,
                       side=MandateSide(row.side), status=MandateStatus(row.status),
                       created_at=row.created_at,
                       criteria=[MandateCriterion(c.criterion_key,
                                                  CriterionOperator(c.operator), c.value,
                                                  CriterionHardness(c.hardness), c.weight)
                                 for c in crit])

    def add(self, mandate: Mandate) -> Mandate:
        row = MandateRow(deal_id=mandate.deal_id, title=mandate.title, notes=mandate.notes,
                         side=mandate.side.value, status=mandate.status.value,
                         created_at=mandate.created_at)
        self.s.add(row)
        self.s.flush()
        self.s.add_all([MandateCriteriaRow(mandate_id=row.id, criterion_key=c.criterion_key,
                                           operator=c.operator.value, value=c.value,
                                           hardness=c.hardness.value, weight=c.weight)
                        for c in mandate.criteria])
        self.s.flush()
        self.s.refresh(row)
        return self._to_domain(row)

    def list_for_deal(self, deal_id: int) -> list[Mandate]:
        rows = self.s.scalars(walled(select(MandateRow).where(MandateRow.deal_id == deal_id),
                                     self.viewer, MandateRow.deal_id)
                              .order_by(MandateRow.id)).all()
        return [self._to_domain(r) for r in rows]


class SqlDocumentRepository:
    def __init__(self, session: Session, viewer: Viewer):
        self.s, self.viewer = session, bind_viewer(session, viewer)

    def _row(self, document_id: int) -> DocumentRow | None:
        return self.s.scalars(walled(select(DocumentRow).where(DocumentRow.id == document_id),
                                     self.viewer, DocumentRow.deal_id)).first()

    def add(self, document: Document) -> Document:
        row = DocumentRow(
            deal_id=document.deal_id, doc_class=document.doc_class.value,
            filename=document.filename, sha256=document.sha256, byte_size=document.byte_size,
            current_version=document.current_version, contains_upsi=document.contains_upsi,
            sensitivity=document.sensitivity, uploaded_by=document.uploaded_by,
            uploaded_at=document.uploaded_at, class_confirmed=document.class_confirmed,
            is_executed=document.is_executed, intake_id=document.intake_id)
        self.s.add(row)
        self.s.flush()
        self.s.add(DocVersionRow(document_id=row.id, version=row.current_version,
                                 sha256=row.sha256, byte_size=row.byte_size,
                                 uploaded_by=row.uploaded_by, uploaded_at=row.uploaded_at))
        self.s.flush()
        self.s.refresh(row)
        return mappers.document_to_domain(row)

    def find_by_filename(self, deal_id: int, filename: str) -> Document | None:
        row = self.s.scalars(walled(select(DocumentRow).where(
            DocumentRow.deal_id == deal_id, DocumentRow.filename == filename),
            self.viewer, DocumentRow.deal_id).order_by(DocumentRow.id.desc())).first()
        return mappers.document_to_domain(row) if row else None

    def add_version(self, document_id: int, sha256: str, byte_size: int, uploaded_by: str,
                    uploaded_at: datetime) -> Document:
        row = self._row(document_id)
        if row is None:
            raise NotFound("Document not found")
        row.current_version += 1
        row.sha256, row.byte_size = sha256, byte_size
        row.uploaded_by, row.uploaded_at = uploaded_by, uploaded_at
        row.is_executed = False
        self.s.add(DocVersionRow(document_id=row.id, version=row.current_version,
                                 sha256=sha256, byte_size=byte_size,
                                 uploaded_by=uploaded_by, uploaded_at=uploaded_at))
        self.s.flush()
        self.s.refresh(row)
        return mappers.document_to_domain(row)

    def list_versions(self, document_id: int) -> list[DocumentVersion]:
        if self._row(document_id) is None:
            return []
        rows = self.s.scalars(select(DocVersionRow).where(
            DocVersionRow.document_id == document_id).order_by(DocVersionRow.version)).all()
        return [mappers.doc_version_to_domain(r) for r in rows]

    def set_executed(self, document_id: int, is_executed: bool) -> Document:
        row = self._row(document_id)
        if row is None:
            raise NotFound("Document not found")
        row.is_executed = is_executed
        self.s.flush()
        self.s.refresh(row)
        return mappers.document_to_domain(row)

    def get(self, document_id: int) -> Document | None:
        row = self._row(document_id)
        return mappers.document_to_domain(row) if row else None

    def list_for_deal(self, deal_id: int) -> list[Document]:
        rows = self.s.scalars(walled(select(DocumentRow).where(DocumentRow.deal_id == deal_id),
                                     self.viewer, DocumentRow.deal_id)
                              .order_by(DocumentRow.id)).all()
        return [mappers.document_to_domain(r) for r in rows]

    def log_access(self, document_id: int, actor: str, action: str) -> None:
        if self._row(document_id) is None:
            raise NotFound("Document not found")
        self.s.add(DocAccessLogRow(document_id=document_id, accessed_by=actor, action=action))
        self.s.flush()

    def set_index_state(self, document_id: int, *, status: str,
                        chunk_count: int | None = None, ocr_used: bool | None = None,
                        page_count: int | None = None, warnings: list[str] | None = None,
                        error: str | None = None, indexed_at: datetime | None = None) -> None:
        """The document's index_* columns (the indexing queue's own bookkeeping)."""
        row = self._row(document_id)
        if row is None:
            raise NotFound("Document not found")
        row.index_status, row.index_error = status, error
        if chunk_count is not None:
            row.chunk_count = chunk_count
        if ocr_used is not None:
            row.ocr_used = ocr_used
        if page_count is not None:
            row.page_count = page_count
        if warnings is not None:
            row.index_warnings = list(warnings)
        if indexed_at is not None:
            row.indexed_at = indexed_at
        self.s.flush()

    def update_classification(self, document_id: int, doc_class: DocClass,
                              confirmed: bool) -> Document:
        row = self._row(document_id)
        if row is None:
            raise NotFound("Document not found")
        row.doc_class, row.class_confirmed = doc_class.value, confirmed
        self.s.flush()
        self.s.refresh(row)
        return mappers.document_to_domain(row)


class SqlDiligenceRepository:
    def __init__(self, session: Session, viewer: Viewer):
        self.s, self.viewer = session, bind_viewer(session, viewer)

    def _row(self, item_id: int) -> DiligenceItemRow | None:
        return self.s.scalars(walled(select(DiligenceItemRow)
                                     .where(DiligenceItemRow.id == item_id),
                                     self.viewer, DiligenceItemRow.deal_id)).first()

    def list_templates(self, transaction_class: TransactionClass) -> list[ChecklistItemTemplate]:
        rows = self.s.scalars(
            select(ChecklistItemTemplateRow).where(or_(
                ChecklistItemTemplateRow.transaction_class.is_(None),
                ChecklistItemTemplateRow.transaction_class == transaction_class.value,
            )).order_by(ChecklistItemTemplateRow.id)).all()
        return [mappers.template_to_domain(r) for r in rows]

    def add_item(self, item: DiligenceItem) -> DiligenceItem:
        row = DiligenceItemRow(deal_id=item.deal_id, template_id=item.template_id,
                               prompt=item.prompt, severity=item.severity.value,
                               status=item.status.value,
                               evidence_doc_ids=item.evidence_doc_ids,
                               waiver_justification=item.waiver_justification)
        self.s.add(row)
        self.s.flush()
        self.s.refresh(row)
        return mappers.diligence_to_domain(row)

    def get_item(self, item_id: int) -> DiligenceItem | None:
        row = self._row(item_id)
        return mappers.diligence_to_domain(row) if row else None

    def update_item(self, item: DiligenceItem) -> DiligenceItem:
        row = self._row(item.id)
        if row is None:
            raise NotFound("Diligence item not found")
        row.status = item.status.value
        row.evidence_doc_ids = list(item.evidence_doc_ids)
        row.waiver_justification = item.waiver_justification
        self.s.flush()
        self.s.refresh(row)
        return mappers.diligence_to_domain(row)

    def list_items(self, deal_id: int) -> list[DiligenceItem]:
        rows = self.s.scalars(walled(select(DiligenceItemRow)
                                     .where(DiligenceItemRow.deal_id == deal_id),
                                     self.viewer, DiligenceItemRow.deal_id)
                              .order_by(DiligenceItemRow.id)).all()
        return [mappers.diligence_to_domain(r) for r in rows]

    def count_open_blockers(self) -> int:
        open_states = [st.value for st in DiligenceStatus
                       if st not in (DiligenceStatus.SATISFIED, DiligenceStatus.WAIVED)]
        # A blocker on a deal that has closed or ended is no longer anyone's open work.
        live_deals = select(DealRow.id).where(DealRow.outcome.is_(None))
        stmt = walled(select(func.count(DiligenceItemRow.id)).where(
            DiligenceItemRow.severity == "blocker", DiligenceItemRow.status.in_(open_states),
            DiligenceItemRow.deal_id.in_(live_deals)),
            self.viewer, DiligenceItemRow.deal_id)
        return self.s.scalar(stmt) or 0


class SqlConditionRepository:
    def __init__(self, session: Session, viewer: Viewer):
        self.s, self.viewer = session, bind_viewer(session, viewer)

    def _row(self, cp_id: int) -> ConditionPrecedentRow | None:
        return self.s.scalars(walled(select(ConditionPrecedentRow)
                                     .where(ConditionPrecedentRow.id == cp_id),
                                     self.viewer, ConditionPrecedentRow.deal_id)).first()

    def add(self, cp: ConditionPrecedent) -> ConditionPrecedent:
        row = ConditionPrecedentRow(deal_id=cp.deal_id, description=cp.description,
                                    cp_type=cp.cp_type, status=cp.status.value,
                                    waiver_justification=cp.waiver_justification)
        self.s.add(row)
        self.s.flush()
        self.s.refresh(row)
        return mappers.condition_to_domain(row)

    def get(self, cp_id: int) -> ConditionPrecedent | None:
        row = self._row(cp_id)
        return mappers.condition_to_domain(row) if row else None

    def update(self, cp: ConditionPrecedent) -> ConditionPrecedent:
        row = self._row(cp.id)
        if row is None:
            raise NotFound("Condition not found")
        row.status = cp.status.value
        row.waiver_justification = cp.waiver_justification
        self.s.flush()
        self.s.refresh(row)
        return mappers.condition_to_domain(row)

    def list_for_deal(self, deal_id: int) -> list[ConditionPrecedent]:
        rows = self.s.scalars(walled(select(ConditionPrecedentRow)
                                     .where(ConditionPrecedentRow.deal_id == deal_id),
                                     self.viewer, ConditionPrecedentRow.deal_id)
                              .order_by(ConditionPrecedentRow.id)).all()
        return [mappers.condition_to_domain(r) for r in rows]


class SqlWallRepository:
    def __init__(self, session: Session, viewer: Viewer):
        self.s, self.viewer = session, bind_viewer(session, viewer)

    def _user_id(self, username: str) -> int:
        user_id = self.s.scalar(select(UserRow.id).where(UserRow.username == username))
        if user_id is None:
            raise NotFound(f"User {username} not found")
        return user_id

    def _wall_id(self, deal_id: int) -> int | None:
        return self.s.scalar(walled(select(WallRow.id).where(WallRow.deal_id == deal_id),
                                    self.viewer, WallRow.deal_id))

    def create(self, deal_id: int, name: str, member: str) -> None:
        wall = WallRow(deal_id=deal_id, name=name)
        self.s.add(wall)
        self.s.flush()
        self.s.add(WallMemberRow(wall_id=wall.id, user_id=self._user_id(member),
                                 added_at=utcnow()))
        self.s.flush()

    def _active(self, wall_id: int, user_id: int) -> WallMemberRow | None:
        return self.s.scalars(select(WallMemberRow).where(
            WallMemberRow.wall_id == wall_id, WallMemberRow.user_id == user_id,
            WallMemberRow.removed_at.is_(None))).first()

    def members(self, deal_id: int) -> list[WallMember]:
        wall_id = self._wall_id(deal_id)
        if wall_id is None:
            return []
        rows = self.s.execute(
            select(UserRow.username, WallMemberRow.added_at)
            .join(WallMemberRow, WallMemberRow.user_id == UserRow.id)
            .where(WallMemberRow.wall_id == wall_id, WallMemberRow.removed_at.is_(None))
            .order_by(WallMemberRow.id)).all()
        return [WallMember(username=u, added_at=a) for u, a in rows]

    def add_member(self, deal_id: int, username: str) -> bool:
        wall_id = self._wall_id(deal_id)
        if wall_id is None:
            raise NotFound("Deal not found")
        user_id = self._user_id(username)
        if self._active(wall_id, user_id) is not None:
            return False
        self.s.add(WallMemberRow(wall_id=wall_id, user_id=user_id,
                                 added_at=utcnow()))
        self.s.flush()
        return True

    def remove_member(self, deal_id: int, username: str) -> bool:
        wall_id = self._wall_id(deal_id)
        if wall_id is None:
            raise NotFound("Deal not found")
        row = self._active(wall_id, self._user_id(username))
        if row is None:
            return False
        row.removed_at = utcnow()
        self.s.flush()
        return True


class SqlFindingRepository:
    def __init__(self, session: Session, viewer: Viewer):
        self.s, self.viewer = session, bind_viewer(session, viewer)

    def add(self, finding: Finding) -> Finding:
        row = FindingRow(diligence_item_id=finding.diligence_item_id,
                         finding_type=finding.finding_type.value,
                         description=finding.description,
                         quantified_impact_inr=finding.quantified_impact_inr,
                         affects_valuation=finding.affects_valuation,
                         raised_by=finding.raised_by, raised_at=finding.raised_at)
        self.s.add(row)
        self.s.flush()
        self.s.refresh(row)
        return mappers.finding_to_domain(row, finding.deal_id)

    def list_for_deal(self, deal_id: int) -> list[Finding]:
        stmt = (select(FindingRow)
                .join(DiligenceItemRow, DiligenceItemRow.id == FindingRow.diligence_item_id)
                .where(DiligenceItemRow.deal_id == deal_id))
        rows = self.s.scalars(walled(stmt, self.viewer, DiligenceItemRow.deal_id)
                              .order_by(FindingRow.id)).all()
        return [mappers.finding_to_domain(r, deal_id) for r in rows]


class SqlExtractionRepository:
    """Extractions hang off documents, so the document's deal decides who may see them."""

    def __init__(self, session: Session, viewer: Viewer):
        self.s, self.viewer = session, bind_viewer(session, viewer)

    def _row(self, extraction_id: int) -> ExtractionRow | None:
        stmt = (select(ExtractionRow)
                .join(DocumentRow, DocumentRow.id == ExtractionRow.document_id)
                .where(ExtractionRow.id == extraction_id))
        return self.s.scalars(walled(stmt, self.viewer, DocumentRow.deal_id)).first()

    def add(self, extraction: Extraction) -> Extraction:
        row = ExtractionRow(
            document_id=extraction.document_id, version=extraction.version,
            schema_name=extraction.schema_name, payload=extraction.payload,
            confidence=extraction.confidence, feeds_valuation=extraction.feeds_valuation,
            human_verified_by=extraction.human_verified_by,
            human_verified_at=extraction.human_verified_at,
            model_run_id=extraction.model_run_id, created_at=extraction.created_at)
        self.s.add(row)
        self.s.flush()
        self.s.refresh(row)
        return mappers.extraction_to_domain(row)

    def get(self, extraction_id: int) -> Extraction | None:
        row = self._row(extraction_id)
        return mappers.extraction_to_domain(row) if row else None

    def update(self, extraction: Extraction) -> Extraction:
        row = self._row(extraction.id)
        if row is None:
            raise NotFound("Extraction not found")
        row.feeds_valuation = extraction.feeds_valuation
        row.human_verified_by = extraction.human_verified_by
        row.human_verified_at = extraction.human_verified_at
        self.s.flush()
        self.s.refresh(row)
        return mappers.extraction_to_domain(row)

    def list_for_deal(self, deal_id: int) -> list[Extraction]:
        stmt = (select(ExtractionRow)
                .join(DocumentRow, DocumentRow.id == ExtractionRow.document_id)
                .where(DocumentRow.deal_id == deal_id))
        rows = self.s.scalars(walled(stmt, self.viewer, DocumentRow.deal_id)
                              .order_by(ExtractionRow.id)).all()
        return [mappers.extraction_to_domain(r) for r in rows]


class SqlSignoffRepository:
    def __init__(self, session: Session, viewer: Viewer):
        self.s, self.viewer = session, bind_viewer(session, viewer)

    def add(self, signoff: DealSignoff) -> DealSignoff:
        row = DealSignoffRow(deal_id=signoff.deal_id, signed_by=signoff.signed_by,
                             note=signoff.note, signed_at=signoff.signed_at)
        self.s.add(row)
        self.s.flush()
        self.s.refresh(row)
        return mappers.signoff_to_domain(row)

    def list_for_deal(self, deal_id: int) -> list[DealSignoff]:
        rows = self.s.scalars(walled(select(DealSignoffRow)
                                     .where(DealSignoffRow.deal_id == deal_id),
                                     self.viewer, DealSignoffRow.deal_id)
                              .order_by(DealSignoffRow.id)).all()
        return [mappers.signoff_to_domain(r) for r in rows]
