from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class InspectionJobRequest(BaseModel):
    pack_id: str = Field(..., alias="packId")
    options: Optional[Dict[str, Any]] = None


class JobCreated(BaseModel):
    id: str


class JobStatus(BaseModel):
    id: str
    state: str
    step: str
    updated_at: datetime = Field(..., alias="updatedAt")


class Health(BaseModel):
    status: str
    robot: str
    camera: str
    vision: str
    dms: str


class InspectionResultSummary(BaseModel):
    id: str
    pack_id: str = Field(..., alias="packId")
    started_at: datetime = Field(..., alias="startedAt")
    finished_at: Optional[datetime] = Field(None, alias="finishedAt")
    decision: str
    dms_ppb: Optional[float] = Field(None, alias="dmsPpb")
    dms_compound: Optional[str] = Field(None, alias="dmsCompound")
    image_path: Optional[str] = Field(None, alias="imagePath")
