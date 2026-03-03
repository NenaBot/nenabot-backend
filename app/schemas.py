from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ---- Waypoint / Measurement ----

class WaypointSchema(BaseModel):
    x: float
    y: float
    z: float = 0.0
    r: float = 0.0


class MeasurementSchema(BaseModel):
    waypoint_index: int = Field(alias="waypointIndex")
    waypoint: WaypointSchema
    scan_result: Optional[Dict[str, Any]] = Field(None, alias="scanResult")
    simulated: bool = False
    timestamp: Optional[str] = None

    model_config = {"populate_by_name": True}


# ---- Job ----

class JobStatusState(BaseModel):
    state: str = "created"
    last_point_processed: int = Field(0, alias="lastPointProcessed")
    error: Optional[str] = None

    model_config = {"populate_by_name": True}


class Job(BaseModel):
    id: str
    options: Optional[Dict[str, Any]] = None
    path: List[WaypointSchema] = Field(default_factory=list)
    dry_run: bool = Field(False, alias="dryRun")
    log: Optional[str] = None
    measurements: List[MeasurementSchema] = Field(default_factory=list)
    path_image: Optional[str] = Field(None, alias="path-image")
    status: JobStatusState = Field(default_factory=JobStatusState)

    model_config = {"populate_by_name": True}


# ---- Health / Status / Profile ----

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


# ---- Path detection ----

class CornerSchema(BaseModel):
    x: float
    y: float


class PathRequest(BaseModel):
    options: Optional[Dict[str, Any]] = None


class PathItem(BaseModel):
    corners: List[CornerSchema] = Field(default_factory=list)
    width_mm: float = 0.0
    height_mm: float = 0.0
    center_x: float = 0.0
    center_y: float = 0.0
    confidence: float = 0.0


class MarkerCornersSchema(BaseModel):
    corners: List[CornerSchema] = Field(default_factory=list)


class PathResponse(BaseModel):
    ok: bool
    detections: List[PathItem] = Field(default_factory=list)
    image_base64: Optional[str] = Field(None, description="JPEG image as base64 string")
    pixels_per_mm: Optional[float] = Field(None, alias="pixelsPerMm")
    marker_count: int = Field(0, alias="markerCount")
    marker_corners: List[MarkerCornersSchema] = Field(default_factory=list, alias="markerCorners")
    error: Optional[str] = None
    options: Optional[Dict[str, Any]] = None

    model_config = {"populate_by_name": True}


# ---- Robot pose ----

class RobotPoseResponse(BaseModel):
    ok: bool
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    r: float = 0.0
    j1: float = 0.0
    j2: float = 0.0
    j3: float = 0.0
    j4: float = 0.0
    error: Optional[str] = None


# ---- Robot move request ----

class RobotMoveRequest(BaseModel):
    x: float
    y: float
    z: float = 0.0
    r: float = 0.0


class RobotMoveResponse(BaseModel):
    ok: bool
    error: Optional[str] = None


# ---- Job creation request ----

class JobCreateRequest(BaseModel):
    path: List[WaypointSchema] = Field(default_factory=list)
    dry_run: bool = Field(False, alias="dryRun")
    options: Optional[Dict[str, Any]] = None
    image_base64: Optional[str] = Field(
        None,
        alias="imageBase64",
        description="Base64-encoded JPEG snapshot to store with the job",
    )
    starting_point: Optional[WaypointSchema] = Field(
        None,
        alias="startingPoint",
        description="Robot starting position — prepended to path so the arm moves there first",
    )

    model_config = {"populate_by_name": True}
