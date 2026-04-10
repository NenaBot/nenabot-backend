from __future__ import annotations

import asyncio
import base64
import queue
import threading
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import StreamingResponse
from fastapi.sse import EventSourceResponse, ServerSentEvent

from app.dependencies import get_orchestrator
from app.domain.models import Job as DomainJob
from app.domain.models import Waypoint
from app.schemas import (
    CalibrationResponse,
    ComponentHealth,
    CornerSchema,
    Health,
    Job,
    JobCreateRequest,
    MarkerCornersSchema,
    MeasurementSchema,
    PathItem,
    PathPopulateRequest,
    PathPopulateResponse,
    PathRequest,
    PathResponse,
    PopulatedPathPointSchema,
    PixelPointSchema,
    Profile,
    RobotMoveRequest,
    RobotMoveResponse,
    RobotPoseResponse,
    Status,
    WaypointSchema,
)
from app.services.orchestrator import OrchestratorService

router = APIRouter()
_reachability_stop_event = threading.Event()


@router.get("/health", response_model=Health)
def health(svc: OrchestratorService = Depends(get_orchestrator)) -> Health:
    data = svc.health()
    return Health(
        status=data["status"],
        uptime_s=data["uptime_s"],
        robot=ComponentHealth(**data["robot"]),
        camera=ComponentHealth(**data["camera"]),
        dms=ComponentHealth(**data["dms"]),
    )


@router.get("/status", response_model=Status)
def status_route(svc: OrchestratorService = Depends(get_orchestrator)) -> Status:
    return Status(state=svc.status())


@router.get("/job", response_model=list[Job])
def list_jobs(svc: OrchestratorService = Depends(get_orchestrator)) -> list[Job]:
    jobs = svc.list_jobs()
    return [_to_job(job) for job in jobs]


@router.get("/job/latest", response_model=Job)
def latest_job(svc: OrchestratorService = Depends(get_orchestrator)) -> Job:
    job = svc.latest_job()
    if not job:
        raise HTTPException(status_code=404, detail="No jobs yet")
    return _to_job(job)


@router.get("/job/{job_id}", response_model=Job)
def get_job(job_id: str, svc: OrchestratorService = Depends(get_orchestrator)) -> Job:
    job = svc.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return _to_job(job)


@router.get("/job/{job_id}/image")
def get_job_image(
    job_id: str,
    svc: OrchestratorService = Depends(get_orchestrator),
) -> Response:
    """Return the clean base JPEG for a job (no overlay annotations)."""
    img = svc.get_job_image(job_id)
    if not img:
        raise HTTPException(status_code=404, detail="No image for this job")
    return Response(content=img, media_type="image/jpeg")


@router.post("/job", response_model=Job, status_code=status.HTTP_201_CREATED)
def create_job(
    payload: JobCreateRequest,
    svc: OrchestratorService = Depends(get_orchestrator),
) -> Job:
    if not svc.is_calibrated:
        raise HTTPException(
            status_code=409,
            detail="Not calibrated — call POST /path/detect first "
            "(with robot arm at starting position)",
        )

    pixel_points = [
        (
            p.pixel_x,
            p.pixel_y,
        )
        for p in payload.path
    ]

    robot_waypoints: list[Waypoint] = []
    for point, (pixel_x, pixel_y) in zip(payload.path, pixel_points):
        wp = svc.pixel_to_robot(pixel_x, pixel_y, payload.work_z, payload.work_r)
        wp.index = point.index
        wp.battery_nr = point.battery_nr
        wp.corner_index = point.corner_index
        wp.measurement_index = point.measurement_index
        robot_waypoints.append(wp)

    # Pixel coords for measurement points (one per measurement waypoint)
    pixel_path: list[tuple[float, float]] = [
        (pixel_x, pixel_y) for pixel_x, pixel_y in pixel_points
    ]

    # Starting position for return-to-start (captured during POST /path/detect)
    starting_wp = svc.calibration_robot_start

    # Decode optional snapshot image
    image_bytes: bytes | None = None
    if payload.image_base64:
        try:
            image_bytes = base64.b64decode(payload.image_base64)
        except Exception:  # noqa: S110
            pass  # — best-effort decode

    job = svc.create_job(
        path=robot_waypoints,
        dry_run=payload.dry_run,
        options=payload.options,
        image_bytes=image_bytes,
        starting_point=starting_wp,
        pixel_path=pixel_path,
    )
    svc.run_job(job.id)
    return _to_job(job)


@router.delete(
    "/job/{job_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
def delete_job(
    job_id: str,
    svc: OrchestratorService = Depends(get_orchestrator),
) -> Response:
    ok = svc.delete_job(job_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Job not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/robot/stop", status_code=status.HTTP_200_OK)
def stop_robot(
    svc: OrchestratorService = Depends(get_orchestrator),
) -> dict:
    stopped = svc.stop_job()
    return {"stopped": stopped}


@router.post("/robot/move", response_model=RobotMoveResponse)
def robot_move(
    payload: RobotMoveRequest,
    svc: OrchestratorService = Depends(get_orchestrator),
) -> RobotMoveResponse:
    """Send the robot to a specific position (for calibration testing)."""
    result = svc.move_robot(payload.x, payload.y, payload.z, payload.r)
    return RobotMoveResponse(ok=result.ok, error=result.error)


@router.get("/robot/pose", response_model=RobotPoseResponse)
def robot_pose(
    svc: OrchestratorService = Depends(get_orchestrator),
) -> RobotPoseResponse:
    """Read the current position of the robot arm."""
    result = svc.get_robot_pose()
    return RobotPoseResponse(
        ok=result.ok,
        x=result.x,
        y=result.y,
        z=result.z,
        r=result.r,
        j1=result.j1,
        j2=result.j2,
        j3=result.j3,
        j4=result.j4,
        error=result.error,
    )


@router.get("/profile", response_model=list[Profile])
def profiles(svc: OrchestratorService = Depends(get_orchestrator)) -> list[Profile]:
    return [Profile(**profile) for profile in svc.profiles()]


@router.get("/profile/default", response_model=Profile)
def default_profile(svc: OrchestratorService = Depends(get_orchestrator)) -> Profile:
    return Profile(**svc.default_profile())


@router.get("/stream/camera/feed")
async def camera_feed(
    svc: OrchestratorService = Depends(get_orchestrator),
) -> StreamingResponse:
    """MJPEG live camera feed. Connect via <img src="..."> or fetch API."""
    return StreamingResponse(
        svc.camera_vision.stream_camera(),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


@router.get("/stream/detection/feed")
async def detection_feed(
    svc: OrchestratorService = Depends(get_orchestrator),
) -> StreamingResponse:
    """MJPEG detection-overlay feed. Shows ArUco markers and battery contour."""
    return StreamingResponse(
        svc.camera_vision.stream_detection(),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


@router.post(
    "/path/detect", response_model=PathResponse, status_code=status.HTTP_201_CREATED
)
def detect_path(
    payload: PathRequest,
    svc: OrchestratorService = Depends(get_orchestrator),
) -> PathResponse:
    result = svc.detect_path()

    # Build calibration summary for the frontend
    cal: CalibrationResponse | None = None
    if svc.is_calibrated:
        rs = svc.calibration_robot_start
        cs = svc.calibration_canvas_start
        cal = CalibrationResponse(
            calibrated=True,
            robot_start=(
                WaypointSchema(robot_x=rs.x, robot_y=rs.y, robot_z=rs.z, robot_r=rs.r)
                if rs
                else None
            ),
            canvas_start=(
                PixelPointSchema(pixel_x=cs[0], pixel_y=cs[1]) if cs else None
            ),
            pixels_per_mm=svc.calibration_pixels_per_mm,
        )

    return PathResponse(
        request_succeeded=result.ok or cal is not None,
        detections=[
            PathItem(
                corners=[CornerSchema(pixel_x=c.x, pixel_y=c.y) for c in d.corners],
                width_mm=d.width_mm,
                height_mm=d.height_mm,
                center_x=d.center_x,
                center_y=d.center_y,
                confidence=d.confidence,
            )
            for d in result.detections
        ],
        image_base64=result.image_base64,
        pixels_per_mm=result.pixels_per_mm,
        marker_count=result.marker_count,
        marker_corners=[
            MarkerCornersSchema(
                corners=[CornerSchema(pixel_x=c.x, pixel_y=c.y) for c in mc.corners]
            )
            for mc in result.marker_corners
        ],
        calibration=cal,
        error=result.error,
        options=payload.options,
    )


_SSE_DESCRIPTION = """\
SSE stream of real-time job progress events.

Connect with an `EventSource` (or any HTTP client that accepts
`text/event-stream`).  The stream behaves as follows:

1. **On connect** — a `job:snapshot` event is sent with the current state so
   late-joining clients are synchronised immediately.
2. **While the job runs** — events are pushed in real-time:
   - `job:started` — job transitioned to *running*
   - `job:waypoint_started` — about to process a waypoint (includes `waypointIndex`)
   - `job:waypoint_completed` — measurement recorded (includes `waypointIndex` and `measurement`)
3. **Terminal event** — one of `job:completed`, `job:failed`, or `job:stopped`.
   The stream closes automatically after a terminal event.

Each SSE message has an `event` field matching the event type and a JSON
`data` field whose shape is described by the **JobEvent** schema.

Multiple clients can subscribe to the same job simultaneously.
"""


@router.get(
    "/job/{job_id}/events",
    response_class=EventSourceResponse,
    summary="Stream job progress (SSE)",
    description=_SSE_DESCRIPTION,
    responses={
        200: {
            "description": "SSE event stream.",
            "content": {
                "text/event-stream": {
                    "schema": {"$ref": "#/components/schemas/JobEvent"},
                },
            },
        },
        404: {"description": "Job not found."},
    },
)
async def job_events(
    job_id: str,
    svc: OrchestratorService = Depends(get_orchestrator),
):
    job = svc.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    q = svc.subscribe(job_id)

    try:
        # Snapshot so late-connecting clients get current state
        yield ServerSentEvent(
            data={
                "type": "job:snapshot",
                "jobId": job_id,
                "state": job.state,
                "lastPointProcessed": job.last_point_processed,
                "totalPoints": len(job.path),
                "error": job.error,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
            event="job:snapshot",
        )

        if job.state in ("completed", "failed", "stopped"):
            return

        while True:
            try:
                event = q.get_nowait()
            except queue.Empty:
                await asyncio.sleep(1)
                continue

            event_type = event.get("type", "job:update")
            payload = {
                "type": event_type,
                "jobId": event.get("job_id"),
                "state": event.get("state"),
                "lastPointProcessed": event.get("last_point_processed", 0),
                "totalPoints": event.get("total_points", 0),
                "error": event.get("error"),
                "timestamp": event.get("timestamp"),
            }
            if event.get("measurement"):
                payload["measurement"] = event["measurement"]
            if "waypoint_index" in event:
                payload["waypointIndex"] = event["waypoint_index"]

            yield ServerSentEvent(data=payload, event=event_type)

            if event.get("state") in ("completed", "failed", "stopped"):
                return
    finally:
        svc.unsubscribe(job_id, q)


@router.post(
    "/path/populate",
    response_model=PathPopulateResponse,
    status_code=status.HTTP_200_OK,
)
def populate_path(
    payload: PathPopulateRequest,
    svc: OrchestratorService = Depends(get_orchestrator),
) -> PathPopulateResponse:
    if not svc.is_calibrated:
        raise HTTPException(
            status_code=409,
            detail="Not calibrated — call POST /path/detect first "
            "(with robot arm at starting position)",
        )

    batteries: list[list[tuple[float, float]]] = [
        [(corner.pixel_x, corner.pixel_y) for corner in battery.corners]
        for battery in payload.batteries
    ]
    try:
        populated = svc.populate_pixel_path_from_batteries(
            batteries,
            payload.measuring_points_per_cm,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return PathPopulateResponse(
        path=[PopulatedPathPointSchema(**point) for point in populated]
    )


def _to_job(job: DomainJob) -> Job:
    return Job(
        id=job.id,
        options=job.options,
        path=[
            WaypointSchema(
                robot_x=w.x,
                robot_y=w.y,
                robot_z=w.z,
                robot_r=w.r,
                index=w.index,
                battery_nr=w.battery_nr,
                corner_index=w.corner_index,
                measurement_index=w.measurement_index,
            )
            for w in job.path
        ],
        dry_run=job.dry_run,
        measurements=[
            MeasurementSchema(
                waypoint_index=m.waypoint_index,
                waypoint=WaypointSchema(
                    robot_x=m.waypoint.x,
                    robot_y=m.waypoint.y,
                    robot_z=m.waypoint.z,
                    robot_r=m.waypoint.r,
                    index=m.waypoint.index,
                    battery_nr=m.waypoint.battery_nr,
                    corner_index=m.waypoint.corner_index,
                    measurement_index=m.waypoint.measurement_index,
                ),
                pixel_x=m.pixel_x,
                pixel_y=m.pixel_y,
                scan_result=m.scan_result,
                simulated=m.simulated,
                timestamp=m.timestamp,
            )
            for m in job.measurements
        ],
        status={
            "state": job.state,
            "lastPointProcessed": job.last_point_processed,
            "error": job.error,
        },
    )


def _sweep_axis_values(start: float, end: float, step_mm: float = 20.0) -> list[float]:
    """Return inclusive axis values from start to end with fixed step size."""
    step = abs(step_mm) if step_mm != 0 else 20.0
    direction = 1.0 if end >= start else -1.0
    delta = step * direction

    values: list[float] = []
    value = float(start)
    while (direction > 0 and value <= end + 1e-9) or (
        direction < 0 and value >= end - 1e-9
    ):
        values.append(round(value, 6))
        value += delta
    return values


def _wait_for_position_interruptible(
    wait_for_position,
    x: float,
    y: float,
    z: float,
    r: float,
    stop_event: threading.Event,
    timeout_s: float,
    check_interval_s: float = 0.2,
):
    """Wait for target pose while periodically honoring stop requests."""
    deadline = time.monotonic() + max(timeout_s, 0.0)
    last_error: str | None = None

    while time.monotonic() <= deadline:
        if stop_event.is_set():
            return None, True, last_error

        remaining = deadline - time.monotonic()
        probe_timeout = max(0.0, min(check_interval_s, remaining))
        arrival = wait_for_position(
            x,
            y,
            z,
            r,
            tolerance_mm=1.0,
            timeout_s=probe_timeout,
            poll_interval_s=min(0.05, check_interval_s),
        )
        if arrival.ok:
            return arrival, False, None
        last_error = arrival.error

    return None, False, last_error


@router.get("/debug/robot/reachability")
@router.post("/debug/robot/reachability")
def debug_robot_reachability(
    x_max: float,
    x_min: float,
    y_max: float,
    y_min: float,
    z_max: float,
    z_min: float,
    step_x: float = 50.0,
    step_y: float = 50.0,
    step_z: float = 10.0,
    r: float = 0.0,
    svc: OrchestratorService = Depends(get_orchestrator),
) -> dict:
    """Temporary endpoint for manual robot reachability checks during development."""
    _reachability_stop_event.clear()

    robot = getattr(svc, "_robot", None)
    if robot is None:
        raise HTTPException(status_code=500, detail="Robot adapter not available")

    reachability_check = getattr(robot, "is_reachable_mm", None)
    if not callable(reachability_check):
        raise HTTPException(
            status_code=500,
            detail="Reachability function is not available on robot adapter",
        )

    wait_for_position = getattr(robot, "wait_for_position", None)
    if not callable(wait_for_position):
        raise HTTPException(
            status_code=500,
            detail="Position wait function is not available on robot adapter",
        )

    x_values = _sweep_axis_values(x_min, x_max, step_mm=step_x)
    y_values = _sweep_axis_values(y_min, y_max, step_mm=step_y)
    z_values = _sweep_axis_values(z_min, z_max, step_mm=step_z)

    checks: list[dict] = []
    total_points = len(x_values) * len(y_values) * len(z_values)

    for y in y_values:
        for x in x_values:
            for z in z_values:
                if _reachability_stop_event.is_set():
                    return {
                        "stoppedEarly": True,
                        "stopReason": "stop_requested",
                        "failedAt": None,
                        "testedPoints": len(checks),
                        "totalPlannedPoints": total_points,
                        "checks": checks,
                    }

                reachable = bool(reachability_check(x, y, z))
                item: dict = {
                    "x": x,
                    "y": y,
                    "z": z,
                    "r": r,
                    "reachable": reachable,
                    "moveAttempted": False,
                    "moveOk": None,
                    "moveError": None,
                }

                if reachable:
                    move_result = svc.move_robot(x, y, z, r)
                    item["moveAttempted"] = True
                    item["moveOk"] = move_result.ok
                    item["moveError"] = move_result.error
                    if move_result.ok:
                        arrival, stop_requested, last_arrival_error = (
                            _wait_for_position_interruptible(
                                wait_for_position,
                                x,
                                y,
                                z,
                                r,
                                _reachability_stop_event,
                                timeout_s=20.0,
                            )
                        )
                        if stop_requested:
                            stop_motion = getattr(robot, "stop", None)
                            if callable(stop_motion):
                                stop_motion()
                            return {
                                "stoppedEarly": True,
                                "stopReason": "stop_requested",
                                "failedAt": None,
                                "testedPoints": len(checks),
                                "totalPlannedPoints": total_points,
                                "checks": checks,
                            }

                        if arrival is None:
                            item["moveOk"] = False
                            error_message = (
                                last_arrival_error or "Timeout waiting for target pose"
                            )
                            item["moveError"] = f"did_not_reach_target: {error_message}"
                        elif not arrival.ok:
                            item["moveOk"] = False
                            item["moveError"] = f"did_not_reach_target: {arrival.error}"
                    checks.append(item)
                    if not item["moveOk"]:
                        return {
                            "stoppedEarly": True,
                            "stopReason": "move_failed",
                            "failedAt": {"x": x, "y": y, "z": z, "r": r},
                            "testedPoints": len(checks),
                            "totalPlannedPoints": total_points,
                            "checks": checks,
                        }
                else:
                    checks.append(item)

    return {
        "stoppedEarly": False,
        "stopReason": None,
        "testedPoints": len(checks),
        "totalPlannedPoints": total_points,
        "checks": checks,
    }


@router.get("/debug/robot/reachability/stop", status_code=status.HTTP_200_OK)
@router.post("/debug/robot/reachability/stop", status_code=status.HTTP_200_OK)
def stop_debug_robot_reachability(
    svc: OrchestratorService = Depends(get_orchestrator),
) -> dict:
    _reachability_stop_event.set()

    robot_stopped = False
    robot = getattr(svc, "_robot", None)
    stop_motion = getattr(robot, "stop", None) if robot is not None else None
    if callable(stop_motion):
        try:
            stop_result = stop_motion()
            robot_stopped = bool(getattr(stop_result, "ok", stop_result))
        except Exception:
            robot_stopped = False

    job_stopped = svc.stop_job()
    return {
        "stopRequested": True,
        "robotStopped": bool(robot_stopped or job_stopped),
    }
