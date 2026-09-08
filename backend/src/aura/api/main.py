import asyncio
import logging

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from aura.agents.factory import make_orchestrator
from aura.api.routers import activity, approvals, auth, jobs
from aura.api.security import decode_token
from aura.api.ws.hub import hub
from aura.data.seed import seed
from aura.worker.runner import start_worker

app = FastAPI(title="Yuki OS Portal API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(jobs.router)
app.include_router(approvals.router)
app.include_router(activity.router)


@app.on_event("startup")
def on_startup() -> None:
    logging.basicConfig(level=logging.INFO)
    seed()
    hub.bind_loop(asyncio.get_running_loop())
    app.state.worker_stop = start_worker(make_orchestrator(), hub)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.websocket("/ws/events")
async def events_socket(websocket: WebSocket, token: str = "") -> None:
    if decode_token(token) is None:
        await websocket.close(code=1008)
        return
    await hub.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        hub.disconnect(websocket)
