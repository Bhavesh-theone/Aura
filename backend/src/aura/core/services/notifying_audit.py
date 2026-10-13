"""An audit repository that also announces what changed. Every mutation is audited, so
wrapping the audit repository is how every mutation gets its `entity_changed` event."""
from aura.core.domain.audit import AuditEntry
from aura.core.policy.entity_policy import entity_kind_for
from aura.core.ports.events import EventPublisher
from aura.core.ports.repositories import AuditRepository


class NotifyingAudit:
    def __init__(self, inner: AuditRepository, events: EventPublisher):
        self._inner, self._events = inner, events

    def append(self, entry: AuditEntry) -> AuditEntry:
        saved = self._inner.append(entry)
        kind = entity_kind_for(entry.action)
        if kind == "intake":
            # A draft intake belongs to its creator alone: the event names its recipient
            # (the hub sends it to nobody else) and never a deal.
            payload = entry.payload or {}
            self._events.publish("entity_changed", {
                "kind": kind, "deal_id": None, "intake_id": payload.get("intake_id"),
                "recipient": payload.get("recipient") or entry.actor})
        elif kind is not None:
            self._events.publish("entity_changed", {"kind": kind, "deal_id": entry.deal_id})
        return saved

    def list_recent(self, limit: int = 100) -> list[AuditEntry]:
        return self._inner.list_recent(limit)

    def count_by_action(self, action: str) -> int:
        return self._inner.count_by_action(action)
