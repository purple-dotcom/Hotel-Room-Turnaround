from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class RoomStatus(str, Enum):
    OCCUPIED = "occupied"
    DUE_OUT = "due_out"
    DIRTY = "dirty"
    CLEANING = "cleaning"
    INSPECT = "inspect"
    MAINTENANCE = "maintenance"
    READY = "ready"


class RoomType(str, Enum):
    STANDARD = "standard"
    DELUXE = "deluxe"
    SUITE = "suite"


class StaffRole(str, Enum):
    HOUSEKEEPING = "housekeeping"
    INSPECTOR = "inspector"
    MAINTENANCE = "maintenance"


class StaffSeniority(str, Enum):
    SENIOR = "senior"
    JUNIOR = "junior"


class EventKind(str, Enum):
    OVERRIDE = "override"
    ASSIGN = "assign"
    READY = "ready"
    CHECKIN = "checkin"
    CHECKOUT = "checkout"
    INSPECT = "inspect"
    MAINT = "maint"
    OPS = "ops"


class TaskKind(str, Enum):
    CLEAN = "clean"
    INSPECT = "inspect"
    MAINTAIN = "maintain"


class NotificationKind(str, Enum):
    READY = "room_ready"
    DELAY = "delay"
    VIP = "vip_prep"
    MAINT = "maintenance"


class Room(BaseModel):
    id: str
    floor: int
    number: str
    room_type: RoomType
    status: RoomStatus
    guests: int = 0
    stay_nights: int = 1
    vip: bool = False
    special_request: Optional[str] = None
    checkout_hour: Optional[float] = None  # hotel-clock hours, e.g. 11.0
    checkin_hour: Optional[float] = None
    guest_name: Optional[str] = None
    incoming_guest: Optional[str] = None
    assigned_staff_id: Optional[str] = None
    task_started_hour: Optional[float] = None
    estimated_minutes: float = 25.0
    actual_minutes: float = 0.0
    last_cleaned_hour: Optional[float] = None
    notes: str = ""
    duration_multiplier: float = 1.0


class Staff(BaseModel):
    id: str
    name: str
    role: StaffRole
    floor: int
    seniority: StaffSeniority = StaffSeniority.JUNIOR
    available: bool = True
    current_room_id: Optional[str] = None
    tasks_completed: int = 0
    minutes_worked: float = 0.0
    quality_score: float = 0.92  # 0-1, inspection pass rate proxy
    speed_factor: float = 1.0  # <1 faster


class Task(BaseModel):
    id: str
    room_id: str
    kind: TaskKind
    staff_id: Optional[str] = None
    priority: float = 0.0
    created_hour: float = 0.0
    started_hour: Optional[float] = None
    eta_minutes: float = 25.0
    delayed: bool = False
    anomaly: bool = False
    anomaly_score: float = 0.0
    done: bool = False


class GuestNotice(BaseModel):
    id: str
    guest_name: str
    room_id: Optional[str] = None
    kind: NotificationKind
    message: str
    hour: float
    read: bool = False


class AssignmentRow(BaseModel):
    staff_id: str
    staff_name: str
    room_id: str
    cost: float
    reason: str


class OpsEvent(BaseModel):
    id: str
    hour: float
    kind: EventKind
    message: str


class HotelSnapshot(BaseModel):
    hotel_hour: float
    day_label: str
    rooms: list[Room]
    staff: list[Staff]
    tasks: list[Task]
    notices: list[GuestNotice]
    assignments: list[AssignmentRow] = Field(default_factory=list)
    kpis: dict = Field(default_factory=dict)
    analytics: dict = Field(default_factory=dict)
    delayed_tasks: list[str] = Field(default_factory=list)
    anomalies: list[dict] = Field(default_factory=list)
    events: list[OpsEvent] = Field(default_factory=list)