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
    pixel_x: float | None = Field(None, alias="pixelX")
    pixel_y: float | None = Field(None, alias="pixelY")
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
    measurements: list[MeasurementSchema] = Field(default_factory=list)
    status: JobStatusState = Field(default_factory=JobStatusState)

    model_config = {"populate_by_name": True}


# ---- Health / Status / Profile ----


class ComponentHealth(BaseModel):
    status: str
    error: str | None = None


class Health(BaseModel):
    status: str
    uptime_s: float = Field(0.0, alias="uptimeSeconds")
    robot: ComponentHealth
    camera: ComponentHealth
    dms: ComponentHealth

    model_config = {"populate_by_name": True}


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


class PathCheckRequest(BaseModel):
    waypoints: list[PixelPointSchema] = Field(default_factory=list)


class PathCheckResponse(BaseModel):
    path: list[PixelPointSchema] = Field(default_factory=list)


class PathItem(BaseModel):
    corners: list[CornerSchema] = Field(default_factory=list)
    width_mm: float = 0.0
    height_mm: float = 0.0
    center_x: float = 0.0
    center_y: float = 0.0


class MarkerCornersSchema(BaseModel):
    corners: list[CornerSchema] = Field(default_factory=list)


class PathResponse(BaseModel):
    ok: bool
    detections: list[PathItem] = Field(default_factory=list)
    image_base64: str | None = Field(None, description="JPEG image as base64 string")
    pixels_per_mm: float | None = Field(None, alias="pixelsPerMm")
    marker_count: int = Field(0, alias="markerCount")
    marker_corners: list[MarkerCornersSchema] = Field(
        default_factory=list,
        alias="markerCorners",
    )
    calibration: CalibrationResponse | None = None
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


# ---- Pixel point (canvas coordinates) ----


class PixelPointSchema(BaseModel):
    """A point in canvas/pixel coordinates."""

    x: float
    y: float


# ---- Calibration ----


class CalibrationResponse(BaseModel):
    """Returned by POST /paths to confirm calibration was captured."""

    calibrated: bool = False
    robot_start: WaypointSchema | None = Field(None, alias="robotStart")
    canvas_start: PixelPointSchema | None = Field(None, alias="canvasStart")
    pixels_per_mm: float | None = Field(None, alias="pixelsPerMm")

    model_config = {"populate_by_name": True}


# ---- SSE Job Events ----


class JobEvent(BaseModel):
    """Payload for server-sent events on GET /jobs/{id}/events."""

    type: str  # job:started, job:waypoint_started, job:waypoint_completed, job:completed, job:failed, job:stopped, job:snapshot
    job_id: str = Field(alias="jobId")
    state: str
    last_point_processed: int = Field(0, alias="lastPointProcessed")
    total_points: int = Field(0, alias="totalPoints")
    measurement: MeasurementSchema | None = None
    error: str | None = None
    timestamp: str | None = None

    model_config = {"populate_by_name": True}


# ---- Job creation request ----


class JobCreateRequest(BaseModel):
    path: list[PixelPointSchema] = Field(default_factory=list)
    work_z: float = Field(0.0, alias="workZ")
    work_r: float = Field(0.0, alias="workR")
    dry_run: bool = Field(False, alias="dryRun")
    options: dict[str, Any] | None = None
    image_base64: str | None = Field(
        None,
        alias="imageBase64",
        description="Base64-encoded JPEG snapshot to store with the job",
    )

    model_config = {"populate_by_name": True}
