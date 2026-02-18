from __future__ import annotations

import base64
import logging
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from app.adapters.camera_vision import CameraVisionAdapter, DetectionResults
from app.adapters.ionVision.ionVision import IVAdapter
from app.adapters.robot import RobotAdapter
from app.adapters.storage import StorageAdapter
from app.domain.models import Job, Measurement, Waypoint

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
        self._profiles = [
            {"name": "default", "description": "Default inspection profile"},
            {"name": "fast", "description": "Faster run, lower accuracy"},
        ]
        self._running_job_id: Optional[str] = None
        self._stop_requested = False
        self._job_thread: Optional[threading.Thread] = None

    # ---- Job CRUD (DB-backed) ----

    def create_job(
        self,
        path: Optional[List[Waypoint]] = None,
        dry_run: bool = False,
        options: Optional[dict] = None,
        image_bytes: Optional[bytes] = None,
        detections: Optional[list] = None,
    ) -> Job:
        job_id = str(uuid.uuid4())
        job = Job(id=job_id, options=options, path=path or [], dry_run=dry_run)
        self._storage.save_job(job)

        # Store initial overlay image (detection snapshot with boxes drawn)
        if image_bytes:
            overlay = CameraVisionAdapter.render_overlay(
                image_bytes, detections or [], []
            )
            self._storage.save_job_image(job_id, overlay)

        return job

    def get_job(self, job_id: str) -> Optional[Job]:
        return self._storage.get_job(job_id)

    def list_jobs(self) -> List[Job]:
        return self._storage.list_jobs()

    def latest_job(self) -> Optional[Job]:
        return self._storage.latest_job()

    def delete_job(self, job_id: str) -> bool:
        return self._storage.delete_job(job_id)

    def get_job_image(self, job_id: str) -> Optional[bytes]:
        return self._storage.get_job_image(job_id)

    # ---- Job execution ----

    def run_job(self, job_id: str) -> Job:
        """Start job execution in a background thread. Returns the job immediately."""
        job = self._storage.get_job(job_id)
        if not job:
            raise ValueError(f"Job {job_id} not found")

        if self._running_job_id:
            raise RuntimeError("Another job is already running")

        self._stop_requested = False
        self._running_job_id = job_id
        job.state = "running"
        job.updated_at = datetime.now(timezone.utc)
        self._storage.update_job_state(job_id, "running", job.last_point_processed)

        self._job_thread = threading.Thread(
            target=self._execute_job, args=(job,), daemon=True
        )
        self._job_thread.start()
        return job

    def stop_job(self) -> bool:
        """Request the running job to stop. Returns True if a job was running."""
        if not self._running_job_id:
            return False
        self._stop_requested = True
        self._robot.stop()
        return True

    def _execute_job(self, job: Job) -> None:
        """Run the job waypoints sequentially (called in background thread)."""
        try:
            for i, wp in enumerate(job.path):
                if self._stop_requested:
                    job.state = "stopped"
                    logger.info("Job %s stopped at waypoint %d", job.id, i)
                    break

                logger.info(
                    "Job %s — waypoint %d/%d  (%.1f, %.1f, %.1f, %.1f) dry_run=%s",
                    job.id, i + 1, len(job.path), wp.x, wp.y, wp.z, wp.r, job.dry_run,
                )

                scan_result: Optional[dict] = None

                if not job.dry_run:
                    # Move robot
                    move_res = self._robot.move(wp.x, wp.y, wp.z, wp.r)
                    if not move_res.ok:
                        raise RuntimeError(f"Robot move failed: {move_res.error}")
                    time.sleep(1.5)  # settle time

                    # DMS scan
                    scan_start = self._dms.start_new_scan()
                    if scan_start.ok:
                        for _ in range(120):
                            time.sleep(0.5)
                            status = self._dms.get_current_scan()
                            if not status.ok:
                                break
                            payload = status.payload or {}
                            if payload.get("state") == "finished":
                                break
                        latest = self._dms.get_latest_dataobject()
                        if latest.ok:
                            scan_result = latest.payload
                else:
                    time.sleep(0.3)

                measurement = Measurement(
                    waypoint_index=i,
                    waypoint=wp,
                    scan_result=scan_result,
                    simulated=job.dry_run,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                )
                job.measurements.append(measurement)
                job.last_point_processed = i + 1
                job.updated_at = datetime.now(timezone.utc)

                # Persist measurement + state to DB
                self._storage.save_measurement(job.id, measurement)
                self._storage.update_job_state(
                    job.id, job.state, job.last_point_processed, job.error
                )

                # Re-render overlay image with accumulated measurements
                self._update_overlay(job)

            if job.state == "running":
                job.state = "completed"

        except Exception as exc:
            logger.exception("Job %s failed: %s", job.id, exc)
            job.state = "failed"
            job.error = str(exc)

        finally:
            self._running_job_id = None
            self._stop_requested = False
            job.updated_at = datetime.now(timezone.utc)
            self._storage.update_job_state(
                job.id, job.state, job.last_point_processed, job.error
            )

    def _update_overlay(self, job: Job) -> None:
        """Re-render the job overlay image with current measurements."""
        try:
            existing = self._storage.get_job_image(job.id)
            if not existing:
                return
            # We need the original snapshot, but we only have the previously
            # rendered overlay.  For simplicity we just re-render from it.
            # The detection boxes are already burned in from create_job.
            overlay = CameraVisionAdapter.render_overlay(
                existing, [], job.measurements
            )
            self._storage.save_job_image(job.id, overlay)
        except Exception:
            logger.debug("Overlay update failed for job %s", job.id, exc_info=True)

    # ---- Misc ----

    def health(self) -> Dict[str, str]:
        return {
            "status": "ok",
            "robot": "unknown",
            "camera": "unknown",
            "dms": "unknown",
        }

    def status(self) -> str:
        if self._running_job_id:
            return "busy"
        return "ready"

    def profiles(self) -> List[dict]:
        return list(self._profiles)

    def default_profile(self) -> dict:
        return self._profiles[0]

    def detect_path(self) -> DetectionResults:
        """Capture an image, detect battery corners, return result with image."""
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
