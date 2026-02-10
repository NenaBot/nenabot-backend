from __future__ import annotations

import uuid
from typing import Dict, List, Optional

from app.adapters.camera_vision import CameraVisionAdapter, DetectionResult
from app.adapters.dms import DmsAdapter
from app.adapters.robot import RobotAdapter
from app.adapters.storage import StorageAdapter
from app.domain.models import Job, ResultSummary


class OrchestratorService:
    def __init__(
        self,
        camera_vision: CameraVisionAdapter,
        robot: RobotAdapter,
        dms: DmsAdapter,
        storage: StorageAdapter,
    ) -> None:
        self._camera_vision = camera_vision
        self._robot = robot
        self._dms = dms
        self._storage = storage
        self._jobs: Dict[str, Job] = {}
        self._job_order: List[str] = []
        self._profiles = [
            {"name": "default", "description": "Default inspection profile"},
            {"name": "fast", "description": "Faster run, lower accuracy"},
        ]

    def create_job(self, options: Optional[dict] = None, path: Optional[str] = None) -> Job:
        job_id = str(uuid.uuid4())
        job = Job(id=job_id, options=options, path=path)
        self._jobs[job_id] = job
        self._job_order.append(job_id)
        return job

    def get_job(self, job_id: str) -> Optional[Job]:
        return self._jobs.get(job_id)

    def list_jobs(self) -> List[Job]:
        return [self._jobs[job_id] for job_id in self._job_order if job_id in self._jobs]

    def latest_job(self) -> Optional[Job]:
        for job_id in reversed(self._job_order):
            job = self._jobs.get(job_id)
            if job:
                return job
        return None

    def delete_job(self, job_id: str) -> bool:
        if job_id not in self._jobs:
            return False
        self._jobs.pop(job_id, None)
        return True

    def health(self) -> Dict[str, str]:
        return {
            "status": "ok",
            "robot": "unknown",
            "camera": "unknown",
            "dms": "unknown",
        }

    def status(self) -> str:
        return "busy" if self._jobs else "ready"

    def profiles(self) -> List[dict]:
        return list(self._profiles)

    def default_profile(self) -> dict:
        return self._profiles[0]

    def detect_path(self) -> DetectionResult:
        """Capture an image, detect battery corners, return result with image."""
        import base64
        from pathlib import Path

        capture = self._camera_vision.capture()
        if not capture.ok or not capture.image_path:
            return DetectionResult(ok=False, error=capture.error or "Capture failed")

        result = self._camera_vision.detect(capture.image_path)

        try:
            raw = Path(capture.image_path).read_bytes()
            result.image_base64 = base64.b64encode(raw).decode("ascii")
        except Exception:
            pass  # image encoding is best-effort

        return result

    @property
    def camera_vision(self) -> CameraVisionAdapter:
        return self._camera_vision

    def latest_result(self) -> Optional[ResultSummary]:
        return self._storage.latest_result()
