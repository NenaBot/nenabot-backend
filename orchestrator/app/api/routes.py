from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.schemas import Health, Job, JobCreateRequest, PathRequest, PathResponse, Profile, Status, StreamStatus
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


@router.get("/jobs/{job_id}", response_model=Job)
def get_job(job_id: str, svc: OrchestratorService = Depends(get_orchestrator)) -> Job:
    job = svc.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return _to_job(job)


@router.get("/jobs/latest", response_model=Job)
def latest_job(svc: OrchestratorService = Depends(get_orchestrator)) -> Job:
    job = svc.latest_job()
    if not job:
        raise HTTPException(status_code=404, detail="No jobs yet")
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


@router.post("/streams/camera", response_model=StreamStatus, status_code=status.HTTP_201_CREATED)
def start_camera_stream(svc: OrchestratorService = Depends(get_orchestrator)) -> StreamStatus:
    started_at = svc.start_stream("camera")
    if not started_at:
        raise HTTPException(status_code=404, detail="Stream not found")
    return StreamStatus(status="started", startedAt=started_at)


@router.delete("/streams/camera", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def stop_camera_stream(svc: OrchestratorService = Depends(get_orchestrator)) -> Response:
    if not svc.stop_stream("camera"):
        raise HTTPException(status_code=404, detail="Stream not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/streams/detection", response_model=StreamStatus, status_code=status.HTTP_201_CREATED)
def start_detection_stream(svc: OrchestratorService = Depends(get_orchestrator)) -> StreamStatus:
    started_at = svc.start_stream("detection")
    if not started_at:
        raise HTTPException(status_code=404, detail="Stream not found")
    return StreamStatus(status="started", startedAt=started_at)


@router.delete("/streams/detection", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def stop_detection_stream(svc: OrchestratorService = Depends(get_orchestrator)) -> Response:
    if not svc.stop_stream("detection"):
        raise HTTPException(status_code=404, detail="Stream not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/paths", response_model=PathResponse, status_code=status.HTTP_201_CREATED)
def create_path(payload: PathRequest) -> PathResponse:
    generated = f"path-{uuid4()}"
    return PathResponse(path=generated, options=payload.options)


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
