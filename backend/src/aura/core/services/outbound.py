"""The one place an outbound action's execution is recorded.

v1 sends nothing: gated tools are never executed (see aura.agents.crewai.tools) and the
number of 'outbound_executed' audit rows must stay 0. If a sender is ever added, it must
call this after it acts, so the success metric (SM5) notices."""



from aura.core.clock import utcnow
from aura.core.domain.audit import AuditEntry
from aura.core.ports.repositories import AuditRepository


def record_outbound_executed(tool: str, arguments: dict, actor: str, deal_id: int | None,
                             job_id: int | None, audit: AuditRepository) -> AuditEntry:
    return audit.append(AuditEntry(
        id=None, job_id=job_id, deal_id=deal_id, actor=actor, action="outbound_executed",
        created_at=utcnow(),
        payload={"tool": tool, "argument_names": sorted(arguments)}))
