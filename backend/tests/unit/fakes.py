from aura.core.domain.approval import Approval
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

    def claim_next_queued(self) -> Segment | None:
        for seg in self.items.values():
            if seg.status is SegmentStatus.QUEUED:
                return seg
        return None

    def list_for_job(self, job_id: int) -> list[Segment]:
        return [s for s in self.items.values() if s.job_id == job_id]


class FakeApprovalRepo:
    def __init__(self):
        self.items: dict[int, Approval] = {}
        self._next = 1

    def add(self, approval: Approval) -> Approval:
        approval.id = self._next
        self._next += 1
        self.items[approval.id] = approval
        return approval

    def get(self, approval_id: int) -> Approval | None:
        return self.items.get(approval_id)

    def update(self, approval: Approval) -> Approval:
        self.items[approval.id] = approval
        return approval

    def list_pending(self) -> list[Approval]:
        from aura.core.domain.enums import ApprovalStatus
        return [a for a in self.items.values() if a.status is ApprovalStatus.PENDING]


class FakeAuditRepo:
    def __init__(self):
        self.entries: list[AuditEntry] = []

    def append(self, entry: AuditEntry) -> AuditEntry:
        entry.id = len(self.entries) + 1
        self.entries.append(entry)
        return entry

    def list_recent(self, limit: int = 100) -> list[AuditEntry]:
        return self.entries[-limit:]


class FakeEvents:
    def __init__(self):
        self.published: list[tuple[str, dict]] = []

    def publish(self, event_type: str, payload: dict) -> None:
        self.published.append((event_type, payload))
