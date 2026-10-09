import asyncio
import logging

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from aura.agents.factory import OrchestratorSelector
from aura.api.errors import register_error_handlers
from aura.api.routers import (activity, agent_runs, audit, auth, dashboard, deal_profiles,
                              deals, diligence, documents, extractions, handoffs, harness,
                              jobs, metrics, outbound, parties, users)
from aura.api.security import decode_token
from aura.api.ws.hub import hub
from aura.data.engine import SessionLocal
from aura.data.seed import seed
from aura.data.verify_audit import default_anchor_path, refresh_anchor
from aura.worker.runner import start_worker

app = FastAPI(title="Yuki OS Portal API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    # The portal reads these: the 429 countdown and the idempotent-replay notice.
    expose_headers=["Retry-After", "Idempotent-Replayed"],
)

app.include_router(auth.router)
app.include_router(jobs.router)
app.include_router(handoffs.router)
app.include_router(agent_runs.router)
app.include_router(dashboard.router)
app.include_router(activity.router)
for _r in (deals, deal_profiles, parties, documents, diligence, audit, users, metrics, extractions,
           harness, outbound):
    app.include_router(_r.router)
register_error_handlers(app)


def _check_audit_anchor() -> None:
    """Compare the audit chain with the anchor file; move the anchor up if all is well."""
    with SessionLocal() as session:
        result = refresh_anchor(session, default_anchor_path())
    log = logging.getLogger(__name__)
    if result.ok:
        log.info("Audit chain and anchor: OK")
    else:
        log.error("AUDIT VERIFICATION FAILED: %s", result.message)


@app.on_event("startup")
def on_startup() -> None:
    logging.basicConfig(level=logging.INFO)
    from aura.config import get_settings
    from aura.core.tracing import tracer
    tracer.configure(get_settings().tracing_enabled)
    seed()
    _check_audit_anchor()
    hub.bind_loop(asyncio.get_running_loop())
    # The orchestrator is chosen per segment: the crew while Ollama answers, the stub (and
    # an 'orchestrator_fallback' audit row) while it does not.
    selector = OrchestratorSelector()
    first = selector.select()
    logging.getLogger(__name__).info(
        "Orchestrator now: %s%s", type(first.orchestrator).__name__,
        f" ({first.fallback_reason})" if first.fallback_reason else "")
    app.state.worker_stop = start_worker(selector, hub)



@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.websocket("/ws/events")
async def events_socket(websocket: WebSocket, token: str = "") -> None:
    claims = decode_token(token)
    if claims is None:
        await websocket.close(code=1008)
        return
    await hub.connect(websocket, str(claims.get("username", "")))
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        hub.disconnect(websocket)
