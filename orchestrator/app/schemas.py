from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class JobStatusState(BaseModel):
    last_point_processed: int = Field(0, alias="lastPointProcessed")
    error: Optional[str] = None


class Job(BaseModel):
    id: str
    options: Optional[Dict[str, Any]] = None
    path: Optional[str] = None
    log: Optional[str] = None
    measurements: List[Any] = Field(default_factory=list)
    path_image: Optional[str] = Field(None, alias="path-image")
    status: JobStatusState = Field(default_factory=JobStatusState)




class Health(BaseModel):
    status: str
    robot: str
    camera: str
    vision: str
    dms: str


class Status(BaseModel):
    state: str


class Profile(BaseModel):
    name: str
    description: Optional[str] = None




class PathRequest(BaseModel):
    options: Optional[Dict[str, Any]] = None


class PathResponse(BaseModel):
    path: str
    options: Optional[Dict[str, Any]] = None


class StreamStatus(BaseModel):
    status: str
    started_at: Optional[datetime] = Field(None, alias="startedAt")


class JobCreateRequest(BaseModel):
    options: Optional[Dict[str, Any]] = None
    path: Optional[str] = None
