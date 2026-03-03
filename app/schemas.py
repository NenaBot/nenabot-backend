from __future__ import annotations

from typing import Any

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
    scan_result: dict[str, Any] | None = Field(None, alias="scanResult")
    simulated: bool = False
    timestamp: str | None = None

    model_config = {"populate_by_name": True}


# ---- Job ----

class JobStatusState(BaseModel):
    state: str = "created"
    last_point_processed: int = Field(0, alias="lastPointProcessed")
    error: str | None = None

    model_config = {"populate_by_name": True}


class Job(BaseModel):
    id: str
    options: dict[str, Any] | None = None
    path: list[WaypointSchema] = Field(default_factory=list)
    dry_run: bool = Field(False, alias="dryRun")
    log: str | None = None
    measurements: list[MeasurementSchema] = Field(default_factory=list)
    path_image: str | None = Field(None, alias="path-image")
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
    description: str | None = None


# ---- Path detection ----

class CornerSchema(BaseModel):
    x: float
    y: float


class PathRequest(BaseModel):
    options: dict[str, Any] | None = None


class PathItem(BaseModel):
    corners: list[CornerSchema] = Field(default_factory=list)
    width_mm: float = 0.0
    height_mm: float = 0.0
    center_x: float = 0.0
    center_y: float = 0.0
    confidence: float = 0.0


class MarkerCornersSchema(BaseModel):
    corners: list[CornerSchema] = Field(default_factory=list)


class PathResponse(BaseModel):
    ok: bool
    detections: list[PathItem] = Field(default_factory=list)
    image_base64: str | None = Field(None, description="JPEG image as base64 string")
    pixels_per_mm: float | None = Field(None, alias="pixelsPerMm")
    marker_count: int = Field(0, alias="markerCount")
    marker_corners: list[MarkerCornersSchema] = Field(
        default_factory=list, alias="markerCorners",
    )
    error: str | None = None
    options: dict[str, Any] | None = None

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
    error: str | None = None


# ---- Robot move request ----

class RobotMoveRequest(BaseModel):
    x: float
    y: float
    z: float = 0.0
    r: float = 0.0


class RobotMoveResponse(BaseModel):
    ok: bool
    error: str | None = None


# ---- Job creation request ----

class JobCreateRequest(BaseModel):
    path: list[WaypointSchema] = Field(default_factory=list)
    dry_run: bool = Field(False, alias="dryRun")
    options: dict[str, Any] | None = None
    image_base64: str | None = Field(
        None,
        alias="imageBase64",
        description=(
            "Base64-encoded JPEG snapshot to store with the job"
        ),
    )
    starting_point: WaypointSchema | None = Field(
        None,
        alias="startingPoint",
        description=(
            "Robot starting position — prepended to path "
            "so the arm moves there first"
        ),
    )

    model_config = {"populate_by_name": True}
