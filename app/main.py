from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.state import HotelState

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"

state = HotelState()
clients: set[WebSocket] = set()


async def broadcast() -> None:
    snap = state.snapshot().model_dump()
    dead = []
    for ws in list(clients):
        try:
            await ws.send_json(snap)
        except Exception:
            dead.append(ws)
    for ws in dead:
        clients.discard(ws)


async def simulator_loop() -> None:
    while True:
        await asyncio.sleep(1.0)
        # 1 hotel minute per real second — demo time, not a user-facing control.
        state.tick(1.0 / 60.0)
        await broadcast()


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(simulator_loop())
    yield
    task.cancel()


app = FastAPI(title="Turnwise", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/")
async def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/state")
async def get_state():
    return state.snapshot().model_dump()


@app.post("/api/checkout/{room_id}")
async def force_checkout(room_id: str):
    result = state.force_checkout(room_id)
    if result.get("ok"):
        await broadcast()
    return result


@app.post("/api/vip/{room_id}")
async def toggle_vip(room_id: str):
    result = state.toggle_vip(room_id)
    if result.get("ok"):
        await broadcast()
    return result


@app.post("/api/maintenance/{room_id}")
async def flag_maintenance(room_id: str):
    result = state.flag_maintenance(room_id)
    if result.get("ok"):
        await broadcast()
    return result


@app.post("/api/sim/tick")
async def sim_tick():
    for _ in range(5):
        state.tick(5.0 / 60.0)
    await broadcast()
    return {"ok": True}


@app.post("/api/sim/reset")
async def sim_reset():
    result = state.reset()
    await broadcast()
    return result


@app.websocket("/ws")
async def ws_feed(ws: WebSocket):
    await ws.accept()
    clients.add(ws)
    try:
        await ws.send_json(state.snapshot().model_dump())
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        clients.discard(ws)
    except Exception:
        clients.discard(ws)