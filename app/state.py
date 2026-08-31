from __future__ import annotations

import copy
import threading
import uuid
from typing import Optional
import random

from app.engine import AnomalyModel, assign_staff, estimate_clean_minutes, room_priority
from app.models import (
    AssignmentRow,
    EventKind,
    GuestNotice,
    HotelSnapshot,
    NotificationKind,
    OpsEvent,
    Room,
    RoomStatus,
    RoomType,
    Staff,
    StaffRole,
    StaffSeniority,
    Task,
    TaskKind,
)

FIRST_NAMES = [
    "Aisha", "Rohan", "Meera", "Kabir", "Nina", "Arjun", "Leila", "Dev",
    "Priya", "Omar", "Sara", "Vikram", "Anya", "Farhan", "Isha", "Noah",
]
LAST_NAMES = [
    "Shah", "Patel", "Khan", "Iyer", "Das", "Nair", "Costa", "Mehta",
    "Kapoor", "Ali", "Fernandes", "Rao",
]
STAFF_NAMES = [
    ("HK-01", "Sita Kulkarni", StaffRole.HOUSEKEEPING, 1, StaffSeniority.SENIOR),
    ("HK-02", "Ramesh Pawar", StaffRole.HOUSEKEEPING, 1, StaffSeniority.JUNIOR),
    ("HK-03", "Fatima Shaikh", StaffRole.HOUSEKEEPING, 2, StaffSeniority.SENIOR),
    ("HK-04", "Joseph D'Souza", StaffRole.HOUSEKEEPING, 2, StaffSeniority.JUNIOR),
    ("HK-05", "Kavita More", StaffRole.HOUSEKEEPING, 3, StaffSeniority.SENIOR),
    ("HK-06", "Imran Qureshi", StaffRole.HOUSEKEEPING, 3, StaffSeniority.JUNIOR),
    ("IN-01", "Anita Desai", StaffRole.INSPECTOR, 2, StaffSeniority.SENIOR),
    ("IN-02", "Sunil Joshi", StaffRole.INSPECTOR, 3, StaffSeniority.JUNIOR),
    ("MT-01", "Prakash Naik", StaffRole.MAINTENANCE, 1, StaffSeniority.SENIOR),
    ("MT-02", "Lina George", StaffRole.MAINTENANCE, 2, StaffSeniority.JUNIOR),
]

ROLE_LABEL = {
    StaffRole.HOUSEKEEPING: "Housekeeping",
    StaffRole.INSPECTOR: "Inspection",
    StaffRole.MAINTENANCE: "Maintenance",
}

KIND_LABEL = {
    TaskKind.CLEAN: "cleaning",
    TaskKind.INSPECT: "inspection",
    TaskKind.MAINTAIN: "maintenance",
}


def _uid(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:6]}"

def _sample_duration_multiplier() -> float:
    """How long a task actually takes vs. its formula ETA.

    Mirrors synthesize_history()'s injection rate in engine.py so live
    tasks occasionally run long enough for the 115%-delay check and the
    Isolation Forest to actually have something to catch.
    """
    mult = max(0.7, random.gauss(1.0, 0.15))
    if random.random() < 0.07:
        mult *= random.uniform(2.4, 4.2)
    return round(mult, 3)


class HotelState:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.hour = 9.0  # 09:00 hotel time
        self.day_label = ""
        self.rooms: dict[str, Room] = {}
        self.staff: dict[str, Staff] = {}
        self.tasks: dict[str, Task] = {}
        self.notices: list[GuestNotice] = []
        self.events: list[OpsEvent] = []
        self.last_assignments: list[AssignmentRow] = []
        self.anomaly_model = AnomalyModel()
        self.ready_count_today = 0
        self.checkins_today = 0
        self.checkouts_today = 0
        self.seed()

    def seed(self) -> None:
        rooms: list[Room] = []
        for floor in (1, 2, 3):
            for n in range(1, 9):
                number = f"{floor}0{n}"
                rid = f"R{number}"
                rtype = RoomType.STANDARD
                if n in (7, 8):
                    rtype = RoomType.DELUXE
                if n == 8 and floor == 3:
                    rtype = RoomType.SUITE
                rooms.append(
                    Room(
                        id=rid,
                        floor=floor,
                        number=number,
                        room_type=rtype,
                        status=RoomStatus.OCCUPIED,
                        guests=1 + (n % 3),
                        stay_nights=1 + (n % 4),
                        guest_name=f"{FIRST_NAMES[(floor * 8 + n) % len(FIRST_NAMES)]} {LAST_NAMES[(n + floor) % len(LAST_NAMES)]}",
                    )
                )
        # Opening picture: mix of statuses so the dashboard is alive immediately
        plan = {
            "R101": (RoomStatus.DIRTY, 14.0, False, None),
            "R102": (RoomStatus.CLEANING, 13.5, False, "HK-01"),
            "R103": (RoomStatus.DUE_OUT, None, False, None),
            "R104": (RoomStatus.OCCUPIED, None, False, None),
            "R105": (RoomStatus.READY, 15.0, True, None),
            "R106": (RoomStatus.DIRTY, 12.5, True, None),
            "R107": (RoomStatus.INSPECT, 16.0, False, None),
            "R108": (RoomStatus.MAINTENANCE, 18.0, False, None),
            "R201": (RoomStatus.DIRTY, 14.5, False, None),
            "R202": (RoomStatus.DUE_OUT, None, True, None),
            "R203": (RoomStatus.OCCUPIED, None, False, None),
            "R204": (RoomStatus.CLEANING, 13.0, False, "HK-03"),
            "R205": (RoomStatus.READY, 17.0, False, None),
            "R206": (RoomStatus.DIRTY, 11.5, False, None),  # guest soon — high priority
            "R207": (RoomStatus.OCCUPIED, None, False, None),
            "R208": (RoomStatus.INSPECT, 15.5, True, None),
            "R301": (RoomStatus.DIRTY, 16.5, False, None),
            "R302": (RoomStatus.OCCUPIED, None, False, None),
            "R303": (RoomStatus.DUE_OUT, None, False, None),
            "R304": (RoomStatus.READY, 12.0, False, None),
            "R305": (RoomStatus.DIRTY, 14.0, False, None),
            "R306": (RoomStatus.CLEANING, 19.0, False, "HK-05"),
            "R307": (RoomStatus.OCCUPIED, None, True, None),
            "R308": (RoomStatus.DIRTY, 13.0, True, None),
        }
        specials = {"R308": "honeymoon setup", "R106": "late checkout linen", "R206": "allergy-safe bedding"}
        incoming = {
            "R101": "Meera Shah",
            "R105": "VIP — Kabir Khan",
            "R106": "VIP — Anya Rao",
            "R201": "Dev Patel",
            "R206": "Leila Fernandes",
            "R208": "VIP — Omar Ali",
            "R304": "Noah Das",
            "R308": "VIP — Priya Kapoor",
        }
        for r in rooms:
            status, cin, vip, assigned = plan[r.id]
            r.status = status
            r.vip = vip or r.id in ("R105", "R106", "R202", "R208", "R307", "R308")
            r.checkin_hour = cin
            r.incoming_guest = incoming.get(r.id)
            r.special_request = specials.get(r.id)
            if status == RoomStatus.DUE_OUT:
                r.checkout_hour = 11.0
            if status == RoomStatus.OCCUPIED and r.checkout_hour is None:
                r.checkout_hour = 11.0 + (int(r.number) % 6)
            if status == RoomStatus.DIRTY:
                r.checkout_hour = 10.5
                r.guest_name = None
                r.guests = 2 if r.vip else 1 + (int(r.number) % 3)
            if status in (RoomStatus.CLEANING, RoomStatus.INSPECT, RoomStatus.MAINTENANCE):
                r.guest_name = None
                r.task_started_hour = self.hour - 0.35
                r.assigned_staff_id = assigned
            if status == RoomStatus.READY:
                r.guest_name = None
                r.guests = 0
            r.estimated_minutes = estimate_clean_minutes(r)
            self.rooms[r.id] = r

        for sid, name, role, floor, seniority in STAFF_NAMES:
            senior = seniority == StaffSeniority.SENIOR
            st = Staff(
                id=sid,
                name=name,
                role=role,
                floor=floor,
                seniority=seniority,
                minutes_worked=float((hash(sid) % 40)),
                quality_score=0.96 if senior else 0.88,
                speed_factor=0.9 if senior else 1.08,
            )
            self.staff[sid] = st

        # Attach in-progress tasks
        for r in self.rooms.values():
            if r.status == RoomStatus.CLEANING and r.assigned_staff_id:
                self._open_task(r, TaskKind.CLEAN, r.assigned_staff_id)
                self.staff[r.assigned_staff_id].available = False
                self.staff[r.assigned_staff_id].current_room_id = r.id
            elif r.status == RoomStatus.INSPECT:
                inspector = "IN-01" if r.floor <= 2 else "IN-02"
                r.assigned_staff_id = inspector
                self._open_task(r, TaskKind.INSPECT, inspector)
                self.staff[inspector].available = False
                self.staff[inspector].current_room_id = r.id
            elif r.status == RoomStatus.MAINTENANCE:
                r.assigned_staff_id = "MT-01"
                self._open_task(r, TaskKind.MAINTAIN, "MT-01")
                self.staff["MT-01"].available = False
                self.staff["MT-01"].current_room_id = r.id

        self.notices.append(
            GuestNotice(
                id=_uid("N"),
                guest_name="Meera Shah",
                room_id="R101",
                kind=NotificationKind.DELAY,
                message="Room 101 is in the queue — we'll message you when it's inspection-complete.",
                hour=self.hour,
            )
        )
        self._log("Demo day opened — 24 rooms on three floors.", EventKind.OPS)
        self._log("New check-in expected for room 206.", EventKind.CHECKIN)
        self._log("Room 105 is READY for VIP arrival.", EventKind.READY)
        for r in self.rooms.values():
            if r.special_request:
                self._log(f"Special request for room {r.number}: {r.special_request}.", EventKind.OPS)

    def _open_task(self, room: Room, kind: TaskKind, staff_id: Optional[str]) -> Task:
        t = Task(
            id=_uid("T"),
            room_id=room.id,
            kind=kind,
            staff_id=staff_id,
            priority=room_priority(room, self.hour),
            created_hour=self.hour,
            started_hour=self.hour if staff_id else None,
            eta_minutes=room.estimated_minutes if kind == TaskKind.CLEAN else (12 if kind == TaskKind.INSPECT else 28),
        )
        self.tasks[t.id] = t
        return t

    def _log(self, message: str, kind: EventKind = EventKind.OPS) -> None:
        self.events.insert(0, OpsEvent(id=_uid("E"), hour=self.hour, kind=kind, message=message))
        self.events = self.events[:50]

    def _release_room_staff(self, room: Room) -> None:
        if room.assigned_staff_id:
            st = self.staff.get(room.assigned_staff_id)
            if st:
                st.available = True
                st.current_room_id = None
        for t in self.tasks.values():
            if t.room_id == room.id and not t.done:
                t.done = True
        room.assigned_staff_id = None
        room.task_started_hour = None
        room.duration_multiplier = 1.0

    def force_checkout(self, room_id: str) -> dict:
        with self.lock:
            room = self.rooms.get(room_id)
            if not room:
                return {"ok": False, "error": "unknown room"}
            self._release_room_staff(room)
            room.status = RoomStatus.DIRTY
            room.guest_name = None
            self.checkouts_today += 1
            self._log(f"Manual override: force checkout for room {room.number}.", EventKind.OVERRIDE)
            return {"ok": True}

    def toggle_vip(self, room_id: str) -> dict:
        with self.lock:
            room = self.rooms.get(room_id)
            if not room:
                return {"ok": False, "error": "unknown room"}
            room.vip = not room.vip
            flag = "on" if room.vip else "off"
            self._log(f"Manual override: VIP {flag} for room {room.number}.", EventKind.OVERRIDE)
            return {"ok": True, "vip": room.vip}

    def flag_maintenance(self, room_id: str) -> dict:
        with self.lock:
            room = self.rooms.get(room_id)
            if not room:
                return {"ok": False, "error": "unknown room"}
            self._release_room_staff(room)
            room.status = RoomStatus.MAINTENANCE
            room.guest_name = None
            room.notes = "Flagged from floor ops"
            self._log(f"Manual override: maintenance flagged for room {room.number}.", EventKind.OVERRIDE)
            return {"ok": True}

    def reset(self) -> dict:
        with self.lock:
            self.hour = 9.0
            self.day_label = ""
            self.rooms.clear()
            self.staff.clear()
            self.tasks.clear()
            self.notices.clear()
            self.events.clear()
            self.last_assignments.clear()
            self.ready_count_today = 0
            self.checkins_today = 0
            self.checkouts_today = 0
            self.seed()
            return {"ok": True}

    def tick(self, dt_hours: float = 0.04) -> None:
        #Advance simulated hotel time (~2.4 minutes per real second at default)
        with self.lock:
            self.hour = round(self.hour + dt_hours, 3)
            if self.hour >= 22:
                self.hour = 8.5
            self._process_checkouts()
            self._progress_work(dt_hours)
            self._run_assignments()
            self._flag_delays_and_anomalies()
            self._maybe_checkin()
            self._trim()

    def _process_checkouts(self) -> None:
        for r in self.rooms.values():
            if r.status == RoomStatus.DUE_OUT and self.hour >= (r.checkout_hour or 11.0):
                r.status = RoomStatus.DIRTY
                r.guest_name = None
                r.assigned_staff_id = None
                r.task_started_hour = None
                self.checkouts_today += 1
                self._log(f"Room {r.number} checked out — vacant dirty.", EventKind.CHECKOUT)
            elif r.status == RoomStatus.OCCUPIED and r.checkout_hour and self.hour >= r.checkout_hour - 0.8:
                r.status = RoomStatus.DUE_OUT

        # Occasional new due-outs so the sim never goes idle
        occupied = [r for r in self.rooms.values() if r.status == RoomStatus.OCCUPIED]
        if occupied and self.hour > 10 and hash(int(self.hour * 10)) % 7 == 0:
            pick = occupied[int(self.hour * 10) % len(occupied)]
            pick.status = RoomStatus.DUE_OUT
            pick.checkout_hour = self.hour + 0.25

    def _progress_work(self, dt_hours: float) -> None:
        for r in list(self.rooms.values()):
            if r.status not in (RoomStatus.CLEANING, RoomStatus.INSPECT, RoomStatus.MAINTENANCE):
                continue
            if r.task_started_hour is None:
                continue
            elapsed_min = (self.hour - r.task_started_hour) * 60
            r.actual_minutes = round(elapsed_min, 1)
            eta = r.estimated_minutes
            if r.status == RoomStatus.INSPECT:
                eta = 11.0
            if r.status == RoomStatus.MAINTENANCE:
                eta = 22.0
            if elapsed_min < eta * r.duration_multiplier:
                continue
            self._complete_room_step(r)

    def _complete_room_step(self, r: Room) -> None:
        staff = self.staff.get(r.assigned_staff_id) if r.assigned_staff_id else None
        for t in self.tasks.values():
            if t.room_id == r.id and not t.done and t.staff_id == r.assigned_staff_id:
                t.done = True
        if staff:
            staff.tasks_completed += 1
            staff.minutes_worked += r.actual_minutes or r.estimated_minutes
            staff.available = True
            staff.current_room_id = None
            staff.floor = r.floor

        r.duration_multiplier = 1.0

        if r.status == RoomStatus.CLEANING:
            r.status = RoomStatus.INSPECT
            r.assigned_staff_id = None
            r.task_started_hour = None
        elif r.status == RoomStatus.MAINTENANCE:
            r.status = RoomStatus.DIRTY
            r.assigned_staff_id = None
            r.task_started_hour = None
            r.notes = "Maintenance cleared — re-clean required"
        elif r.status == RoomStatus.INSPECT:
            # Rare fail → maintenance
            fail = (int(self.hour * 50) + int(r.number)) % 11 == 0
            if fail:
                r.status = RoomStatus.MAINTENANCE
                r.notes = "Inspection failed: AC / plumbing"
                r.assigned_staff_id = None
                r.task_started_hour = None
                self.notices.insert(
                    0,
                    GuestNotice(
                        id=_uid("N"),
                        guest_name=r.incoming_guest or "Front office",
                        room_id=r.id,
                        kind=NotificationKind.MAINT,
                        message=f"Room {r.number} failed inspection — maintenance dispatched.",
                        hour=self.hour,
                    ),
                )
                self._log(f"Room {r.number} failed inspection — sent to maintenance.", EventKind.MAINT)
            else:
                r.status = RoomStatus.READY
                r.assigned_staff_id = None
                r.task_started_hour = None
                r.last_cleaned_hour = self.hour
                self.ready_count_today += 1
                self._log(f"Room {r.number} passed inspection and is READY.", EventKind.READY)
                if r.incoming_guest:
                    self.notices.insert(
                        0,
                        GuestNotice(
                            id=_uid("N"),
                            guest_name=r.incoming_guest,
                            room_id=r.id,
                            kind=NotificationKind.READY,
                            message=f"Good news — Room {r.number} is ready. You may check in at the desk.",
                            hour=self.hour,
                        ),
                    )

    def _run_assignments(self) -> None:
        rows: list[AssignmentRow] = []
        for kind in (TaskKind.CLEAN, TaskKind.INSPECT, TaskKind.MAINTAIN):
            matches = assign_staff(self.rooms.values(), self.staff.values(), self.hour, kind)
            for st, room, cost, reason in matches:
                st.available = False
                st.current_room_id = room.id
                room.assigned_staff_id = st.id
                room.task_started_hour = self.hour
                room.estimated_minutes = estimate_clean_minutes(room, st)
                room.duration_multiplier = _sample_duration_multiplier()
                if kind == TaskKind.CLEAN:
                    room.status = RoomStatus.CLEANING
                elif kind == TaskKind.INSPECT:
                    room.status = RoomStatus.INSPECT
                else:
                    room.status = RoomStatus.MAINTENANCE
                self._open_task(room, kind, st.id)
                pri = room_priority(room, self.hour)
                self._log(
                    f"{st.name} assigned to {KIND_LABEL[kind]} — room {room.number} (priority {pri:.0f}).",
                    EventKind.ASSIGN,
                )
                rows.append(
                    AssignmentRow(
                        staff_id=st.id,
                        staff_name=st.name,
                        room_id=room.id,
                        cost=round(cost, 2),
                        reason=reason,
                    )
                )
        if rows:
            self.last_assignments = rows + self.last_assignments
            self.last_assignments = self.last_assignments[:12]

    def _flag_delays_and_anomalies(self) -> None:
        for t in self.tasks.values():
            if t.done:
                continue
            room = self.rooms.get(t.room_id)
            if not room:
                continue
            t.priority = room_priority(room, self.hour)
            if room.task_started_hour is not None:
                elapsed = (self.hour - room.task_started_hour) * 60
                t.delayed = elapsed > t.eta_minutes * 1.15
                staff = self.staff.get(t.staff_id) if t.staff_id else None
                load = staff.minutes_worked if staff else 0.0
                flag, score = self.anomaly_model.score_task(room, self.hour, load)
                t.anomaly = flag
                t.anomaly_score = score

    def _maybe_checkin(self) -> None:
        ready = [r for r in self.rooms.values() if r.status == RoomStatus.READY]
        for r in ready:
            if r.checkin_hour is None:
                continue
            if self.hour >= r.checkin_hour and r.incoming_guest:
                r.status = RoomStatus.OCCUPIED
                r.guest_name = r.incoming_guest.replace("VIP — ", "")
                r.incoming_guest = None
                r.checkin_hour = None
                r.checkout_hour = min(21.0, self.hour + 18)
                self.checkins_today += 1
                self._log(f"Guest checked in to room {r.number}.", EventKind.CHECKIN)

        # Recycle empty ready rooms into future arrivals — every idle room gets a new arrival queued, staggered a bit so they don't all land at once.
        idle_ready = [r for r in self.rooms.values() if r.status == RoomStatus.READY and r.incoming_guest is None]
        for i, r in enumerate(idle_ready):
            r.checkin_hour = self.hour + 0.25 + 0.15 * i
            r.incoming_guest = f"{FIRST_NAMES[int(self.hour * 7 + i) % len(FIRST_NAMES)]} {LAST_NAMES[int(self.hour * 11 + i) % len(LAST_NAMES)]}"
            r.vip = (int(self.hour * 3) + i) % 5 == 0
            self._log(f"New check-in expected for room {r.number}.", EventKind.CHECKIN)

        # Occupied rooms without checkout get one later in the day
        for r in self.rooms.values():
            if r.status == RoomStatus.OCCUPIED and r.checkout_hour is None:
                r.checkout_hour = 11.0 + (int(r.number) % 6)

    def _trim(self) -> None:
        done = [tid for tid, t in self.tasks.items() if t.done]
        if len(done) > 40:
            for tid in done[:-30]:
                self.tasks.pop(tid, None)
        self.notices = self.notices[:40]
        self.events = self.events[:50]

    def snapshot(self) -> HotelSnapshot:
        with self.lock:
            rooms = [copy.deepcopy(r) for r in self.rooms.values()]
            staff = [copy.deepcopy(s) for s in self.staff.values()]
            tasks = [copy.deepcopy(t) for t in self.tasks.values() if not t.done]
            delayed = [t.id for t in tasks if t.delayed]
            anomalies = [
                {
                    "task_id": t.id,
                    "room_id": t.room_id,
                    "score": t.anomaly_score,
                    "kind": t.kind,
                }
                for t in tasks
                if t.anomaly
            ]
            by_status = {}
            for r in rooms:
                by_status[r.status.value] = by_status.get(r.status.value, 0) + 1
            hk = [s for s in staff if s.role == StaffRole.HOUSEKEEPING]
            avg_load = sum(s.minutes_worked for s in hk) / max(len(hk), 1)
            ready_rate = self.ready_count_today
            waiting = sum(
                1
                for r in rooms
                if r.checkin_hour is not None
                and r.checkin_hour <= self.hour
                and r.status != RoomStatus.READY
                and r.status != RoomStatus.OCCUPIED
            )
            kpis = {
                "hotel_clock": _fmt_clock(self.hour),
                "ready": by_status.get("ready", 0),
                "dirty": by_status.get("dirty", 0),
                "cleaning": by_status.get("cleaning", 0),
                "inspect": by_status.get("inspect", 0),
                "maintenance": by_status.get("maintenance", 0),
                "occupied": by_status.get("occupied", 0),
                "due_out": by_status.get("due_out", 0),
                "ready_today": ready_rate,
                "checkins_today": self.checkins_today,
                "checkouts_today": self.checkouts_today,
                "avg_hk_minutes": round(avg_load, 1),
                "guests_waiting": waiting,
                "open_tasks": len(tasks),
                "anomalies": len(anomalies),
            }
            analytics = {
                "staff": [
                    {
                        "id": s.id,
                        "name": s.name,
                        "role": s.role,
                        "role_label": ROLE_LABEL.get(s.role, s.role),
                        "seniority": s.seniority,
                        "tasks": s.tasks_completed,
                        "minutes": round(s.minutes_worked, 1),
                        "avg_minutes": round(s.minutes_worked / max(s.tasks_completed, 1), 1),
                        "quality": s.quality_score,
                        "busy": not s.available,
                        "current_room_id": s.current_room_id,
                    }
                    for s in staff
                ],
                "status_counts": by_status,
                "priority_queue": [
                    {
                        "room_id": r.id,
                        "number": r.number,
                        "priority": room_priority(r, self.hour),
                        "status": r.status,
                        "vip": r.vip,
                        "checkin": r.checkin_hour,
                        "special": r.special_request,
                    }
                    for r in sorted(
                        [x for x in rooms if x.status in (RoomStatus.DIRTY, RoomStatus.INSPECT, RoomStatus.MAINTENANCE, RoomStatus.CLEANING)],
                        key=lambda x: room_priority(x, self.hour),
                        reverse=True,
                    )
                ],
            }
            return HotelSnapshot(
                hotel_hour=self.hour,
                day_label=self.day_label,
                rooms=rooms,
                staff=staff,
                tasks=tasks,
                notices=list(self.notices),
                assignments=list(self.last_assignments),
                kpis=kpis,
                analytics=analytics,
                delayed_tasks=delayed,
                anomalies=anomalies,
                events=list(self.events),
            )


def _fmt_clock(hour: float) -> str:
    h = int(hour) % 24
    m = int((hour - int(hour)) * 60)
    return f"{h:02d}:{m:02d}"
