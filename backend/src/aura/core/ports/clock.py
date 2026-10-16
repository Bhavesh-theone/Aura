from datetime import datetime
from typing import Protocol, runtime_checkable


@runtime_checkable
class Clock(Protocol):
    """Where services get "now" from. Always timezone-aware UTC."""
    def now(self) -> datetime: ...
