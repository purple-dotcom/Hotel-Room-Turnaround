# ReadMePresenter — how to explain Turnwise

Read this until you can tell the story without looking. It matches **this repo**, not a generic hotel app. If a judge asks something we did not build, use the honest answers at the end.

**On-screen name:** Turnwise  
**Hackathon:** SIH internal · **PCACS PS 4** — Smart Hotel Room Turnaround & Housekeeping Optimization  
**One sentence you can open with:**  
*A live operations board that takes a room from checkout to ready: it scores which rooms matter first, assigns staff with an optimization algorithm, and flags jobs that look abnormally slow — all in Python on this laptop, no ChatGPT API.*

---

## 0. The real-world problem (30 seconds)

Hotels run a loop: check-out → clean → inspect → maybe maintenance → check-in.

A room can be **empty and still not sellable**: cleaning not started, cleaning done but inspection pending, something broken, or the status never updated. Front office, housekeeping, maintenance, and the guest usually sit on different chats. Result: guests wait, some attendants are overloaded, VIP rooms sit dirty, nobody has one live picture.

**Turnwise:** one shared live state + automatic “who goes to which room next.”

---

## 1. What the demo hotel is

Not a real property. A **simulated 24-room, 3-floor** hotel that starts at **09:00 hotel time**.

| Piece | What we seeded |
|--------|----------------|
| Rooms | 24 — floors 1–3, numbers `101`–`108`, `201`–`208`, `301`–`308` |
| Types | Standard; deluxe on xx07/xx08; **suite 308** |
| Housekeeping | 6 people: `HK-01` … `HK-06` |
| Inspectors | `IN-01`, `IN-02` |
| Maintenance | `MT-01`, `MT-02` |
| VIPs / specials | e.g. 308 honeymoon setup, 106 late linen, 206 allergy-safe bedding |

**Hotel clock:** every **1 real second**, the hotel advances **1 hotel minute** (`tick(1/60)` hour in `app/main.py`). A 25-minute clean is about 25 seconds on stage. When the clock reaches **22:00** it jumps back to **08:30** so the demo never ends.

Say: *“This clock is simulated so you can watch a full turnaround in the pitch. It is not the guest’s wall clock.”*

---

## 2. Room statuses — the workflow you must recite

Point at the floor board. This is the product.

```
occupied  →  due_out  →  dirty  →  cleaning  →  inspect  →  ready  →  occupied (next guest)
                                           ↑                    |
                                           |                    v
                                           +←── maintenance ←── (inspect fail)
```

| Label on the board | Code status | Meaning |
|--------------------|-------------|---------|
| In house | `occupied` | Guest currently in the room |
| Due out | `due_out` | Checkout soon; still occupied |
| Vacant dirty | `dirty` | Guest left; needs a housekeeper |
| Cleaning | `cleaning` | Housekeeper is on it |
| Inspect | `inspect` | Clean finished; inspector must sign off |
| Maint. | `maintenance` | Failed inspect / fault |
| Ready | `ready` | Next guest can check in |

**★** = VIP (`room.vip`). Extra clean minutes, higher priority, preferred in assignment.

**Clicks (demo):**

- Click **In house** or **Due out** → `POST /api/checkout/{room_id}` → immediately **dirty** (forced checkout).
- Click any other room → `POST /api/vip/{room_id}` → toggle VIP (watch the queue).

---

## 3. Architecture (draw this with your finger)

> *“The browser is a TV. All decisions happen in Python. Every second the server ticks the hotel and pushes a snapshot over WebSocket. The page only redraws.”*

```
  Browser (static/index.html + app.js)
       │  GET /           HTML/CSS/JS
       │  GET /api/state  first paint
       │  WebSocket /ws   live updates every 1s
       │  POST /api/checkout/{id}  and  /api/vip/{id}
       ▼
  FastAPI — app/main.py
       │  simulator_loop: sleep 1s → state.tick → broadcast JSON
       ▼
  HotelState — app/state.py
       │  rooms, staff, tasks, guest notices, last assignments
       │  each tick: checkouts → finish work → assign → flag delays → check-ins
       ▼
  app/engine.py
       ├── estimate_clean_minutes   (formula, not ML)
       ├── room_priority            (who is cleaned first)
       ├── assign_staff             (Hungarian / SciPy)
       └── AnomalyModel             (Isolation Forest / sklearn)
```

**Libraries:** FastAPI, uvicorn, numpy, scikit-learn, SciPy. **No OpenAI, no paid API, no internet required after `pip install`.**

**Memory:** everything lives in RAM. Restart uvicorn = hotel resets to the seed (already a mix of dirty/cleaning/inspect so the board is not empty).

---

## 4. Folder map (if they ask “what’s in the project?”)

| Path | Job |
|------|-----|
| `app/models.py` | Data shapes: Room, Staff, Task, GuestNotice, statuses |
| `app/engine.py` | ETA, priority, Hungarian assignment, Isolation Forest |
| `app/state.py` | The hotel + event simulator + tick order |
| `app/main.py` | Website, click APIs, WebSocket, 1-second loop |
| `static/` | Supervisor UI (four tabs) |
| `requirements.txt` | Python packages |
| `README.md` | How to run / deploy notes |
| `ReadMePresenter.md` | This file — how to talk |

---

## 5. One tick, in order (`HotelState.tick`)

Every second, with a lock:

1. **Advance** `hour` (wrap at 22:00 → 08:30).
2. **`_process_checkouts`** — due-out time hit → dirty; occupied near checkout → due_out; sometimes invent a new due-out so the sim stays busy.
3. **`_progress_work`** — if cleaning / inspect / maintenance has run past its ETA, **`_complete_room_step`**.
4. **`_run_assignments`** — Hungarian for clean, inspect, and maintain separately.
5. **`_flag_delays_and_anomalies`** — over 115% of ETA = delayed; Isolation Forest may set `anomaly`.
6. **`_maybe_checkin`** — ready + check-in time → occupied; idle ready rooms get a future arrival.
7. **`_trim`** — drop old finished tasks / notices so RAM stays small.

Then `snapshot()` copies state to JSON and every `/ws` client gets it.

---

## 6. Completing a room (`_complete_room_step`)

When ETA is reached:

- Staff is freed, `tasks_completed` and `minutes_worked` go up, they “move” to that floor.
- **Cleaning done** → status **inspect** (staff cleared; next tick an inspector can be assigned).
- **Maintenance done** → status **dirty** again (must re-clean) + note.
- **Inspect done** — about 1 in 11 rooms fail (`% 11 == 0`): **maintenance** + guest notice. Otherwise **ready** + “Room X is ready…” notice if there is an incoming guest.

---

## 7. Estimated clean time — formula, not AI

`estimate_clean_minutes` in `engine.py`.

Base: standard **22** min, deluxe **28**, suite **40**. Then:

- +**4.5** min per extra guest after the first  
- +**1.4** min per extra night after the first  
- +**8** if `special_request`  
- +**6** if VIP  
- × that housekeeper’s `speed_factor` if assigned  

Inspect ETA is treated as ~11–12 minutes, maintenance ~22–28, not the full clean formula.

*“ETA is an operations formula you can audit. ML is only for ‘is this taking a weirdly long time.’”*

---

## 8. Priority score — who is cleaned first

`room_priority(room, hotel_hour)`. Occupied and ready rooms score **0** (not in the work queue).

Higher number = sooner. Rough weights:

| Situation | Effect |
|-----------|--------|
| Incoming guest already waiting (check-in time passed) | +90 |
| Arrival in &lt; 1 hour | +70 |
| &lt; 2 hours | +50 |
| &lt; 4 hours | +28 |
| Later today | +8 |
| No inbound guest | +4 |
| VIP | +35 |
| Special request | +12 |
| In maintenance | +18 |
| Waiting inspect | +8 |
| Already over ETA | extra points (capped) |

This is **rules**, not a neural net. The right-hand **Priority queue** is this list sorted high → low.

Toggle VIP on a dirty room and the number should jump.

---

## 9. Hungarian algorithm — staff to rooms

`assign_staff` → SciPy `linear_sum_assignment` (this **is** the Hungarian algorithm).

**Explain like this:**  
We have free people and pending rooms. We fill a **cost grid**: row = staff, column = room. Each cell = “how bad is this pairing.” The algorithm picks pairs with **minimum total cost** — globally better than “send the nearest person first.”

We run it **three times** per tick (roles don’t mix):

- `dirty` rooms ↔ housekeeping  
- `inspect` rooms ↔ inspectors  
- `maintenance` rooms ↔ maintenance  

If there are more dirty rooms than free housekeepers, we only keep the **highest-priority** rooms (as many as there are free staff). Optimal among *those*.

**Cost of one pair** (lower = more likely):

| Term | Meaning |
|------|---------|
| ETA | Long jobs cost more |
| `|staff.floor − room.floor| × 7` | Walking between floors |
| `minutes_worked × 0.04` | **Workload balance** — busy staff cost more |
| VIP | **−18** (prefer) |
| Imminent arrival | negative (prefer) |
| Suite + quality &lt; 0.9 | +10 skill mismatch |

The **Assignment** tab shows staff, room, **cost**, and a **reason** (VIP, same floor, load, imminent arrival).

*“We solve a small assignment problem every second. That is the optimization.”*

---

## 10. Isolation Forest — the only ML

Class `AnomalyModel` in `engine.py`.

**Not** language AI. **Not** “predict tomorrow’s occupancy.”

**At startup:**

1. `synthesize_history()` builds **~900 fake past cleans** (type, guests, nights, typical duration + noise).  
2. About **6%** are stretched 2.4–4.2× too long on purpose.  
3. Fit sklearn **IsolationForest** (`n_estimators=120`, `contamination=0.06`).

**Features:** minutes so far, ETA, ratio so far/ETA, guests, nights, room-type code, hour, that worker’s minutes worked.

**Live:** after a job has run **≥ 8 hotel minutes**, `score_task`. `predict == -1` → **anomaly** on the UI. Separately, elapsed &gt; **115% of ETA** → **delayed**.

*“We simulate historical housekeeping data, train a small anomaly detector, apply it live, next to Hungarian assignment. Local libraries only.”*

If they say the history is fake: *“Yes — hackathon. A real hotel would train the same model on PMS / housekeeping logs.”*

---

## 11. Guest notices

Tab **Guest notices**. An in-app log (not SMS):

- Inspect **pass** + incoming guest → room-ready message  
- Inspect **fail** → maintenance dispatched  
- Seed starts with a “you’re in the queue” note for 101  

Do **not** claim WhatsApp/Twilio unless you add it later.

---

## 12. The four tabs

| Tab | Say this |
|-----|----------|
| **Floor ops** | Supervisor floor board, KPIs, priority queue, anomalies |
| **Assignment** | Last Hungarian matches + open tasks + delayed/anomaly |
| **Staff** | Minutes, rooms finished, busy/free, quality proxy |
| **Guest notices** | Readiness / fail copy |

KPIs along the top: clock, ready, dirty, cleaning, inspect, maint, guests waiting, anomalies, rooms turned today.

---

## 13. Spoken walkthrough (one room)

1. Guest leaves (sim or your click) → **dirty**.  
2. `room_priority` ranks it (arrival / VIP / special).  
3. Next tick `assign_staff` binds a free housekeeper → **cleaning**.  
4. Time hits ETA → **inspect**; an inspector is matched the same way.  
5. Pass → **ready** + notice; fail → **maintenance**, then dirty again.  
6. If it drags: **delayed** and maybe Isolation Forest **anomaly**.  
7. Browser got the JSON on `/ws` and redrew.

---

## 14. Live demo script (~2 minutes)

1. Open http://127.0.0.1:8000 — “24 rooms, live hotel clock.”  
2. KPIs.  
3. Click an **In house** room — “Front office checkout.” Watch it go dirty.  
4. **Priority queue** + **Assignment** — read one cost reason out loud.  
5. ★ VIP / special tag (308, 206). Toggle VIP on a dirty room.  
6. **Staff** — “Load penalty spreads work.”  
7. **Guest notices**.  
8. Close: “Classical ML + Hungarian, on-device, demo-safe.”

---

## 15. 60-second pitch (memorize)

A vacant room is not a ready room — cleaning, inspection, maintenance, and the desk don’t share one live view. Turnwise is a supervisor dashboard on a 24-room simulated hotel. We score rooms by arrival time, VIP, specials, and delay. Free staff are assigned with the Hungarian algorithm so we minimize a mix of duration, floor travel, and workload. Isolation Forest, trained on simulated past cleans, flags jobs that don’t look normal. Guests get an in-app message when inspection passes. The whole stack is Python on this machine — no external AI API.

---

## 16. Q&A cheat sheet

**Why not an LLM to assign rooms?**  
The live path cannot depend on an API that is slow, billed, or down during judging. Matching is math; outliers are a small local model.

**Is this AI?**  
Classical ML + optimization. Not generative AI.

**Predictive scheduling?**  
We **use known expected check-in times** in the score. We do **not** forecast tomorrow’s check-outs from history. Don’t say “demand forecasting model.”

**Mobile workforce?**  
Browser dashboard only. No phone GPS app.

**Analytics?**  
Live counts and staff bars for **this demo day**, not a week of BI.

**Database?**  
None. RAM + seed. Production would plug into a PMS and a real DB.

**WebSocket?**  
Server **pushes** the snapshot so we don’t refresh. Fallback would be polling `/api/state`.

**Hungarian vs greedy?**  
Greedy: best room for person 1, leftovers for person 2 — can be worse overall. Hungarian: best **set** of pairs for the matrix we built.

---

## 17. How to run (if they ask)

```powershell
cd C:\Users\crank\hotel-turnaround
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --reload --port 8000
```

Open http://127.0.0.1:8000  

If there is no venv: `py -m venv .venv` then `pip install -r requirements.txt`.

---

## 18. PS 4 checklist (for slides / form)

| Requirement | Where it lives |
|-------------|----------------|
| Occupancy | Floor statuses |
| Expected check-outs | `due_out` + `checkout_hour` |
| Expected check-ins | `incoming_guest` + `checkin_hour` |
| Task allocation | `assign_staff` Hungarian |
| Cleaning status | dirty / cleaning |
| Inspection | inspect + pass/fail |
| Maintenance | status + `MT-*` staff |
| Priority rooms | `room_priority` |
| Workload balancing | `minutes_worked` in cost |
| Estimated clean time | `estimate_clean_minutes` |
| VIP / specials | flags + extra minutes + score |
| Real-time readiness | `/ws` board |
| Delayed tasks | 115% ETA |
| Supervisor dashboard | Floor ops |
| Staff analytics | Staff tab (live only) |
| Guest notification | Notices tab (in-app) |

**Practice once:** statuses → four boxes → Hungarian → Isolation Forest → click checkout. That is the whole talk.
