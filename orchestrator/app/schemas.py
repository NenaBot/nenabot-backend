from __future__ import annotations

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
    dms: str


class Status(BaseModel):
    state: str


class Profile(BaseModel):
    name: str
    description: Optional[str] = None




class CornerSchema(BaseModel):
    x: float
    y: float


class PathRequest(BaseModel):
    options: Optional[Dict[str, Any]] = None


class PathResponse(BaseModel):
    ok: bool
    corners: List[CornerSchema] = Field(default_factory=list)
    width_mm: float = 0.0
    height_mm: float = 0.0
    center_x: float = 0.0
    center_y: float = 0.0
    confidence: float = 0.0
    image_base64: Optional[str] = Field(None, description="JPEG image as base64 string")
    error: Optional[str] = None
    options: Optional[Dict[str, Any]] = None


class JobCreateRequest(BaseModel):
    options: Optional[Dict[str, Any]] = None
    path: Optional[str] = None
