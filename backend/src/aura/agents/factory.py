import logging

from aura.agents.llm.ollama_check import ollama_available
from aura.config import get_settings
from aura.core.ports.orchestrator import Orchestrator

logger = logging.getLogger(__name__)


def make_orchestrator(base_url: str | None = None) -> Orchestrator:
    """Real crew when Ollama is up; deterministic stub otherwise.

    The portal stays usable with no model running - the approval loop is
    exercised either way.
    """
    url = base_url or get_settings().ollama_base_url

    if ollama_available(url):
        try:
            from aura.agents.crewai.orchestrator import CrewOrchestrator
            logger.info("Orchestrator: CrewAI on %s", url)
            return CrewOrchestrator()
        except Exception as exc:
            logger.warning("CrewAI unavailable (%s) - falling back to stub", exc)

    from aura.worker.stub_orchestrator import StubOrchestrator
    logger.warning("Orchestrator: StubOrchestrator (Ollama unreachable at %s)", url)
    return StubOrchestrator()
