import logging
import threading
import time
from dataclasses import dataclass
from typing import Callable

from aura.agents.llm.ollama_check import ollama_available
from aura.config import get_settings
from aura.core.ports.orchestrator import Orchestrator

logger = logging.getLogger(__name__)


def _crew() -> Orchestrator:
    from aura.agents.crewai.orchestrator import CrewOrchestrator
    return CrewOrchestrator()


def _stub() -> Orchestrator:
    from aura.worker.stub_orchestrator import StubOrchestrator
    return StubOrchestrator()


def make_orchestrator(base_url: str | None = None) -> Orchestrator:
    """Real crew when Ollama is up; deterministic stub otherwise.

    The portal stays usable with no model running - the approval loop is
    exercised either way.
    """
    url = base_url or get_settings().ollama_base_url

    if ollama_available(url):
        try:
            orchestrator = _crew()
            logger.info("Orchestrator: CrewAI on %s", url)
            return orchestrator
        except Exception as exc:
            logger.warning("CrewAI unavailable (%s) - falling back to stub", exc)

    logger.warning("Orchestrator: StubOrchestrator (Ollama unreachable at %s)", url)
    return _stub()


@dataclass
class Selection:
    orchestrator: Orchestrator
    # Why the stub stands in for the crew on this segment; None when nothing fell back.
    fallback_reason: str | None = None


class OrchestratorSelector:
    """Chooses the orchestrator per segment rather than once at startup.

    Ollama's health is checked at most every `ttl_seconds` (default 30 s). While it answers,
    segments go to the crew; while it does not, each segment runs on the stub instead of
    failing, and the selection says so (the worker audits 'orchestrator_fallback'; the stub
    records its runs as model 'stub'). The worker calls invalidate() after a transient
    failure so the next segment checks again at once."""

    def __init__(self, base_url: str | None = None, ttl_seconds: float | None = None,
                 available: Callable[[str], bool] = ollama_available,
                 crew_factory: Callable[[], Orchestrator] = _crew,
                 stub_factory: Callable[[], Orchestrator] = _stub,
                 clock: Callable[[], float] = time.monotonic):
        settings = get_settings()
        self.url = base_url or settings.ollama_base_url
        self.ttl = settings.orchestrator_health_ttl_seconds if ttl_seconds is None \
            else ttl_seconds
        self._available, self._clock = available, clock
        self._crew_factory, self._stub_factory = crew_factory, stub_factory
        self._crew: Orchestrator | None = None
        self._stub: Orchestrator | None = None
        self._checked_at: float | None = None
        self._up = False
        self._lock = threading.Lock()

    def invalidate(self) -> None:
        with self._lock:
            self._checked_at = None

    def _healthy(self) -> bool:
        now = self._clock()
        if self._checked_at is None or now - self._checked_at >= self.ttl:
            self._up = self._available(self.url)
            self._checked_at = now
        return self._up

    def select(self) -> Selection:
        with self._lock:
            if self._healthy():
                try:
                    if self._crew is None:
                        self._crew = self._crew_factory()
                    return Selection(self._crew)
                except Exception as exc:
                    reason = f"CrewAI could not start: {exc}"
            else:
                reason = f"Ollama unreachable at {self.url}"
            if self._stub is None:
                self._stub = self._stub_factory()
            return Selection(self._stub, reason)
