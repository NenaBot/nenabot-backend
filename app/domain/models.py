from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


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
    scan_result: Optional[Dict[str, Any]] = None
    simulated: bool = False
    timestamp: Optional[str] = None


@dataclass
class Job:
    id: str
    options: Optional[Dict[str, Any]] = None
    path: List[Waypoint] = field(default_factory=list)
    dry_run: bool = False
    log: Optional[str] = None
    measurements: List[Measurement] = field(default_factory=list)
    path_image: Optional[str] = None
    state: str = "created"  # created | running | completed | failed | stopped
    last_point_processed: int = 0
    error: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
