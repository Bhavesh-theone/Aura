from dataclasses import dataclass, field
from datetime import datetime

from aura.core.domain.enums import IdentifierScheme, PartyRole, PartyType


@dataclass
class PartyIdentifier:
    scheme: IdentifierScheme
    value: str


@dataclass
class Party:
    id: int | None
    party_type: PartyType
    display_name: str
    created_at: datetime
    identifiers: list[PartyIdentifier] = field(default_factory=list)


@dataclass
class DealParty:
    deal_id: int
    party_id: int
    role: PartyRole
    display_name: str = ""
