from __future__ import annotations

import uuid
import logging
from typing import Dict, List, Optional

from app.adapters.camera_vision import CameraVisionAdapter, DetectionResults
from app.adapters.ionVision import IVAdapter
from app.adapters.robot import RobotAdapter
from app.adapters.storage import StorageAdapter
from app.domain.models import Job, ResultSummary

logger = logging.getLogger(__name__)

class OrchestratorService:
    def __init__(
        self,
        camera_vision: CameraVisionAdapter,
        robot: RobotAdapter,
        dms: IVAdapter,
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

    def detect_path(self) -> DetectionResults:
        """Capture an image, detect battery corners, return result with image."""
        import base64
        from pathlib import Path

        capture = self._camera_vision.capture()
        if not capture.ok or not capture.image_path:
            return DetectionResults(ok=False, error=capture.error or "Capture failed")

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
    
    async def initialize_dms(self) -> None:
        """Initialize async WebSocket handlers, etc"""
        await self._dms.initialize_websocket()
        self._dms.on_event("scan.finished", self._handle_scan_finished)
        self._dms.on_event("message.error", self._handle_error) 
    
    async def _close_dms(self) -> None:
        """Clean up DMS connection and handlers"""
        await self._dms.disconnect_websocket()
        self._dms.off_event("scan.finished", self._handle_scan_finished)
        self._dms.off_event("message.error", self._handle_error) 

    async def _handle_scan_finished(self, data: dict) -> None:
        """scan.finished": A scan has been finished successfully. 
        Results are still being processed."""
        logger.info(f"Scan finished, message body received: {data.get('body')}")

    async def _handle_error(self, data: dict) -> None:
        """message.error": An error or warning message. Contains 
        unique error code."""
        logger.warning(f"An error occurred: {data.get('code')}")

"""
    - "scan.stopped": A scan has been stopped without finishing. No result data will be saved.
    - "scan.finished": A scan has been finished successfully. Results are still being processed.
    - "scan.resultsProcessed": The results of the finished scan have been processed to device storage.
    - "scan.progress": The progress of an ongoing scan (0-100 percentage).
    - "device.standbyButtonPressed": Standby button at front panel pressed. Shows "power off?" dialog.
    - "device.shutdown": Device is powering off. Device APIs will not be usable shortly after.
    - "message.error": An error or warning message. Contains unique error code.
    - "message.limitError": User set or safety limit has been crossed.
    - "backup.started": Backup process started. Scanning unavailable during this.
    - "backup.finished": Backup process finished successfully. 
"""