from __future__ import annotations

import asyncio
import base64
import queue
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
        ok=result.ok,
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


@router.post("/path/populate", status_code=status.HTTP_200_OK)
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
    populated = svc.populate_pixel_path_from_batteries(
        batteries,
        payload.measuring_points_per_cm,
    )

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
