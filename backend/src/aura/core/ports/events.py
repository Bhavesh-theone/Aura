from typing import Protocol, runtime_checkable


@runtime_checkable
class EventPublisher(Protocol):
    def publish(self, event_type: str, payload: dict) -> None: ...
