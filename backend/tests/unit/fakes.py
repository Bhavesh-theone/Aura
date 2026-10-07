from aura.core.domain.audit import AuditEntry
from aura.core.domain.enums import SegmentStatus
from aura.core.domain.job import Job
from aura.core.domain.segment import Segment


class FakeJobRepo:
    def __init__(self):
        self.items: dict[int, Job] = {}
        self._next = 1

    def add(self, job: Job) -> Job:
        job.id = self._next
        self._next += 1
        self.items[job.id] = job
        return job

    def get(self, job_id: int) -> Job | None:
        return self.items.get(job_id)

    def update(self, job: Job) -> Job:
        self.items[job.id] = job
        return job

    def list_recent(self, limit: int = 50) -> list[Job]:
        return list(self.items.values())[-limit:]


class FakeSegmentRepo:
    def __init__(self):
        self.items: dict[int, Segment] = {}
        self._next = 1

    def add(self, segment: Segment) -> Segment:
        segment.id = self._next
        self._next += 1
        self.items[segment.id] = segment
        return segment

    def get(self, segment_id: int) -> Segment | None:
        return self.items.get(segment_id)

    def update(self, segment: Segment) -> Segment:
        self.items[segment.id] = segment
        return segment

    def claim_next_queued(self, worker_id: str = "worker", now=None) -> Segment | None:
        for seg in self.items.values():
            if seg.status is SegmentStatus.QUEUED and (
                    seg.not_before is None or now is None or seg.not_before <= now):
                seg.status, seg.claimed_by, seg.claimed_at = (SegmentStatus.RUNNING,
                                                             worker_id, now)
                seg.attempts += 1
                return seg
        return None

    def list_for_job(self, job_id: int) -> list[Segment]:
        return [s for s in self.items.values() if s.job_id == job_id]

    def list_stale_running(self, claimed_before):
        return [s for s in self.items.values() if s.status is SegmentStatus.RUNNING
                and (s.claimed_at is None or s.claimed_at < claimed_before)]

    def list_by_status(self, status):
        return [s for s in self.items.values() if s.status is status]



class FakeAuditRepo:
    def __init__(self):
        self.entries: list[AuditEntry] = []

    def append(self, entry: AuditEntry) -> AuditEntry:
        entry.id = len(self.entries) + 1
        self.entries.append(entry)
        return entry

    def list_recent(self, limit: int = 100) -> list[AuditEntry]:
        return self.entries[-limit:]

    def count_by_action(self, action: str) -> int:
        return sum(1 for e in self.entries if e.action == action)


class FakeEvents:
    def __init__(self):
        self.published: list[tuple[str, dict]] = []

    def publish(self, event_type: str, payload: dict) -> None:
        self.published.append((event_type, payload))


class FakeDealRepo:
    def __init__(self):
        self.items: dict = {}

    def add(self, deal):
        deal.id = len(self.items) + 1
        self.items[deal.id] = deal
        return deal

    def get(self, deal_id):
        return self.items.get(deal_id)

    def get_by_external_id(self, external_id):
        return next((d for d in self.items.values() if d.external_id == external_id), None)

    def update(self, deal):
        self.items[deal.id] = deal
        return deal

    def list_all(self):
        return list(self.items.values())


class FakeHistoryRepo:
    def __init__(self):
        self.entries = []

    def append(self, entry):
        entry.id = len(self.entries) + 1
        self.entries.append(entry)
        return entry

    def list_for_deal(self, deal_id):
        return [e for e in self.entries if e.deal_id == deal_id]

    def list_all(self):
        return list(self.entries)


class FakeGuardRepo:
    """guards: StageGuard list; outcomes: guard_name -> bool (default True)."""

    def __init__(self, guards=(), outcomes=None):
        self.guards = list(guards)
        self.outcomes = outcomes or {}
        self.recorded = []
        self.attached = []

    def list_active(self, from_stage, to_stage, transaction_class):
        return [g for g in self.guards if g.from_stage is from_stage and g.to_stage is to_stage]

    def evaluate(self, guard, deal_id):
        return self.outcomes.get(guard.guard_name, True), {}

    def record(self, evaluation):
        evaluation.id = len(self.recorded) + 1
        self.recorded.append(evaluation)
        return evaluation

    def attach_history(self, evaluation_ids, history_id):
        self.attached.append((list(evaluation_ids), history_id))

    def linked_history_ids(self, history_ids):
        return {h for ids, h in self.attached if h in history_ids}


class FakeDiligenceRepo:
    def __init__(self, templates=()):
        self.templates = list(templates)
        self.items = []

    def list_templates(self, transaction_class):
        return [t for t in self.templates if t.transaction_class in (None, transaction_class)]

    def add_item(self, item):
        item.id = len(self.items) + 1
        self.items.append(item)
        return item

    def get_item(self, item_id):
        return next((i for i in self.items if i.id == item_id), None)

    def update_item(self, item):
        return item

    def list_items(self, deal_id):
        return [i for i in self.items if i.deal_id == deal_id]


class FakeTaskRepo:
    def __init__(self):
        self.items = {}

    def add(self, task):
        task.id = len(self.items) + 1
        self.items[task.id] = task
        return task

    def get(self, task_id):
        return self.items.get(task_id)

    def update(self, task):
        self.items[task.id] = task
        return task


class FakeHandoffRepo:
    def __init__(self):
        self.items = {}

    def add(self, handoff):
        handoff.id = len(self.items) + 1
        self.items[handoff.id] = handoff
        return handoff

    def get(self, handoff_id):
        return self.items.get(handoff_id)

    def update(self, handoff):
        self.items[handoff.id] = handoff
        return handoff

    def list_all(self, resolved=None):
        from aura.core.domain.enums import HandoffStatus
        return [h for h in self.items.values()
                if resolved is None or (h.status is HandoffStatus.RESOLVED) == resolved]

    def count_waiting(self):
        return len(self.list_all(resolved=False))

    def list_overdue(self, now):
        from aura.core.domain.enums import HandoffStatus
        return [h for h in self.items.values() if h.status is HandoffStatus.OPEN
                and h.auto_escalate_at is not None and h.auto_escalate_at <= now]

    def mark_resolved(self, handoff):
        from aura.core.domain.enums import HandoffStatus
        current = self.items.get(handoff.id)
        if current is None or current.status not in (HandoffStatus.OPEN,
                                                     HandoffStatus.ESCALATED):
            return False
        # in place, like a row: callers holding the earlier object see the resolution
        current.__dict__.update(handoff.__dict__)
        return True


    def open_ones(self):
        return self.list_all(resolved=False)


class FakeDocumentRepo:
    def __init__(self, docs=()):
        self.docs = {d.id: d for d in docs}

    def get(self, document_id):
        return self.docs.get(document_id)

    def update_classification(self, document_id, doc_class, confirmed):
        doc = self.docs[document_id]
        doc.doc_class, doc.class_confirmed = doc_class, confirmed
        return doc


class FakeUow:
    def __init__(self):
        self.commits = 0
        self.rollbacks = 0

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class FakeRunSink:
    def __init__(self, fail=False):
        self.runs = []
        self.fail = fail

    def record(self, run):
        from aura.core.ports.orchestrator import AgentRunLogError
        if self.fail:
            raise AgentRunLogError("disk full")
        run.id = len(self.runs) + 1
        self.runs.append(run)
        return run


class FakeWallRepo:
    def __init__(self):
        self.created = []
        self.added = []

    def create(self, deal_id, name, member):
        self.created.append((deal_id, name, member))

    def add_member(self, deal_id, username):
        self.added.append((deal_id, username))
        return True
