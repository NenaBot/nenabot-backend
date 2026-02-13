from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class Job:
    id: str
    options: Optional[Dict[str, Any]] = None
    path: Optional[str] = None
    log: Optional[str] = None
    measurements: List[Any] = field(default_factory=list)
    path_image: Optional[str] = None
    last_point_processed: int = 0
    error: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class ResultSummary:
    id: str
    pack_id: str
    started_at: datetime
    finished_at: Optional[datetime]
    decision: str
    dms_ppb: Optional[float] = None
    dms_compound: Optional[str] = None
    image_path: Optional[str] = None
