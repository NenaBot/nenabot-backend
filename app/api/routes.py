from __future__ import annotations

import asyncio
import base64
import json
import logging
import queue
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import StreamingResponse

from app.dependencies import get_orchestrator
from app.domain.models import Job as DomainJob
from app.domain.models import Waypoint
from app.schemas import (
    CalibrationActionRequest,
    CalibrationFlowResponse,
    ComponentHealth,
    CornerSchema,
    Health,
    Job,
    JobCreateRequest,
    MeasurementSchema,
    PathItem,
    PathPopulateRequest,
    PathPopulateResponse,
    PathRequest,
    PathResponse,
    PopulatedPathPointSchema,
    Profile,
    RobotMoveRequest,
    RobotMoveResponse,
    RobotPoseResponse,
    Status,
    WaypointSchema,
)
from app.services.orchestrator import OrchestratorService

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/health", response_model=Health)
def health(svc: OrchestratorService = Depends(get_orchestrator)) -> Health:
    data = svc.health()
    return Health(
        status=data["status"],
        uptime_s=data["uptime_s"],
        robot=ComponentHealth(**data["robot"]),
        camera=ComponentHealth(**data["camera"]),
        ionvision=ComponentHealth(**data["ionvision"]),
    )


@router.get("/status", response_model=Status)
def status_route(svc: OrchestratorService = Depends(get_orchestrator)) -> Status:
    return Status(**svc.status())


@router.get("/job", response_model=list[Job])
def list_jobs(svc: OrchestratorService = Depends(get_orchestrator)) -> list[Job]:
    return [_to_job(job) for job in svc.list_jobs()]


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
    image = svc.get_job_image(job_id)
    if not image:
        raise HTTPException(status_code=404, detail="No image for this job")
    return Response(content=image, media_type="image/jpeg")


@router.post("/job", response_model=Job, status_code=status.HTTP_201_CREATED)
def create_job(
    payload: JobCreateRequest,
    svc: OrchestratorService = Depends(get_orchestrator),
) -> Job:
    if not svc.is_calibrated:
        raise HTTPException(
            status_code=409,
            detail="Not calibrated — complete POST /calibration first",
        )

    pixel_points = [(point.pixel_x, point.pixel_y) for point in payload.path]
    robot_waypoints: list[Waypoint] = []
    for point, (pixel_x, pixel_y) in zip(payload.path, pixel_points):
        waypoint = svc.pixel_to_robot(pixel_x, pixel_y, payload.work_z, payload.work_r)
        waypoint.index = point.index
        waypoint.battery_nr = point.battery_nr
        waypoint.corner_index = point.corner_index
        waypoint.measurement_index = point.measurement_index
        robot_waypoints.append(waypoint)

    try:
        svc.validate_job_waypoints(robot_waypoints, dry_run=payload.dry_run)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    image_bytes: bytes | None = None
    if payload.image_base64:
        try:
            image_bytes = base64.b64decode(payload.image_base64)
        except Exception:  # noqa: S110
            image_bytes = None

    job = svc.create_job(
        path=robot_waypoints,
        dry_run=payload.dry_run,
        options=payload.options,
        image_bytes=image_bytes,
        starting_point=svc.calibration_robot_start,
        pixel_path=pixel_points,
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
    if not svc.delete_job(job_id):
        raise HTTPException(status_code=404, detail="Job not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/robot/stop", status_code=status.HTTP_200_OK)
def stop_robot(svc: OrchestratorService = Depends(get_orchestrator)) -> dict:
    return {"stopped": svc.stop_job()}


@router.post("/robot/move", response_model=RobotMoveResponse)
def robot_move(
    payload: RobotMoveRequest,
    svc: OrchestratorService = Depends(get_orchestrator),
) -> RobotMoveResponse:
    result = svc.move_robot(payload.x, payload.y, payload.z, payload.r)
    return RobotMoveResponse(ok=result.ok, error=result.error)


@router.get("/robot/pose", response_model=RobotPoseResponse)
def robot_pose(
    svc: OrchestratorService = Depends(get_orchestrator),
) -> RobotPoseResponse:
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
    return StreamingResponse(
        svc.camera_vision.stream_camera(),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


@router.get("/stream/detection/feed")
async def detection_feed(
    svc: OrchestratorService = Depends(get_orchestrator),
) -> StreamingResponse:
    return StreamingResponse(
        svc.camera_vision.stream_detection(),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


@router.post(
    "/path/detect",
    response_model=PathResponse,
    status_code=status.HTTP_201_CREATED,
)
def detect_path(
    payload: PathRequest,
    svc: OrchestratorService = Depends(get_orchestrator),
) -> PathResponse:
    logger.info("Path detect start options=%s", payload.options)
    result = svc.detect_path()
    logger.info(
        "Path detect done ok=%s detections=%d error=%s",
        result.ok,
        len(result.detections),
        result.error,
    )
    return PathResponse(
        request_succeeded=result.ok,
        detections=[
            PathItem(
                corners=[
                    CornerSchema(pixel_x=corner.x, pixel_y=corner.y)
                    for corner in detection.corners
                ],
                width_mm=detection.width_mm,
                height_mm=detection.height_mm,
                center_x=detection.center_x,
                center_y=detection.center_y,
                confidence=detection.confidence,
            )
            for detection in result.detections
        ],
        image_base64=result.image_base64,
        error=result.error,
        options=payload.options,
    )


@router.post("/calibration", response_model=CalibrationFlowResponse)
def calibration(
    payload: CalibrationActionRequest,
    svc: OrchestratorService = Depends(get_orchestrator),
) -> CalibrationFlowResponse:
    return CalibrationFlowResponse(**svc.calibration_action(payload.action))


async def _job_events_stream(job_id: str, svc: OrchestratorService):
    job = svc.get_job(job_id)
    if not job:
        logger.warning("SSE stream requested for missing job job_id=%s", job_id)
        return

    subscriber = svc.subscribe(job_id)
    try:
        snapshot = {
            "type": "job:snapshot",
            "jobId": job_id,
            "state": job.state,
            "lastPointProcessed": job.last_point_processed,
            "totalPoints": len(job.path),
            "error": job.error,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        logger.info(
            "SSE send snapshot job_id=%s state=%s points=%d/%d",
            job_id,
            job.state,
            job.last_point_processed,
            len(job.path),
        )
        yield _format_sse("job:snapshot", snapshot)

        if job.state in ("completed", "failed", "stopped"):
            return

        while True:
            try:
                event = subscriber.get_nowait()
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

            logger.info(
                "SSE send event=%s job_id=%s state=%s points=%s/%s",
                event_type,
                payload.get("jobId"),
                payload.get("state"),
                payload.get("lastPointProcessed"),
                payload.get("totalPoints"),
            )
            yield _format_sse(event_type, payload)
            if event.get("state") in ("completed", "failed", "stopped"):
                logger.info(
                    "SSE stream closing on terminal state job_id=%s state=%s",
                    job_id,
                    event.get("state"),
                )
                return
    finally:
        svc.unsubscribe(job_id, subscriber)
        logger.info("SSE unsubscribed job_id=%s", job_id)


@router.get(
    "/job/{job_id}/events",
    summary="Stream job progress (SSE)",
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
) -> StreamingResponse:
    if not svc.get_job(job_id):
        raise HTTPException(status_code=404, detail="Job not found")
    return StreamingResponse(
        _job_events_stream(job_id, svc),
        media_type="text/event-stream",
    )


@router.post(
    "/path/populate",
    response_model=PathPopulateResponse,
    status_code=status.HTTP_200_OK,
)
def populate_path(
    payload: PathPopulateRequest,
    svc: OrchestratorService = Depends(get_orchestrator),
) -> PathPopulateResponse:
    logger.info(
        "Path populate start batteries=%d measuring_points_per_cm=%.3f",
        len(payload.batteries),
        payload.measuring_points_per_cm,
    )
    if not svc.is_calibrated:
        logger.warning("Path populate rejected: not calibrated")
        raise HTTPException(
            status_code=409,
            detail="Not calibrated — complete POST /calibration first",
        )

    batteries = [
        [(corner.pixel_x, corner.pixel_y) for corner in battery.corners]
        for battery in payload.batteries
    ]
    try:
        populated = svc.populate_pixel_path_from_batteries(
            batteries,
            payload.measuring_points_per_cm,
        )
    except ValueError as exc:
        logger.warning("Path populate validation error: %s", exc)
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        logger.warning("Path populate runtime error: %s", exc)
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    logger.info("Path populate done points=%d", len(populated))

    return PathPopulateResponse(
        path=[PopulatedPathPointSchema(**point) for point in populated]
    )


def _format_sse(event_name: str, payload: dict) -> bytes:
    encoded = json.dumps(payload, separators=(",", ":"))
    return f"event: {event_name}\ndata: {encoded}\n\n".encode("utf-8")


def _to_job(job: DomainJob) -> Job:
    return Job(
        id=job.id,
        options=job.options,
        path=[
            WaypointSchema(
                robot_x=waypoint.x,
                robot_y=waypoint.y,
                robot_z=waypoint.z,
                robot_r=waypoint.r,
                index=waypoint.index,
                battery_nr=waypoint.battery_nr,
                corner_index=waypoint.corner_index,
                measurement_index=waypoint.measurement_index,
            )
            for waypoint in job.path
        ],
        dry_run=job.dry_run,
        measurements=[
            MeasurementSchema(
                waypoint_index=measurement.waypoint_index,
                waypoint=WaypointSchema(
                    robot_x=measurement.waypoint.x,
                    robot_y=measurement.waypoint.y,
                    robot_z=measurement.waypoint.z,
                    robot_r=measurement.waypoint.r,
                    index=measurement.waypoint.index,
                    battery_nr=measurement.waypoint.battery_nr,
                    corner_index=measurement.waypoint.corner_index,
                    measurement_index=measurement.waypoint.measurement_index,
                ),
                pixel_x=measurement.pixel_x,
                pixel_y=measurement.pixel_y,
                scan_result=measurement.scan_result,
                simulated=measurement.simulated,
                timestamp=measurement.timestamp,
            )
            for measurement in job.measurements
        ],
        status={
            "state": job.state,
            "lastPointProcessed": job.last_point_processed,
            "error": job.error,
        },
    )
