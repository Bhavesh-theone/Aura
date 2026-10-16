from dataclasses import dataclass
from datetime import datetime


@dataclass
class WallMember:
    username: str
    added_at: datetime
