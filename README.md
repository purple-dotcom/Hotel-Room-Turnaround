# Turnwise

Live hotel housekeeping coordination — checkout → clean → inspect → ready — built for **PCACS PS 4 (Smart India Hackathon, internal round)**: *Smart Hotel Room Turnaround & Housekeeping Optimization*.

A vacant room isn't a sellable room until it's been cleaned, inspected, and marked ready — and in most hotels, front desk, housekeeping, and maintenance track that through separate, disconnected channels. Turnwise keeps one shared live state and automatically works out who should clean or inspect which room next.

## Features

- Live floor board across 24 rooms, 3 floors — occupied, due-out, dirty, cleaning, inspect, maintenance, ready
- Priority scoring per room from expected arrivals, VIP status, special requests, and delay
- Optimal staff-to-room assignment via the **Hungarian algorithm** (SciPy) — balances job duration, floor distance, and staff workload rather than just picking the nearest free person
- **Isolation Forest** (scikit-learn) trained on simulated historical cleans, flagging tasks that are running abnormally long
- In-app guest readiness / delay / maintenance notices
- Staff workload and completion tracking
- A simulated hotel clock that runs faster than real time, so a full room-turnaround cycle plays out in seconds rather than hours

All decisions run locally — no external AI API, no rate limits, no internet dependency after install.

## Tech stack

| Layer | Tech |
|---|---|
| Backend | FastAPI + WebSocket, in-memory state |
| Optimization | SciPy (`linear_sum_assignment` — Hungarian algorithm) |
| Anomaly detection | scikit-learn (`IsolationForest`) |
| Frontend | Static HTML/CSS/JS, no framework |

## Project layout

| Path | What's there |
|---|---|
| `app/models.py` | Data shapes — Room, Staff, Task, GuestNotice, and their statuses |
| `app/engine.py` | Clean-time estimation, priority scoring, Hungarian assignment, Isolation Forest |
| `app/state.py` | Hotel state and the tick-by-tick event simulator |
| `app/main.py` | FastAPI app, HTTP endpoints, WebSocket feed |
| `static/` | Supervisor dashboard (floor ops, assignments, staff, guest notices) |

## Getting started

Requires Python 3.14.

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Then open [http://127.0.0.1:8000](http://127.0.0.1:8000).

Click an **In house** / **Due out** room to force a checkout. Click any other room to toggle its VIP flag and watch the priority queue react.

## How it works, briefly

Every second, the server advances the simulated hotel clock by one minute and re-runs a full cycle: process checkouts → progress in-flight cleans/inspections/maintenance → assign free staff to pending rooms (Hungarian, run separately for housekeeping, inspection, and maintenance) → flag delayed or anomalous tasks → resolve check-ins → push the updated state to every connected browser over WebSocket.

Estimated clean time is a transparent formula (room type + guests + nights + VIP/special-request adjustments), not a model — it's meant to be auditable. The only ML in the project is the anomaly detector, trained at startup on ~900 synthesized past cleans.

## Known limitations

- State is in-memory only — a restart resets the hotel to its seeded opening state.
- No persistent database; a production version would sit on top of a real PMS and datastore.
- Single shared dashboard — no distinct per-staff mobile view yet (housekeepers/inspectors don't get individual pushed task feeds).
- Guest notices are in-app only, not SMS/WhatsApp.
- The clock is a simulation for demo purposes, not the guest's real-time wall clock.

## Deploying

GitHub Pages can't run this — it's a Python backend (FastAPI + WebSocket + a live simulator), not static HTML. [Render](https://render.com) works on a free tier: connect this repo, set the build command to `pip install -r requirements.txt`, and the start command to `uvicorn app.main:app --host 0.0.0.0 --port $PORT` (or let it pick up the included `Procfile`). Note the free tier sleeps after ~15 minutes idle and resets in-memory state on wake.