from __future__ import annotations

from typing import Iterable

import numpy as np
from scipy.optimize import linear_sum_assignment
from sklearn.ensemble import IsolationForest

from app.models import Room, RoomStatus, RoomType, Staff, StaffRole, Task, TaskKind


ROOM_TYPE_CODE = {RoomType.STANDARD: 0, RoomType.DELUXE: 1, RoomType.SUITE: 2}

BASE_CLEAN_MIN = {
    RoomType.STANDARD: 22.0,
    RoomType.DELUXE: 28.0,
    RoomType.SUITE: 40.0,
}


def estimate_clean_minutes(room: Room, staff: Staff | None = None) -> float:
    minutes = BASE_CLEAN_MIN[room.room_type]
    minutes += max(0, room.guests - 1) * 4.5
    minutes += max(0, room.stay_nights - 1) * 1.4
    if room.special_request:
        minutes += 8.0
    if room.vip:
        minutes += 6.0
    if staff:
        minutes *= staff.speed_factor
    return round(minutes, 1)


def room_priority(room: Room, hotel_hour: float) -> float:
    """Higher score = clean sooner. Mix of arrivals, VIP, delay, occupancy cycle."""
    score = 10.0
    if room.status in (RoomStatus.OCCUPIED, RoomStatus.READY):
        return 0.0

    if room.checkin_hour is not None:
        hours_until = room.checkin_hour - hotel_hour
        if hours_until <= 0:
            score += 90.0  # guest waiting
        elif hours_until < 1:
            score += 70.0
        elif hours_until < 2:
            score += 50.0
        elif hours_until < 4:
            score += 28.0
        else:
            score += 8.0
    else:
        score += 4.0  # no inbound guest — fill later

    if room.vip:
        score += 35.0
    if room.special_request:
        score += 12.0
    if room.status == RoomStatus.MAINTENANCE:
        score += 18.0
    if room.status == RoomStatus.INSPECT:
        score += 8.0

    if room.task_started_hour is not None:
        elapsed = (hotel_hour - room.task_started_hour) * 60
        if elapsed > room.estimated_minutes:
            score += min(40.0, (elapsed - room.estimated_minutes) * 1.2)

    # slight floor-cluster bias is applied in assignment cost, not here
    return round(score, 2)


def _feature_row(
    duration_so_far: float,
    estimated: float,
    guests: int,
    stay_nights: int,
    room_type: RoomType,
    hour: float,
    staff_load: float,
) -> list[float]:
    return [
        duration_so_far,
        estimated,
        duration_so_far / max(estimated, 1.0),
        float(guests),
        float(stay_nights),
        float(ROOM_TYPE_CODE[room_type]),
        hour,
        staff_load,
    ]


def synthesize_history(n: int = 900, seed: int = 42) -> np.ndarray:
    rng = np.random.default_rng(seed)
    rows = []
    types = [RoomType.STANDARD, RoomType.DELUXE, RoomType.SUITE]
    for _ in range(n):
        rtype = types[int(rng.integers(0, 3))]
        guests = int(rng.choice([1, 1, 2, 2, 2, 3, 4]))
        stay = int(rng.integers(1, 8))
        estimated = BASE_CLEAN_MIN[rtype] + max(0, guests - 1) * 4.5 + max(0, stay - 1) * 1.4
        hour = float(rng.uniform(8, 18))
        staff_load = float(rng.uniform(0, 180))
        duration = float(estimated + rng.normal(0, 3.8))
        duration = max(8.0, duration)
        if rng.random() < 0.06:
            duration *= float(rng.uniform(2.4, 4.2))  # injected anomalies
        rows.append(_feature_row(duration, estimated, guests, stay, rtype, hour, staff_load))
    return np.array(rows, dtype=float)


class AnomalyModel:
    def __init__(self) -> None:
        X = synthesize_history()
        self.model = IsolationForest(
            n_estimators=120,
            contamination=0.06,
            random_state=42,
        )
        self.model.fit(X)

    def score_task(self, room: Room, hotel_hour: float, staff_load: float) -> tuple[bool, float]:
        if room.task_started_hour is None:
            return False, 0.0
        elapsed = max(0.0, (hotel_hour - room.task_started_hour) * 60)
        if elapsed < 8:
            return False, 0.0
        x = np.array(
            [
                _feature_row(
                    elapsed,
                    room.estimated_minutes,
                    room.guests,
                    room.stay_nights,
                    room.room_type,
                    hotel_hour,
                    staff_load,
                )
            ]
        )
        raw = float(self.model.decision_function(x)[0])  # lower = more anomalous
        flag = int(self.model.predict(x)[0]) == -1
        # invert so higher score = more anomalous for the UI
        anomaly_score = round(-raw, 4)
        return flag, anomaly_score


def assign_staff(
    rooms: Iterable[Room],
    staff: Iterable[Staff],
    hotel_hour: float,
    kind: TaskKind,
) -> list[tuple[Staff, Room, float, str]]:
    """Hungarian assignment: min cost matching of free staff to pending rooms."""
    role = {
        TaskKind.CLEAN: StaffRole.HOUSEKEEPING,
        TaskKind.INSPECT: StaffRole.INSPECTOR,
        TaskKind.MAINTAIN: StaffRole.MAINTENANCE,
    }[kind]

    eligible_status = {
        TaskKind.CLEAN: {RoomStatus.DIRTY},
        TaskKind.INSPECT: {RoomStatus.INSPECT},
        TaskKind.MAINTAIN: {RoomStatus.MAINTENANCE},
    }[kind]

    free = [s for s in staff if s.role == role and s.available and s.current_room_id is None]
    pending = [
        r
        for r in rooms
        if r.status in eligible_status and r.assigned_staff_id is None
    ]
    if not free or not pending:
        return []

    pending.sort(key=lambda r: room_priority(r, hotel_hour), reverse=True)
    pending = pending[: len(free) * 2]  # keep matrix small; still optimal among these
    if len(pending) > len(free):
        pending = pending[: len(free)]

    n_s, n_r = len(free), len(pending)
    size = max(n_s, n_r)
    cost = np.full((size, size), 1e6)

    reasons: dict[tuple[int, int], str] = {}
    for i, s in enumerate(free):
        for j, r in enumerate(pending):
            eta = estimate_clean_minutes(r, s) if kind == TaskKind.CLEAN else (12.0 if kind == TaskKind.INSPECT else 30.0)
            floor_pen = abs(s.floor - r.floor) * 7.0
            load_pen = s.minutes_worked * 0.04
            vip_boost = -18.0 if r.vip else 0.0
            arrival_boost = 0.0
            if r.checkin_hour is not None:
                arrival_boost = -max(0.0, 25.0 - (r.checkin_hour - hotel_hour) * 8)
            skill_pen = 0.0
            if kind == TaskKind.CLEAN and r.room_type == RoomType.SUITE and s.quality_score < 0.9:
                skill_pen = 10.0
            c = eta + floor_pen + load_pen + vip_boost + arrival_boost + skill_pen
            cost[i, j] = c
            bits = []
            if r.vip:
                bits.append("VIP")
            if r.checkin_hour is not None and r.checkin_hour - hotel_hour < 2:
                bits.append("imminent arrival")
            if floor_pen == 0:
                bits.append(f"same floor {r.floor}")
            else:
                bits.append(f"floor Δ{abs(s.floor - r.floor)}")
            bits.append(f"load {int(s.minutes_worked)}m")
            reasons[(i, j)] = ", ".join(bits)

    row_ind, col_ind = linear_sum_assignment(cost)
    matches: list[tuple[Staff, Room, float, str]] = []
    for i, j in zip(row_ind, col_ind):
        if i >= n_s or j >= n_r:
            continue
        if cost[i, j] >= 1e5:
            continue
        matches.append((free[i], pending[j], float(cost[i, j]), reasons.get((i, j), "")))
    return matches
