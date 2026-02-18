from __future__ import annotations

import base64

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import StreamingResponse

from app.dependencies import get_orchestrator
from app.domain.models import Waypoint
from app.schemas import (
    CornerSchema,
    Health,
    Job,
    JobCreateRequest,
    MeasurementSchema,
    PathItem,
    PathRequest,
    PathResponse,
    Profile,
    Status,
    WaypointSchema,
)
from app.services.orchestrator import OrchestratorService

router = APIRouter()


@router.get("/health", response_model=Health)
def health(svc: OrchestratorService = Depends(get_orchestrator)) -> Health:
    data = svc.health()
    return Health(**data)


@router.get("/status", response_model=Status)
def status_route(svc: OrchestratorService = Depends(get_orchestrator)) -> Status:
    return Status(state=svc.status())


@router.get("/jobs", response_model=list[Job])
def list_jobs(svc: OrchestratorService = Depends(get_orchestrator)) -> list[Job]:
    jobs = svc.list_jobs()
    return [_to_job(job) for job in jobs]


@router.get("/jobs/latest", response_model=Job)
def latest_job(svc: OrchestratorService = Depends(get_orchestrator)) -> Job:
    job = svc.latest_job()
    if not job:
        raise HTTPException(status_code=404, detail="No jobs yet")
    return _to_job(job)


@router.get("/jobs/{job_id}", response_model=Job)
def get_job(job_id: str, svc: OrchestratorService = Depends(get_orchestrator)) -> Job:
    job = svc.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return _to_job(job)


@router.get("/jobs/{job_id}/image")
def get_job_image(job_id: str, svc: OrchestratorService = Depends(get_orchestrator)):
    """Return the annotated overlay JPEG for a job."""
    img = svc.get_job_image(job_id)
    if not img:
        raise HTTPException(status_code=404, detail="No image for this job")
    return Response(content=img, media_type="image/jpeg")


@router.post("/jobs", response_model=Job, status_code=status.HTTP_201_CREATED)
def create_job(
    payload: JobCreateRequest,
    svc: OrchestratorService = Depends(get_orchestrator),
) -> Job:
    waypoints = [Waypoint(x=w.x, y=w.y, z=w.z, r=w.r) for w in payload.path]

    # Decode optional snapshot image
    image_bytes: bytes | None = None
    if payload.image_base64:
        try:
            image_bytes = base64.b64decode(payload.image_base64)
        except Exception:
            pass

    job = svc.create_job(
        path=waypoints,
        dry_run=payload.dry_run,
        options=payload.options,
        image_bytes=image_bytes,
    )
    svc.run_job(job.id)
    return _to_job(job)


@router.delete("/jobs/{job_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def delete_job(job_id: str, svc: OrchestratorService = Depends(get_orchestrator)) -> Response:
    ok = svc.delete_job(job_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Job not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/robot/stop", status_code=status.HTTP_200_OK)
def stop_robot(svc: OrchestratorService = Depends(get_orchestrator)):
    stopped = svc.stop_job()
    return {"stopped": stopped}


@router.get("/profiles", response_model=list[Profile])
def profiles(svc: OrchestratorService = Depends(get_orchestrator)) -> list[Profile]:
    return [Profile(**profile) for profile in svc.profiles()]


@router.get("/profiles/default", response_model=Profile)
def default_profile(svc: OrchestratorService = Depends(get_orchestrator)) -> Profile:
    return Profile(**svc.default_profile())


@router.get("/streams/camera/feed")
async def camera_feed(svc: OrchestratorService = Depends(get_orchestrator)):
    """MJPEG live camera feed. Connect via <img src="..."> or fetch API."""
    return StreamingResponse(
        svc.camera_vision.stream_camera(),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


@router.post("/streams/camera", status_code=status.HTTP_201_CREATED)
def start_camera_stream(svc: OrchestratorService = Depends(get_orchestrator)):
    """Start the camera stream (no-op — stream is started on first GET to /feed)."""
    return {"streaming": True}


@router.delete("/streams/camera", status_code=status.HTTP_204_NO_CONTENT)
def stop_camera_stream(svc: OrchestratorService = Depends(get_orchestrator)):
    """Stop the camera stream."""
    svc.camera_vision.stop_camera_stream()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/streams/detection/feed")
async def detection_feed(svc: OrchestratorService = Depends(get_orchestrator)):
    """MJPEG detection-overlay feed. Shows ArUco markers and battery contour."""
    return StreamingResponse(
        svc.camera_vision.stream_detection(),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


@router.post("/streams/detection", status_code=status.HTTP_201_CREATED)
def start_detection_stream(svc: OrchestratorService = Depends(get_orchestrator)):
    """Start the detection stream (no-op — stream is started on first GET to /feed)."""
    return {"streaming": True}


@router.delete("/streams/detection", status_code=status.HTTP_204_NO_CONTENT)
def stop_detection_stream(svc: OrchestratorService = Depends(get_orchestrator)):
    """Stop the detection stream."""
    svc.camera_vision.stop_detection_stream()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/paths", response_model=PathResponse, status_code=status.HTTP_201_CREATED)
def create_path(
    payload: PathRequest,
    svc: OrchestratorService = Depends(get_orchestrator),
) -> PathResponse:
    result = svc.detect_path()
    return PathResponse(
        ok=result.ok,
        detections=[
            PathItem(
                corners=[CornerSchema(x=c.x, y=c.y) for c in d.corners],
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
        error=result.error,
        options=payload.options,
    )


def _to_job(job) -> Job:
    return Job(
        id=job.id,
        options=job.options,
        path=[WaypointSchema(x=w.x, y=w.y, z=w.z, r=w.r) for w in job.path],
        dry_run=job.dry_run,
        log=job.log,
        measurements=[
            MeasurementSchema(
                waypoint_index=m.waypoint_index,
                waypoint=WaypointSchema(x=m.waypoint.x, y=m.waypoint.y, z=m.waypoint.z, r=m.waypoint.r),
                scan_result=m.scan_result,
                simulated=m.simulated,
                timestamp=m.timestamp,
            )
            for m in job.measurements
        ],
        path_image=job.path_image,
        status={
            "state": job.state,
            "lastPointProcessed": job.last_point_processed,
            "error": job.error,
        },
    )
