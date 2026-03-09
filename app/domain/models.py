from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class Waypoint:
    x: float
    y: float
    z: float = 0.0
    r: float = 0.0


@dataclass
class Measurement:
    waypoint_index: int
    waypoint: Waypoint
    pixel_x: float | None = None
    pixel_y: float | None = None
    scan_result: dict[str, Any] | None = None
    simulated: bool = False
    timestamp: str | None = None


@dataclass
class Job:
    id: str
    options: dict[str, Any] | None = None
    path: list[Waypoint] = field(default_factory=list)
    dry_run: bool = False
    log: str | None = None
    measurements: list[Measurement] = field(default_factory=list)
    path_image: str | None = None
    state: str = "created"  # created | running | completed | failed | stopped
    last_point_processed: int = 0
    error: str | None = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
