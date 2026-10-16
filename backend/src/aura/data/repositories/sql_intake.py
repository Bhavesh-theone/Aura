"""Deal intakes and their staged documents on PostgreSQL.

Row-level security keeps a draft intake, its documents, chunks and index jobs visible to its
creator only (0004_deal_intake); the user-scoped repository also filters on created_by in
SQL (defence in depth, like `walled`). SYSTEM (the worker) sees every intake.
"""
from datetime import datetime

from sqlalchemy import delete, func, or_, select, text, update
from sqlalchemy.orm import Session

from aura.core.clock import utcnow
from aura.core.domain.document import Document
from aura.core.domain.intake import Intake, StagedChunk
from aura.data import mappers
from aura.data.models.tables import (AgentRunRow, DealIntakeRow, DocChunkRow, DocVersionRow,
                                     DocumentRow, EmbedRunRow, IndexJobRow)
from aura.data.walls import SYSTEM, Viewer, bind_viewer

_COLUMNS = ("created_by", "status", "transaction_class", "fields", "conflicts",
            "confirmed_deal_id", "hints", "external_id", "progress", "extract_status",
            "extract_attempts", "extract_not_before", "extract_claimed_by",
            "extract_claimed_at", "extract_error", "extract_meta", "trace_id", "span_id")
_MUTABLE = tuple(c for c in _COLUMNS if c != "created_by")
EXTERNAL_PREFIX = "AUR-"


def _intake(row: DealIntakeRow) -> Intake:
    return Intake(id=row.id, created_at=row.created_at, updated_at=row.updated_at,
                  **{c: getattr(row, c) for c in _COLUMNS})


class SqlIntakeRepository:
    def __init__(self, session: Session, viewer: Viewer):
        self.s, self.viewer = session, bind_viewer(session, viewer)

    # ------------------------------------------------------------------ intakes

    def _mine(self, stmt):
        if self.viewer is SYSTEM:
            return stmt
        return stmt.where(DealIntakeRow.created_by == self.viewer)

    def _row(self, intake_id: int, for_update: bool = False) -> DealIntakeRow | None:
        stmt = self._mine(select(DealIntakeRow).where(DealIntakeRow.id == intake_id))
        if for_update:
            stmt = stmt.with_for_update()
        return self.s.scalars(stmt.execution_options(populate_existing=True)).first()

    def add(self, intake: Intake) -> Intake:
        row = DealIntakeRow(**{c: getattr(intake, c) for c in _COLUMNS})
        self.s.add(row)
        self.s.flush()
        self.s.refresh(row)
        return _intake(row)

    def get(self, intake_id: int, for_update: bool = False) -> Intake | None:
        row = self._row(intake_id, for_update)
        return _intake(row) if row else None

    def list_open(self) -> list[Intake]:
        rows = self.s.scalars(self._mine(select(DealIntakeRow).where(
            DealIntakeRow.status.in_(("draft", "processing", "review"))))
            .order_by(DealIntakeRow.updated_at.desc(), DealIntakeRow.id.desc())).all()
        return [_intake(r) for r in rows]

    def save(self, intake: Intake) -> Intake:
        row = self._row(intake.id)
        if row is None:
            from aura.core.domain.errors import NotFound
            raise NotFound("Intake not found")
        for c in _MUTABLE:
            setattr(row, c, getattr(intake, c))
        row.updated_at = utcnow()
        self.s.flush()
        self.s.refresh(row)
        return _intake(row)

    # ------------------------------------------------------------------ staged files

    def files(self, intake_id: int) -> list[Document]:
        rows = self.s.scalars(select(DocumentRow).where(
            DocumentRow.intake_id == intake_id, DocumentRow.deal_id.is_(None))
            .order_by(DocumentRow.id).execution_options(populate_existing=True)).all()
        return [mappers.document_to_domain(r) for r in rows]

    def file_stages(self, intake_id: int) -> dict[int, str]:
        rows = self.s.execute(select(IndexJobRow.document_id, IndexJobRow.status).where(
            IndexJobRow.intake_id == intake_id)).all()
        return {doc_id: status for doc_id, status in rows}

    def add_file(self, document: Document) -> Document:
        row = DocumentRow(
            deal_id=None, intake_id=document.intake_id, doc_class=document.doc_class.value,
            filename=document.filename, sha256=document.sha256, byte_size=document.byte_size,
            current_version=1, contains_upsi=document.contains_upsi,
            sensitivity=document.sensitivity, uploaded_by=document.uploaded_by,
            uploaded_at=document.uploaded_at, class_confirmed=False, is_executed=False)
        self.s.add(row)
        self.s.flush()
        self.s.add(DocVersionRow(document_id=row.id, version=1, sha256=row.sha256,
                                 byte_size=row.byte_size, uploaded_by=row.uploaded_by,
                                 uploaded_at=row.uploaded_at))
        self.s.flush()
        self.s.refresh(row)
        return mappers.document_to_domain(row)

    def _doc(self, document_id: int) -> DocumentRow | None:
        return self.s.scalars(select(DocumentRow).where(
            DocumentRow.id == document_id, DocumentRow.deal_id.is_(None),
            DocumentRow.intake_id.is_not(None))).first()

    def add_file_version(self, document_id: int, sha256: str, byte_size: int,
                         uploaded_by: str, uploaded_at: datetime) -> Document:
        row = self._doc(document_id)
        row.current_version += 1
        row.sha256, row.byte_size = sha256, byte_size
        row.uploaded_by, row.uploaded_at = uploaded_by, uploaded_at
        self.s.add(DocVersionRow(document_id=row.id, version=row.current_version,
                                 sha256=sha256, byte_size=byte_size, uploaded_by=uploaded_by,
                                 uploaded_at=uploaded_at))
        self.s.flush()
        self.s.refresh(row)
        return mappers.document_to_domain(row)

    def set_index_state(self, document_id: int, *, status: str, error: str | None = None,
                        **_ignored) -> None:
        """Mark a staged file pending when it is queued (DocumentIndexState for enqueue);
        the worker writes the rest through the SYSTEM document repository."""
        row = self._doc(document_id)
        if row is not None:
            row.index_status, row.index_error = status, error
            self.s.flush()

    def set_file_class(self, document_id: int, doc_class: str) -> None:
        row = self._doc(document_id)
        if row is not None:
            row.doc_class, row.class_confirmed = doc_class, True
            self.s.flush()

    def delete_file(self, intake_id: int, document_id: int) -> bool:
        row = self._doc(document_id)
        if row is None or row.intake_id != intake_id:
            return False
        self.s.execute(delete(DocChunkRow).where(DocChunkRow.document_id == document_id))
        self.s.execute(delete(IndexJobRow).where(IndexJobRow.document_id == document_id))
        self.s.execute(update(EmbedRunRow).where(EmbedRunRow.document_id == document_id)
                       .values(document_id=None).execution_options(synchronize_session=False))
        self.s.execute(delete(DocVersionRow).where(DocVersionRow.document_id == document_id))
        self.s.execute(delete(DocumentRow).where(DocumentRow.id == document_id))
        self.s.flush()
        return True

    def move_to_deal(self, intake_id: int, deal_id: int) -> list[Document]:
        ids = list(self.s.scalars(select(DocumentRow.id).where(
            DocumentRow.intake_id == intake_id, DocumentRow.deal_id.is_(None))))
        for table, col in ((DocChunkRow, DocChunkRow.intake_id),
                           (IndexJobRow, IndexJobRow.intake_id),
                           (AgentRunRow, AgentRunRow.intake_id)):
            self.s.execute(update(table).where(col == intake_id, table.deal_id.is_(None))
                           .values(deal_id=deal_id)
                           .execution_options(synchronize_session=False))
        self.s.execute(update(EmbedRunRow).where(EmbedRunRow.document_id.in_(ids),
                                                 EmbedRunRow.deal_id.is_(None))
                       .values(deal_id=deal_id).execution_options(synchronize_session=False))
        self.s.execute(update(DocumentRow).where(DocumentRow.id.in_(ids))
                       .values(deal_id=deal_id).execution_options(synchronize_session=False))
        self.s.flush()
        rows = self.s.scalars(select(DocumentRow).where(DocumentRow.id.in_(ids))
                              .order_by(DocumentRow.id)
                              .execution_options(populate_existing=True)).all()
        return [mappers.document_to_domain(r) for r in rows]

    # ------------------------------------------------------------------ chunks

    def _staged(self, row, filename: str) -> StagedChunk:
        return StagedChunk(chunk_id=row.id, document_id=row.document_id, filename=filename,
                           page_from=row.page_from, page_to=row.page_to, kind=row.kind,
                           text=row.text, meta=dict(row.meta or {}))

    def chunks(self, intake_id: int) -> list[StagedChunk]:
        """Current-version chunks of the intake's documents, in reading order."""
        rows = self.s.execute(
            select(DocChunkRow, DocumentRow.filename)
            .join(DocumentRow, DocumentRow.id == DocChunkRow.document_id)
            .where(DocChunkRow.intake_id == intake_id,
                   DocChunkRow.version == DocumentRow.current_version)
            .order_by(DocChunkRow.document_id, DocChunkRow.chunk_index)).all()
        return [self._staged(r, name) for r, name in rows]

    def chunk(self, intake_id: int, chunk_id: int) -> StagedChunk | None:
        row = self.s.execute(
            select(DocChunkRow, DocumentRow.filename)
            .join(DocumentRow, DocumentRow.id == DocChunkRow.document_id)
            .where(DocChunkRow.id == chunk_id, DocChunkRow.intake_id == intake_id)).first()
        return self._staged(*row) if row else None

    def page_text(self, document_id: int, page_from: int | None, page_to: int | None,
                  limit_chars: int = 12_000) -> str:
        stmt = select(DocChunkRow.text).join(
            DocumentRow, DocumentRow.id == DocChunkRow.document_id).where(
            DocChunkRow.document_id == document_id,
            DocChunkRow.version == DocumentRow.current_version)
        if page_from is not None:
            last = page_to if page_to is not None else page_from
            stmt = stmt.where(or_(DocChunkRow.page_from.is_(None),
                                  DocChunkRow.page_from <= last),
                              or_(DocChunkRow.page_to.is_(None),
                                  DocChunkRow.page_to >= page_from))
        texts = self.s.scalars(stmt.order_by(DocChunkRow.chunk_index)).all()
        out, size = [], 0
        for t in texts:
            out.append(t)
            size += len(t)
            if size >= limit_chars:
                break
        return "\n\n".join(out)[:limit_chars]

    # ------------------------------------------------------------------ deal ids

    def next_external_id(self) -> str:
        n = self.s.execute(text("SELECT nextval('aura_deal_external_id_seq')")).scalar_one()
        return f"{EXTERNAL_PREFIX}{n:04d}"

    # ------------------------------------------------------------------ extraction queue

    def claim_next_extraction(self, worker_id: str, now: datetime) -> Intake | None:
        """The oldest queued extraction whose files are all indexed (or failed)."""
        pending = select(DocumentRow.id).where(DocumentRow.intake_id == DealIntakeRow.id,
                                               DocumentRow.deal_id.is_(None),
                                               DocumentRow.index_status == "pending")
        candidate = (select(DealIntakeRow.id)
                     .where(DealIntakeRow.extract_status == "queued",
                            DealIntakeRow.status.in_(("draft", "processing", "review")),
                            (DealIntakeRow.extract_not_before.is_(None))
                            | (DealIntakeRow.extract_not_before <= now),
                            ~pending.exists())
                     .order_by(DealIntakeRow.updated_at).limit(1)
                     .with_for_update(skip_locked=True).scalar_subquery())
        stmt = (update(DealIntakeRow)
                .where(DealIntakeRow.id == candidate, DealIntakeRow.extract_status == "queued")
                .values(extract_status="running", extract_claimed_by=worker_id,
                        extract_claimed_at=now,
                        extract_attempts=DealIntakeRow.extract_attempts + 1)
                .returning(DealIntakeRow.id).execution_options(synchronize_session=False))
        intake_id = self.s.execute(stmt).scalar_one_or_none()
        return self.get(intake_id) if intake_id is not None else None

    def hold_extraction(self, intake_id: int, worker_id: str) -> Intake | None:
        """Lock the intake; the intake while the extraction is still ours, else None."""
        row = self._row(intake_id, for_update=True)
        if row is None or row.extract_status != "running" or \
                row.extract_claimed_by != worker_id:
            return None
        return _intake(row)

    def stale_extractions(self, claimed_before: datetime) -> list[Intake]:
        rows = self.s.scalars(select(DealIntakeRow).where(
            DealIntakeRow.extract_status == "running",
            (DealIntakeRow.extract_claimed_at.is_(None))
            | (DealIntakeRow.extract_claimed_at < claimed_before))).all()
        return [_intake(r) for r in rows]

    # ------------------------------------------------------------------ metrics

    def override_stats(self) -> dict:
        """Across confirmed intakes the viewer can see: auto-filled fields and how many the
        creator changed before confirming (the 'intake' override rate)."""
        rows = self.s.scalars(select(DealIntakeRow.extract_meta).where(
            DealIntakeRow.status == "confirmed")).all()
        auto = sum(int((m or {}).get("override", {}).get("auto_filled", 0)) for m in rows)
        changed = sum(int((m or {}).get("override", {}).get("changed", 0)) for m in rows)
        return {"intakes_confirmed": len(rows), "auto_filled_fields": auto,
                "fields_changed": changed,
                "override_rate": round(changed / auto, 4) if auto else None}

    def count_open(self) -> int:
        return self.s.scalar(self._mine(select(func.count(DealIntakeRow.id)).where(
            DealIntakeRow.status.in_(("draft", "processing", "review"))))) or 0
