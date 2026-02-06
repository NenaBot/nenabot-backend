from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.schemas import Health, InspectionJobRequest, InspectionResultSummary, JobCreated, JobStatus
from app.services.orchestrator import OrchestratorService
from app.dependencies import get_orchestrator

router = APIRouter()


@router.post("/jobs/start", response_model=JobCreated)
def start_job(payload: InspectionJobRequest, svc: OrchestratorService = Depends(get_orchestrator)) -> JobCreated:
    job = svc.start_job(payload.pack_id)
    return JobCreated(id=job.id)


@router.get("/jobs/{job_id}", response_model=JobStatus)
def get_job(job_id: str, svc: OrchestratorService = Depends(get_orchestrator)) -> JobStatus:
    job = svc.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobStatus(id=job.id, state=job.state, step=job.step, updatedAt=job.updated_at)


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: str, svc: OrchestratorService = Depends(get_orchestrator)) -> dict:
    job = svc.cancel_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"status": "cancelled"}


@router.get("/health", response_model=Health)
def health(svc: OrchestratorService = Depends(get_orchestrator)) -> Health:
    data = svc.health()
    return Health(**data)


@router.get("/results/latest", response_model=InspectionResultSummary)
def latest_result(svc: OrchestratorService = Depends(get_orchestrator)) -> InspectionResultSummary:
    result = svc.latest_result()
    if not result:
        raise HTTPException(status_code=404, detail="No results yet")
    return InspectionResultSummary(
        id=result.id,
        packId=result.pack_id,
        startedAt=result.started_at,
        finishedAt=result.finished_at,
        decision=result.decision,
        dmsPpb=result.dms_ppb,
        dmsCompound=result.dms_compound,
        imagePath=result.image_path,
    )
