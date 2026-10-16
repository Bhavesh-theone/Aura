from enum import Enum


class ActionCategory(str, Enum):
    MONEY = "money"
    LEGAL = "legal"
    OUTBOUND = "outbound"
    INTERNAL_READ = "internal_read"
    INTERNAL_WRITE = "internal_write"
    DOCUMENT_CLASSIFICATION = "document_classification"
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
    # Transient failures retried up to segment_max_attempts: parked for a person to retry.
    DEAD_LETTER = "dead_letter"


class Role(str, Enum):
    ADMIN = "admin"
    DEALMAKER = "dealmaker"
    ANALYST = "analyst"
    COMPLIANCE = "compliance"


class FindingType(str, Enum):
    RED_FLAG = "red_flag"
    QUALIFICATION = "qualification"
    ADJUSTMENT = "adjustment"
    OBSERVATION = "observation"


class ChecklistLayer(str, Enum):
    BASE = "base"
    SUBCLASS = "subclass"
    VERTICAL = "vertical"
    JURISDICTION = "jurisdiction"


class DealStage(str, Enum):
    ORIGINATED = "ORIGINATED"
    QUALIFIED = "QUALIFIED"
    MANDATED = "MANDATED"
    PREPARED = "PREPARED"
    MARKETED = "MARKETED"
    MATCHED = "MATCHED"
    BID_AUCTION = "BID_AUCTION"
    NEGOTIATION = "NEGOTIATION"
    DILIGENCE = "DILIGENCE"
    DOCUMENTATION = "DOCUMENTATION"
    CONDITIONS_PRECEDENT = "CONDITIONS_PRECEDENT"
    CLOSED = "CLOSED"
    LAPSED = "LAPSED"
    WITHDRAWN = "WITHDRAWN"
    REJECTED = "REJECTED"
    ABORTED = "ABORTED"


class TransactionClass(str, Enum):
    DEBT = "DEBT"
    EQUITY = "EQUITY"
    MNA = "MNA"
    HYBRID = "HYBRID"
    JV = "JV"
    LPGP = "LPGP"
    ALLIANCE = "ALLIANCE"


class Outcome(str, Enum):
    CLOSED_WON = "closed_won"
    CLOSED_LOST = "closed_lost"
    WITHDRAWN = "withdrawn"
    LAPSED = "lapsed"
    REJECTED = "rejected"
    ABORTED = "aborted"


class GuardSeverity(str, Enum):
    BLOCKING = "blocking"
    WARNING = "warning"


class PartyType(str, Enum):
    COMPANY = "company"
    LLP = "llp"
    FUND = "fund"
    TRUST = "trust"
    INDIVIDUAL = "individual"
    GOVERNMENT_BODY = "government_body"
    FOREIGN_ENTITY = "foreign_entity"
    PARTNERSHIP = "partnership"
    SOLE_PROP = "sole_prop"
    HUF = "huf"


class IdentifierScheme(str, Enum):
    CIN = "CIN"
    LLPIN = "LLPIN"
    PAN = "PAN"
    GSTIN = "GSTIN"
    DIN = "DIN"


class PartyRole(str, Enum):
    BUYER = "buyer"
    SELLER = "seller"
    TARGET = "target"
    ISSUER = "issuer"
    INVESTOR = "investor"
    LENDER = "lender"
    ADVISOR = "advisor"
    COUNSEL = "counsel"


class CriterionHardness(str, Enum):
    HARD = "hard"
    SOFT = "soft"
    PREFERENCE = "preference"


class CriterionOperator(str, Enum):
    EQ = "eq"
    IN = "in"
    GTE = "gte"
    LTE = "lte"
    BETWEEN = "between"
    NOT_IN = "not_in"
    CONTAINS = "contains"


class MandateSide(str, Enum):
    SELL = "sell"
    BUY = "buy"
    RAISE = "raise"
    DEPLOY = "deploy"
    PARTNER = "partner"


class MandateStatus(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    PAUSED = "paused"
    FULFILLED = "fulfilled"
    EXPIRED = "expired"
    WITHDRAWN = "withdrawn"


class DocClass(str, Enum):
    FINANCIAL_STATEMENT = "financial_statement"
    CAP_TABLE = "cap_table"
    BOARD_RESOLUTION = "board_resolution"
    MOA_AOA = "moa_aoa"
    TERM_SHEET = "term_sheet"
    SPA = "spa"
    SHPA = "shpa"
    VALUATION_REPORT = "valuation_report"
    TAX_RETURN = "tax_return"
    LITIGATION_SUMMARY = "litigation_summary"
    ENV_CLEARANCE = "env_clearance"
    ENGAGEMENT_LETTER = "engagement_letter"
    NDA = "nda"
    BANK_STATEMENT = "bank_statement"
    GST_RETURN = "gst_return"
    CHARGE_DOCUMENT = "charge_document"
    LAND_TITLE = "land_title"


class DiligenceSeverity(str, Enum):
    BLOCKER = "blocker"
    MATERIAL = "material"
    STANDARD = "standard"
    INFORMATIONAL = "informational"


class DiligenceStatus(str, Enum):
    OPEN = "open"
    REQUESTED = "requested"
    RECEIVED = "received"
    UNDER_REVIEW = "under_review"
    SATISFIED = "satisfied"
    WAIVED = "waived"
    FAILED = "failed"


class CPStatus(str, Enum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    SATISFIED = "satisfied"
    WAIVED = "waived"
    FAILED = "failed"


class AssignmentMode(str, Enum):
    BOT_AUTO = "bot_auto"
    BOT_SUPERVISED = "bot_supervised"
    HUMAN_REQUIRED = "human_required"


class TaskStatus(str, Enum):
    QUEUED = "queued"
    ASSIGNED = "assigned"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    REVIEW = "review"
    DONE = "done"
    CANCELLED = "cancelled"


class HandoffDirection(str, Enum):
    BOT_TO_HUMAN = "bot_to_human"
    HUMAN_TO_BOT = "human_to_bot"


class HandoffTrigger(str, Enum):
    CONFIDENCE_BELOW_THRESHOLD = "confidence_below_threshold"
    MATERIALITY_GATE = "materiality_gate"
    POLICY_REQUIRED = "policy_required"
    EXPLICIT_REQUEST = "explicit_request"
    HUMAN_CORRECTION = "human_correction"
    # The context held text that looks like a prompt injection (injection_policy).
    UNTRUSTED_CONTENT = "untrusted_content"


class HandoffStatus(str, Enum):
    OPEN = "open"
    RESOLVED = "resolved"
    ESCALATED = "escalated"


class IntakeStatus(str, Enum):
    """A deal intake (phase 3): drafted, extracted, reviewed, then confirmed or discarded."""
    DRAFT = "draft"
    PROCESSING = "processing"
    REVIEW = "review"
    CONFIRMED = "confirmed"
    DISCARDED = "discarded"
