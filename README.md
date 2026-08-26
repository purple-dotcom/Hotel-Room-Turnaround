# Turnwise — hotel room turnaround

Working prototype for **PCACS PS 4 (SIH internal)**: live housekeeping coordination from checkout → clean → inspect → ready, with local ML and an optimization algorithm. **No cloud AI API, no rate limits.**

## What it does

- Live floor board of 24 rooms (occupied, due-out, dirty, cleaning, inspect, maintenance, ready)
- Priority scoring from expected arrivals, VIP, special requests, and delay
- **Hungarian algorithm** (SciPy) assigns free staff to rooms by cost (ETA + floor distance + workload − VIP/arrival urgency)
- **Isolation Forest** (scikit-learn) trained on ~900 synthetic past cleans; flags stuck/odd tasks live
- Guest readiness / delay / maintenance messages
- Staff workload bars and completed-room counts
- Hotel clock runs faster than real time so a demo shows the full cycle in minutes

Click an occupied / due-out room to force checkout. Click other rooms to toggle VIP (watch the queue jump).

## Run in VS Code (Windows)

1. Open this folder in VS Code / Cursor.
2. In the terminal:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

3. Browser: [http://127.0.0.1:8000](http://127.0.0.1:8000)

If `py` is not found, use `python` instead.

## GitHub vs a live website

**GitHub Pages cannot run this project.** Pages only serves static HTML. This app is Python (FastAPI + WebSocket + a live simulator), so it needs a server process.

**What GitHub is good for (free):** put the source in a public repo so judges / teammates can clone it and so Render can deploy from it.

```powershell
cd C:\Users\crank\hotel-turnaround
git add app static requirements.txt Procfile README.md .gitignore run.bat
git commit -m "Turnwise SIH prototype"
# create an empty repo on github.com, then:
git remote add origin https://github.com/YOUR_USER/hotel-turnaround.git
git branch -M main
git push -u origin main
```

**Free live URL (recommended): [Render](https://render.com)**

1. Push the repo to GitHub.
2. Render → New → Web Service → connect that repo.
3. Runtime: Python. Build: `pip install -r requirements.txt`. Start: `uvicorn app.main:app --host 0.0.0.0 --port $PORT` (or it will pick up the `Procfile`).
4. Free instance type. First boot can take a few minutes (scikit-learn / SciPy).

Caveats: the free instance **sleeps after ~15 minutes idle**, so the first open after that is slow. The hotel state is **in memory** — sleep or restart wipes the demo back to the seed. For the internal round, run it **locally** as backup.

**Other free-ish options:** Hugging Face Spaces (Docker), Railway (trial credits, not forever-free). Do not use Vercel/Netlify for this backend.

## Pitch line

We simulate realistic historical housekeeping data to train a lightweight anomaly-detection model, then apply it live — combined with an optimization algorithm that recomputes the best staff-to-room assignment in real time, using no external AI APIs.

## Project layout

- `app/engine.py` — priority, Hungarian assignment, Isolation Forest
- `app/state.py` — in-memory hotel + event simulator
- `app/main.py` — FastAPI + WebSocket
- `static/` — supervisor dashboard
