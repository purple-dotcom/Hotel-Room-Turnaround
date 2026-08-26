from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.models import RoomStatus
from app.state import HotelState

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"

state = HotelState()
clients: set[WebSocket] = set()


async def simulator_loop() -> None:
    while True:
        await asyncio.sleep(1.0)
        with state.lock:
            minutes = state.sim_minutes_per_second
        if minutes > 0:
            state.tick(minutes / 60.0)
        snap = state.snapshot().model_dump()
        dead = []
        for ws in list(clients):
            try:
                await ws.send_json(snap)
            except Exception:
                dead.append(ws)
        for ws in dead:
            clients.discard(ws)


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
    with state.lock:
        room = state.rooms.get(room_id)
        if not room:
            return {"ok": False, "error": "unknown room"}
        room.status = RoomStatus.DIRTY
        room.guest_name = None
        room.assigned_staff_id = None
        room.task_started_hour = None
        state.checkouts_today += 1
    return {"ok": True}


class SpeedIn(BaseModel):
    minutes_per_second: float = Field(ge=0, le=10)


@app.post("/api/speed")
async def set_speed(body: SpeedIn):
    with state.lock:
        state.sim_minutes_per_second = body.minutes_per_second
    return {"ok": True, "minutes_per_second": body.minutes_per_second}


@app.post("/api/vip/{room_id}")
async def toggle_vip(room_id: str):
    vip = False
    with state.lock:
        room = state.rooms.get(room_id)
        if not room:
            return {"ok": False, "error": "unknown room"}
        room.vip = not room.vip
        vip = room.vip
    return {"ok": True, "vip": vip}


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
