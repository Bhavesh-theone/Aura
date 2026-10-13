"""Index existing documents (uploaded before phase 2, or whose indexing failed).

    uv run python -m aura.ingest.backfill [--deal ID] [--limit N] [--all | --reindex]
                                          [--queue-only]

Queues every document that is not indexed yet (--all or --reindex: every document, e.g. after
changing the PDF parser), then works the queue
in this process and prints one line per document. The API's own index worker may take some
of the jobs at the same time; claims are FOR UPDATE SKIP LOCKED, so nothing is done twice.
--queue-only leaves the work to the running API. Exit code 1 when any document failed.
"""
import argparse
import sys
import time

from sqlalchemy import select

from aura.config import get_settings
from aura.core.services.indexing import enqueue
from aura.core.tracing import tracer
from aura.data.engine import SessionLocal
from aura.data.models.tables import DocumentRow
from aura.data.repositories.sql_deals import SqlDocumentRepository
from aura.data.repositories.sql_ingest import SqlIndexQueue
from aura.data.walls import SYSTEM, bind_viewer


class _Quiet:
    def publish(self, event_type: str, payload: dict) -> None:
        pass


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m aura.ingest.backfill",
                                 description="Index existing documents.")
    ap.add_argument("--deal", type=int, default=None, help="only this deal id")
    ap.add_argument("--limit", type=int, default=None, help="at most N documents")
    ap.add_argument("--all", "--reindex", dest="all", action="store_true",
                    help="re-index indexed documents too (e.g. after a parser change)")
    ap.add_argument("--queue-only", action="store_true",
                    help="queue them and let the API's worker do the work")
    args = ap.parse_args(argv)
    tracer.configure(get_settings().tracing_enabled)

    from aura.worker.indexer import embedder_factory, index_once, parser_factory
    with SessionLocal() as session:
        bind_viewer(session, SYSTEM)
        stmt = select(DocumentRow.id).order_by(DocumentRow.id)
        if args.deal is not None:
            stmt = stmt.where(DocumentRow.deal_id == args.deal)
        if not args.all:
            stmt = stmt.where(DocumentRow.index_status != "indexed")
        if args.limit:
            stmt = stmt.limit(args.limit)
        ids = list(session.scalars(stmt))
        documents = SqlDocumentRepository(session, SYSTEM)
        queue = SqlIndexQueue(session, SYSTEM)
        for doc_id in ids:
            enqueue(documents.get(doc_id), "backfill", queue, documents)
        session.commit()
        print(f"queued {len(ids)} document(s)")
        if args.queue_only or not ids:
            return 0

        parser, embedder = parser_factory(), embedder_factory()
        from aura.ingest.parsers import limits_from_settings
        limits = limits_from_settings()
        print(f"embedder: {embedder.model}; PDF parser: {limits.pdf_parser}; "
              f"scan VLM: {limits.scan_vlm}")
        started = time.perf_counter()
        counts: dict[str, int] = {}
        while True:
            t0 = time.perf_counter()
            outcome = index_once(session, _Quiet(), worker_id="backfill", parser=parser,
                                 embedder=embedder)
            if outcome is None:
                break
            counts[outcome] = counts.get(outcome, 0) + 1
            print(f"  {outcome:<11} {time.perf_counter() - t0:6.2f}s")
            if sum(counts.values()) > len(ids) * 4:  # retries of retries: stop, report
                break
        rows = session.execute(select(DocumentRow.id, DocumentRow.filename,
                                      DocumentRow.index_status, DocumentRow.chunk_count,
                                      DocumentRow.ocr_used, DocumentRow.index_error)
                               .where(DocumentRow.id.in_(ids)).order_by(DocumentRow.id)).all()
        for r in rows:
            extra = " OCR" if r.ocr_used else ""
            error = f"  ({r.index_error[:120]})" if r.index_error else ""
            print(f"  #{r.id:<5} {r.index_status:<8} {r.chunk_count:>4} chunks{extra}  "
                  f"{r.filename}{error}")
        summary = {s: sum(1 for r in rows if r.index_status == s)
                   for s in ("indexed", "pending", "failed")}
        print(f"done in {time.perf_counter() - started:.1f}s: {summary}")
        return 1 if summary["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
