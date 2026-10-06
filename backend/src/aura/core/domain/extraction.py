from dataclasses import dataclass
from datetime import datetime

# An extraction at or above this confidence may feed a valuation without a person looking.
CONFIDENCE_GATE = 0.95


@dataclass
class ExtractionProposal:
    """What an orchestrator read out of a document. Nothing is stored until run_segment
    does it."""
    schema_name: str
    payload: dict
    confidence: float
    model_run_id: int | None = None


@dataclass
class Extraction:
    id: int | None
    document_id: int
    version: int
    schema_name: str
    payload: dict
    confidence: float
    feeds_valuation: bool
    human_verified_by: str | None
    human_verified_at: datetime | None
    model_run_id: int | None
    created_at: datetime
