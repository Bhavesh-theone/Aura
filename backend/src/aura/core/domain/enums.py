from enum import Enum


class ActionCategory(str, Enum):
    MONEY = "money"
    LEGAL = "legal"
    OUTBOUND = "outbound"
    INTERNAL_READ = "internal_read"
    INTERNAL_WRITE = "internal_write"
    UNKNOWN = "unknown"


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    COMPLETE = "complete"
    FAILED = "failed"
    REJECTED = "rejected"


class SegmentStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    DONE = "done"
    FAILED = "failed"


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class Role(str, Enum):
    ADMIN = "admin"
    MEMBER = "member"
