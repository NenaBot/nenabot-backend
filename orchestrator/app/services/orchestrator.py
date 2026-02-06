from __future__ import annotations

import uuid
from datetime import datetime
from typing import Dict, Optional

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

    def start_job(self, pack_id: str) -> Job:
        job_id = str(uuid.uuid4())
        job = Job(id=job_id, pack_id=pack_id, state="running", step="init")
        self._jobs[job_id] = job
        return job

    def get_job(self, job_id: str) -> Optional[Job]:
        return self._jobs.get(job_id)

    def cancel_job(self, job_id: str) -> Optional[Job]:
        job = self._jobs.get(job_id)
        if not job:
            return None
        job.state = "cancelled"
        job.step = "cancelled"
        job.updated_at = datetime.utcnow()
        return job

    def health(self) -> Dict[str, str]:
        return {
            "status": "ok",
            "robot": "unknown",
            "camera": "unknown",
            "vision": "unknown",
            "dms": "unknown",
        }

    def latest_result(self) -> Optional[ResultSummary]:
        return self._storage.latest_result()
