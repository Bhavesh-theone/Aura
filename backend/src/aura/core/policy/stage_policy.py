"""SOSPE stage machine as pure functions. Guards are evaluated elsewhere."""
from aura.core.domain.enums import DealStage, Outcome
from aura.core.domain.errors import InvalidTransition, RuleViolation

_S = DealStage
FORWARD_ORDER = [_S.ORIGINATED, _S.QUALIFIED, _S.MANDATED, _S.PREPARED, _S.MARKETED,
                 _S.MATCHED, _S.BID_AUCTION, _S.NEGOTIATION, _S.DILIGENCE,
                 _S.DOCUMENTATION, _S.CONDITIONS_PRECEDENT, _S.CLOSED]
EXIT_STAGES = frozenset({_S.LAPSED, _S.WITHDRAWN, _S.REJECTED, _S.ABORTED})
TERMINAL_STAGES = EXIT_STAGES | {_S.CLOSED}

REGRESSIONS = frozenset({
    (_S.DILIGENCE, _S.NEGOTIATION),
    (_S.DOCUMENTATION, _S.NEGOTIATION),
    (_S.CONDITIONS_PRECEDENT, _S.DOCUMENTATION),
    (_S.MATCHED, _S.MARKETED),
    (_S.BID_AUCTION, _S.MARKETED),
})

OUTCOME_FOR_STAGE = {
    _S.CLOSED: Outcome.CLOSED_WON,
    _S.LAPSED: Outcome.LAPSED,
    _S.WITHDRAWN: Outcome.WITHDRAWN,
    _S.REJECTED: Outcome.REJECTED,
    _S.ABORTED: Outcome.ABORTED,
}


def allowed_next(stage: DealStage) -> list[DealStage]:
    if stage in TERMINAL_STAGES:
        return []
    i = FORWARD_ORDER.index(stage)
    regress = [b for a, b in sorted(REGRESSIONS, key=lambda p: p[1].value) if a is stage]
    return [FORWARD_ORDER[i + 1], *regress, *sorted(EXIT_STAGES, key=lambda s: s.value)]


def check_transition(from_stage: DealStage, to_stage: DealStage,
                     reason_code: str | None) -> bool:
    """Validate a move. Returns is_regression; raises if the move is not permitted."""
    if to_stage not in allowed_next(from_stage):
        raise InvalidTransition(f"{from_stage.value} -> {to_stage.value} is not permitted")
    is_regression = (from_stage, to_stage) in REGRESSIONS
    if (is_regression or to_stage in EXIT_STAGES) and not (reason_code or "").strip():
        raise RuleViolation("reason_code is required for regressions and exits")
    return is_regression
