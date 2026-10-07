"""Show, and with --apply enforce, the autonomy demotion rules.

    uv run python -m aura.evals.autonomy            # what would change (nothing is written)
    uv run python -m aura.evals.autonomy --apply    # demote, audited 'autonomy_demoted'

The worker runs the same check every AURA_AUTONOMY_CHECK_INTERVAL_SECONDS. Promotion is never
automatic: an admin calls POST /api/autonomy/{capability}/promote.
"""
import argparse
import sys

from aura.core.domain.harness import EVAL_CAPABILITIES
from aura.core.services.autonomy import apply_demotions
from aura.data.engine import SessionLocal
from aura.data.repositories.sql import SqlAuditRepository, SqlHandoffRepository
from aura.data.repositories.sql_harness import SqlAutonomyRepository, SqlEvalRepository
from aura.data.walls import SYSTEM
from aura.worker.runner import demotion_rules


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m aura.evals.autonomy")
    parser.add_argument("--apply", action="store_true", help="write the demotions")
    args = parser.parse_args(argv)
    with SessionLocal() as session:
        autonomy = SqlAutonomyRepository(session)
        changes = apply_demotions(autonomy, SqlEvalRepository(session),
                                  SqlHandoffRepository(session, SYSTEM),
                                  SqlAuditRepository(session, SYSTEM), demotion_rules())
        for change in changes:
            print(f"{'DEMOTED' if args.apply else 'would demote'} {change['capability']}: "
                  f"level {change['from_level']} -> {change['to_level']} ({change['reason']})")
        if args.apply:
            session.commit()
        else:
            session.rollback()
        for capability in EVAL_CAPABILITIES:
            state = autonomy.get(capability)
            print(f"{capability:<20} level {state.level}  {state.reason or ''}")
    if not changes:
        print("No demotions.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
