from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import StreamingResponse

from app.schemas import (
    CornerSchema,
    Health,
    Job,
    JobCreateRequest,
    PathItem,
    PathRequest,
    PathResponse,
    Profile,
    Status,
)
from app.services.orchestrator import OrchestratorService
from app.dependencies import get_orchestrator

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


@router.post("/jobs", response_model=Job, status_code=status.HTTP_201_CREATED)
def create_job(payload: JobCreateRequest, svc: OrchestratorService = Depends(get_orchestrator)) -> Job:
    job = svc.create_job(options=payload.options, path=payload.path)
    return _to_job(job)


@router.delete("/jobs/{job_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def delete_job(job_id: str, svc: OrchestratorService = Depends(get_orchestrator)) -> Response:
    ok = svc.delete_job(job_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Job not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


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


@router.get("/streams/detection/feed")
async def detection_feed(svc: OrchestratorService = Depends(get_orchestrator)):
    """MJPEG detection-overlay feed. Shows ArUco markers and battery contour."""
    return StreamingResponse(
        svc.camera_vision.stream_detection(),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


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
        error=result.error,
        options=payload.options,
    )


def _to_job(job) -> Job:
    return Job(
        id=job.id,
        options=job.options,
        path=job.path,
        log=job.log,
        measurements=job.measurements,
        path_image=job.path_image,
        status={"lastPointProcessed": job.last_point_processed, "error": job.error},
    )
