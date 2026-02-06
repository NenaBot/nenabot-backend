from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Job:
    id: str
    pack_id: str
    state: str
    step: str
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
