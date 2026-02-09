from __future__ import annotations

import uuid
from datetime import datetime
from typing import Dict, List, Optional

from app.adapters.camera import CameraAdapter
from app.adapters.dms import DmsAdapter
from app.adapters.robot import RobotAdapter
from app.adapters.storage import StorageAdapter
from app.adapters.vision import VisionAdapter
from app.domain.models import Job, ResultSummary


class OrchestratorService:
    def __init__(
        self,
        camera: CameraAdapter,
        vision: VisionAdapter,
        robot: RobotAdapter,
        dms: DmsAdapter,
        storage: StorageAdapter,
    ) -> None:
        self._camera = camera
        self._vision = vision
        self._robot = robot
        self._dms = dms
        self._storage = storage
        self._jobs: Dict[str, Job] = {}
        self._job_order: List[str] = []
        self._streams: Dict[str, Optional[datetime]] = {"camera": None, "detection": None}
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
            "vision": "unknown",
            "dms": "unknown",
        }

    def status(self) -> str:
        return "busy" if self._jobs else "ready"

    def profiles(self) -> List[dict]:
        return list(self._profiles)

    def default_profile(self) -> dict:
        return self._profiles[0]

    def start_stream(self, stream: str) -> Optional[datetime]:
        if stream not in self._streams:
            return None
        started_at = datetime.utcnow()
        self._streams[stream] = started_at
        return started_at

    def stop_stream(self, stream: str) -> bool:
        if stream not in self._streams:
            return False
        self._streams[stream] = None
        return True

    def latest_result(self) -> Optional[ResultSummary]:
        return self._storage.latest_result()
