"""In-memory storage adapter used for mock mode runtime."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import threading

from app.domain.models import Job, Measurement


class InMemoryStorageAdapter:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._jobs: dict[str, Job] = {}
        self._images: dict[str, bytes] = {}

    def _clone_job(self, job: Job) -> Job:
        return deepcopy(job)

    # ---- Jobs ----

    def save_job(self, job: Job) -> None:
        with self._lock:
            self._jobs[job.id] = self._clone_job(job)

    def update_job_state(
        self,
        job_id: str,
        state: str,
        last_point_processed: int,
        error: str | None = None,
    ) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            job.state = state
            job.last_point_processed = last_point_processed
            job.error = error
            job.updated_at = datetime.now(timezone.utc)

    def get_job(self, job_id: str) -> Job | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return self._clone_job(job) if job is not None else None

    def list_jobs(self) -> list[Job]:
        with self._lock:
            jobs_sorted = sorted(
                self._jobs.values(),
                key=lambda job: (job.created_at, job.id),
            )
            return [self._clone_job(job) for job in jobs_sorted]

    def latest_job(self) -> Job | None:
        with self._lock:
            if not self._jobs:
                return None
            latest = max(
                self._jobs.values(),
                key=lambda job: (
                    job.created_at,
                    job.updated_at,
                    job.id,
                ),
            )
            return self._clone_job(latest)

    def delete_job(self, job_id: str) -> bool:
        with self._lock:
            existed = job_id in self._jobs
            self._jobs.pop(job_id, None)
            self._images.pop(job_id, None)
            return existed

    def prune_jobs(self, max_jobs: int) -> list[str]:
        if max_jobs <= 0:
            return []
        with self._lock:
            jobs_sorted = sorted(
                self._jobs.values(),
                key=lambda job: (job.created_at, job.id),
            )
            excess = len(jobs_sorted) - max_jobs
            if excess <= 0:
                return []
            deleted_ids = [job.id for job in jobs_sorted[:excess]]
            for job_id in deleted_ids:
                self._jobs.pop(job_id, None)
                self._images.pop(job_id, None)
            return deleted_ids

    # ---- Measurements ----

    def save_measurement(self, job_id: str, measurement: Measurement) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            job.measurements.append(deepcopy(measurement))

    def get_measurements(self, job_id: str) -> list[Measurement]:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return []
            return deepcopy(job.measurements)

    # ---- Images ----

    def save_job_image(
        self,
        job_id: str,
        image_bytes: bytes,
        content_type: str = "image/jpeg",
    ) -> None:
        _ = content_type
        with self._lock:
            self._images[job_id] = bytes(image_bytes)

    def get_job_image(self, job_id: str) -> bytes | None:
        with self._lock:
            image_bytes = self._images.get(job_id)
            return bytes(image_bytes) if image_bytes is not None else None
