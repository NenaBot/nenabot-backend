from __future__ import annotations

import base64
import logging
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.adapters.camera_vision import CameraVisionAdapter, DetectionResults
from app.adapters.robot import PoseResult, RobotAdapter, RobotResult
from app.adapters.ionVision import IVAdapter
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
        self._started_at = time.monotonic()
        self._profiles = [
            {"name": "default", "description": "Default inspection profile"},
            {"name": "fast", "description": "Faster run, lower accuracy"},
        ]
        self._running_job_id: str | None = None
        self._stop_requested = False
        self._job_thread: threading.Thread | None = None

        # Calibration state — populated by detect_path()
        self._cal_robot_start: Waypoint | None = None
        self._cal_canvas_start: tuple[float, float] | None = None
        self._cal_pixels_per_mm: float | None = None

        # Per-job pixel path for overlay rendering (job_id → pixel coords)
        self._pixel_paths: dict[str, list[tuple[float, float]]] = {}

    # ---- Job CRUD (DB-backed) ----

    def create_job(
        self,
        path: list[Waypoint] | None = None,
        dry_run: bool = False,
        options: dict | None = None,
        image_bytes: bytes | None = None,
        detections: list | None = None,
        starting_point: Waypoint | None = None,
        canvas_start: tuple[float, float] | None = None,
        pixel_path: list[tuple[float, float]] | None = None,
    ) -> Job:
        job_id = str(uuid.uuid4())
        job = Job(id=job_id, options=options, path=path or [], dry_run=dry_run)
        self._storage.save_job(job)

        # Store the pixel path for overlay rendering during execution
        self._pixel_paths[job_id] = pixel_path or []

        # Store initial overlay image (detection snapshot with boxes drawn)
        if image_bytes:
            sp_tuple = canvas_start  # already in pixel coordinates
            overlay = CameraVisionAdapter.render_overlay(
                image_bytes, detections or [], [], starting_point=sp_tuple
            )
            self._storage.save_job_image(job_id, overlay)

            # Save the clean base image so we can re-render overlays later
            self._storage.save_job_base_image(job_id, image_bytes)

        return job

    def get_job(self, job_id: str) -> Job | None:
        return self._storage.get_job(job_id)

    def list_jobs(self) -> list[Job]:
        return self._storage.list_jobs()

    def latest_job(self) -> Job | None:
        return self._storage.latest_job()

    def delete_job(self, job_id: str) -> bool:
        return self._storage.delete_job(job_id)

    def get_job_image(self, job_id: str) -> bytes | None:
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

    def get_robot_pose(self) -> PoseResult:
        """Read the current position of the robot arm."""
        return self._robot.get_pose()

    def move_robot(
        self,
        x: float,
        y: float,
        z: float,
        r: float,
    ) -> RobotResult:
        """Send the robot to a specific position (for calibration / testing)."""
        logger.info(
            "Manual move → (%.1f, %.1f, %.1f, %.1f)",
            x,
            y,
            z,
            r,
        )
        return self._robot.move(x, y, z, r)

    def _execute_job(self, job: Job) -> None:
        """Run the job waypoints sequentially (called in background thread)."""
        try:
            for i, wp in enumerate(job.path):
                if self._stop_requested:
                    job.state = "stopped"
                    logger.info("Job %s stopped at waypoint %d", job.id, i)
                    break

                logger.info(
                    "Job %s — WP %d/%d (%.1f, %.1f, %.1f, %.1f) dry=%s",
                    job.id,
                    i + 1,
                    len(job.path),
                    wp.x,
                    wp.y,
                    wp.z,
                    wp.r,
                    job.dry_run,
                )

                scan_result: dict | None = None

                # Look up pixel coordinates for this waypoint
                pp = self._pixel_paths.get(job.id, [])
                pixel_coords: tuple[float, float] | None = None
                if i < len(pp):
                    pixel_coords = pp[i]

                if not job.dry_run:
                    # Move robot to waypoint
                    move_res = self._robot.move(wp.x, wp.y, wp.z, wp.r)
                    if not move_res.ok:
                        raise RuntimeError(f"Robot move failed: {move_res.error}")

                    # Validate the arm actually reached the target position
                    arrival = self._robot.wait_for_position(
                        wp.x,
                        wp.y,
                        wp.z,
                        wp.r,
                        tolerance_mm=1.0,
                        timeout_s=30.0,
                    )
                    if not arrival.ok:
                        logger.warning(
                            "Job %s — WP %d arrival validation failed: %s",
                            job.id,
                            i + 1,
                            arrival.error,
                        )
                        msg = f"Arm did not reach waypoint {i + 1}: {arrival.error}"
                        raise RuntimeError(msg)
                    logger.info(
                        "Job %s — WP %d reached: (%.1f, %.1f, %.1f) — dwelling 1.5 s",
                        job.id,
                        i + 1,
                        arrival.x,
                        arrival.y,
                        arrival.z,
                    )

                    # Dwell at the waypoint for 1.5 seconds
                    time.sleep(1.5)

                    # Here comes the reading of the DMS
                    scan_start = self._dms.start_new_scan()
                    if scan_start.ok:
                        for _ in range(120):
                            time.sleep(1.5)
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
                    time.sleep(0.3)  # simulate settle time in dry run

                measurement = Measurement(
                    waypoint_index=i,
                    waypoint=wp,
                    pixel_x=pixel_coords[0] if pixel_coords else None,
                    pixel_y=pixel_coords[1] if pixel_coords else None,
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
                # Return to starting position (path[0] = the starting point)
                if job.path:
                    sp = job.path[0]
                    if not job.dry_run:
                        logger.info(
                            "Job %s — returning to start (%.1f, %.1f, %.1f, %.1f)",
                            job.id,
                            sp.x,
                            sp.y,
                            sp.z,
                            sp.r,
                        )
                        move_res = self._robot.move(sp.x, sp.y, sp.z, sp.r)
                        if not move_res.ok:
                            logger.warning(
                                "Return-to-start failed: %s",
                                move_res.error,
                            )
                        else:
                            arrival = self._robot.wait_for_position(
                                sp.x,
                                sp.y,
                                sp.z,
                                sp.r,
                                tolerance_mm=1.0,
                                timeout_s=30.0,
                            )
                            if not arrival.ok:
                                logger.warning(
                                    "Return-to-start validation failed: %s",
                                    arrival.error,
                                )
                            else:
                                logger.info(
                                    "Job %s — back at start (%.1f, %.1f, %.1f)",
                                    job.id,
                                    arrival.x,
                                    arrival.y,
                                    arrival.z,
                                )
                    else:
                        logger.info(
                            "Job %s (dry run) — would return "
                            "to start (%.1f, %.1f, %.1f, %.1f)",
                            job.id,
                            sp.x,
                            sp.y,
                            sp.z,
                            sp.r,
                        )
                job.state = "completed"

        except Exception as exc:
            logger.exception("Job %s failed: %s", job.id, exc)
            job.state = "failed"
            job.error = str(exc)

        finally:
            self._running_job_id = None
            self._stop_requested = False
            self._pixel_paths.pop(job.id, None)
            job.updated_at = datetime.now(timezone.utc)
            self._storage.update_job_state(
                job.id, job.state, job.last_point_processed, job.error
            )

    def _update_overlay(self, job: Job) -> None:
        """Re-render the job overlay image with current measurements."""
        try:
            base = self._storage.get_job_base_image(job.id)
            if not base:
                return
            # Determine starting-point pixel coords for the overlay
            pp = self._pixel_paths.get(job.id, [])
            sp_tuple: tuple[float, float] | None = None
            if pp:
                sp_tuple = pp[0]  # first entry is the starting position
            overlay = CameraVisionAdapter.render_overlay(
                base, [], job.measurements, starting_point=sp_tuple
            )
            self._storage.save_job_image(job.id, overlay)
        except Exception:
            logger.debug("Overlay update failed for job %s", job.id, exc_info=True)

    # ---- Misc ----

    def health(self) -> dict[str, object]:
        """Probe every subsystem and return a structured health report."""
        components: dict[str, dict[str, str | None]] = {}

        # Robot
        try:
            res = self._robot.ping()
            components["robot"] = {
                "status": "connected" if res.ok else "disconnected",
                "error": res.error,
            }
        except Exception as exc:
            components["robot"] = {"status": "error", "error": str(exc)}

        # Camera
        try:
            res = self._camera_vision.ping()
            components["camera"] = {
                "status": "connected" if res.ok else "disconnected",
                "error": res.error,
            }
        except Exception as exc:
            components["camera"] = {"status": "error", "error": str(exc)}

        # DMS (IonVision)
        try:
            res = self._dms.ping()
            components["dms"] = {
                "status": "connected" if res.ok else "disconnected",
                "error": res.error,
            }
        except Exception as exc:
            components["dms"] = {"status": "error", "error": str(exc)}

        any_error = any(c["status"] == "error" for c in components.values())
        overall = "degraded" if any_error else "ok"

        return {
            "status": overall,
            "uptime_s": round(time.monotonic() - self._started_at, 2),
            **components,
        }

    def status(self) -> str:
        if self._running_job_id:
            return "busy"
        return "ready"

    def profiles(self) -> list[dict]:
        return list(self._profiles)

    def default_profile(self) -> dict:
        return self._profiles[0]

    # ---- Calibration ----

    def _compute_canvas_start(
        self, result: DetectionResults, offset_mm: float = 50.0
    ) -> tuple[float, float] | None:
        """Compute canvas start marker 50 mm below the first ArUco marker center.

        Camera is mounted behind the arm, so "below" in the image (Y+)
        corresponds to the arm being offset away from the marker.
        """
        if not result.marker_corners:
            return None
        mc = result.marker_corners[0].corners
        if len(mc) < 4:
            return None

        cx = sum(c.x for c in mc) / len(mc)
        cy = sum(c.y for c in mc) / len(mc)

        ppm = result.pixels_per_mm
        offset_px = (offset_mm * ppm) if ppm else 50.0
        return (cx, cy + offset_px)

    @property
    def is_calibrated(self) -> bool:
        return all([
            self._cal_robot_start is not None,
            self._cal_canvas_start is not None,
            self._cal_pixels_per_mm is not None,
        ])

    @property
    def calibration_robot_start(self) -> Waypoint | None:
        return self._cal_robot_start

    @property
    def calibration_canvas_start(self) -> tuple[float, float] | None:
        return self._cal_canvas_start

    @property
    def calibration_pixels_per_mm(self) -> float | None:
        return self._cal_pixels_per_mm

    def pixel_to_robot(
        self, px: float, py: float, work_z: float, work_r: float
    ) -> Waypoint:
        """Convert canvas pixel coordinates → robot mm coordinates.

        Uses the calibration state captured during ``detect_path()``.
        Camera orientation (mounted behind the arm):
          • image Y decreasing (up) → robot +X
          • image X increasing (right) → robot −Y
        """
        if not self.is_calibrated:
            raise RuntimeError(
                "Not calibrated — call POST /paths first "
                "(with robot arm at starting position)"
            )
        cs_x, cs_y = self._cal_canvas_start  # type: ignore[misc]
        rs = self._cal_robot_start  # type: ignore[union-attr]
        ppm = self._cal_pixels_per_mm  # type: ignore[assignment]

        dpx = px - cs_x  # pixel delta X (+ = right)
        dpy = py - cs_y  # pixel delta Y (+ = down)
        return Waypoint(
            x=rs.x - (dpy / ppm),  # pixel Y↑ → robot +X
            y=rs.y - (dpx / ppm),  # pixel X→ → robot −Y
            z=work_z,
            r=work_r,
        )

    def detect_path(self) -> DetectionResults:
        """Capture an image, detect battery corners, and calibrate.

        This also reads the robot’s current pose (assumed to be at the
        starting position) and computes the canvas start point from the
        first ArUco marker.  All three calibration ingredients are stored
        so that ``pixel_to_robot()`` can convert coordinates.
        """
        capture = self._camera_vision.capture()
        if not capture.ok or not capture.image_path:
            return DetectionResults(ok=False, error=capture.error or "Capture failed")

        result = self._camera_vision.detect(capture.image_path)

        try:
            raw = Path(capture.image_path).read_bytes()
            result.image_base64 = base64.b64encode(raw).decode("ascii")
        except Exception:
            logger.debug("Image encoding failed", exc_info=True)

        # --- Calibration: capture robot pose + canvas start ----
        pose = self._robot.get_pose()
        if pose.ok:
            self._cal_robot_start = Waypoint(
                x=pose.x, y=pose.y, z=pose.z, r=pose.r
            )
            logger.info(
                "Calibration: robot start → (%.1f, %.1f, %.1f, %.1f)",
                pose.x, pose.y, pose.z, pose.r,
            )
        else:
            logger.warning("Calibration: could not read robot pose — %s", pose.error)

        self._cal_pixels_per_mm = result.pixels_per_mm
        self._cal_canvas_start = self._compute_canvas_start(result)

        if self._cal_canvas_start:
            logger.info(
                "Calibration: canvas start → (%.0f, %.0f) px, ppm=%.4f",
                self._cal_canvas_start[0],
                self._cal_canvas_start[1],
                self._cal_pixels_per_mm or 0,
            )
        else:
            logger.warning("Calibration: no ArUco markers — canvas start not set")

        return result

    @property
    def camera_vision(self) -> CameraVisionAdapter:
        return self._camera_vision
