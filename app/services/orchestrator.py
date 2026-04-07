from __future__ import annotations

import base64
import logging
import math
import queue
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app.adapters.camera_vision import CameraVisionAdapter, DetectionResults
from app.adapters.robot import PoseResult, RobotAdapter, RobotResult
from app.adapters.ionVision import IVAdapter
from app.adapters.storage import StorageAdapter
from app.domain.models import Job, Measurement, Waypoint

logger = logging.getLogger(__name__)

logger = logging.getLogger(__name__)

MAX_MEASURING_POINTS_PER_CM = 10.0
MAX_POPULATED_PATH_POINTS = 20000


class OrchestratorService:
    def __init__(
        self,
        camera_vision: CameraVisionAdapter,
        robot: RobotAdapter,
        dms: IVAdapter,
        storage: StorageAdapter,
        max_jobs: int = 0,
        default_work_z: float = 0.0,
        default_measuring_points_per_cm: float = 0.5,
    ) -> None:
        self._camera_vision = camera_vision
        self._robot = robot
        self._dms = dms
        self._storage = storage
        self._max_jobs = max_jobs  # 0 = unlimited
        self._started_at = time.monotonic()
        self._profiles = [
            {
                "name": "default",
                "description": "Default inspection profile",
                "workZ": default_work_z,
                "measuringPointsPerCm": default_measuring_points_per_cm,
            }
        ]
        self._running_job_id: str | None = None
        self._stop_requested = False
        self._job_thread: threading.Thread | None = None

        # Calibration state — populated by detect_path()
        self._cal_robot_start: Waypoint | None = None
        self._cal_canvas_start: tuple[float, float] | None = None
        self._cal_pixels_per_mm: float | None = None

        # Per-job pixel path for measurement pixel coordinates
        self._pixel_paths: dict[str, list[tuple[float, float]]] = {}

        # Per-job starting positions for return-to-start
        self._starting_waypoints: dict[str, Waypoint] = {}

        # SSE subscribers: job_id → list of queues (one per connected client)
        self._job_subscribers: dict[str, list[queue.Queue]] = {}
        self._subscribers_lock = threading.Lock()

    # ---- Job CRUD (DB-backed) ----

    def subscribe(self, job_id: str) -> queue.Queue:
        """Subscribe to SSE events for a job. Returns a Queue that receives event dicts."""
        q: queue.Queue = queue.Queue()
        with self._subscribers_lock:
            self._job_subscribers.setdefault(job_id, []).append(q)
        return q

    def unsubscribe(self, job_id: str, q: queue.Queue) -> None:
        """Remove a subscriber queue for a job."""
        with self._subscribers_lock:
            subs = self._job_subscribers.get(job_id, [])
            try:
                subs.remove(q)
            except ValueError:
                pass
            if not subs:
                self._job_subscribers.pop(job_id, None)

    def _publish_event(self, job_id: str, event: dict) -> None:
        """Push an event dict to all subscribers of a job."""
        with self._subscribers_lock:
            for q in self._job_subscribers.get(job_id, []):
                try:
                    q.put_nowait(event)
                except queue.Full:
                    pass

    def create_job(
        self,
        path: list[Waypoint] | None = None,
        dry_run: bool = False,
        options: dict | None = None,
        image_bytes: bytes | None = None,
        detections: list | None = None,
        starting_point: Waypoint | None = None,
        pixel_path: list[tuple[float, float]] | None = None,
    ) -> Job:
        job_id = str(uuid.uuid4())
        job = Job(id=job_id, options=options, path=path or [], dry_run=dry_run)
        self._storage.save_job(job)

        # Store the pixel path for measurement pixel coordinates
        self._pixel_paths[job_id] = pixel_path or []

        # Store starting position separately (used for return-to-start,
        # but not included in the measurement loop)
        if starting_point:
            self._starting_waypoints[job_id] = starting_point

        # Store the clean base image (frontend renders points on top)
        if image_bytes:
            self._storage.save_job_image(job_id, image_bytes)

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

        self._publish_event(
            job_id,
            {
                "type": "job:started",
                "job_id": job_id,
                "state": "running",
                "last_point_processed": 0,
                "total_points": len(job.path),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )

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

                self._publish_event(
                    job.id,
                    {
                        "type": "job:waypoint_started",
                        "job_id": job.id,
                        "state": "running",
                        "last_point_processed": job.last_point_processed,
                        "total_points": len(job.path),
                        "waypoint_index": i,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    },
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
                        # # --- SSE: emit scan-started event (uncomment when DMS is connected) ---
                        # self._publish_event(job.id, {
                        #     "type": "job:scanning",
                        #     "job_id": job.id,
                        #     "state": "running",
                        #     "last_point_processed": job.last_point_processed,
                        #     "total_points": len(job.path),
                        #     "waypoint_index": i,
                        #     "timestamp": datetime.now(timezone.utc).isoformat(),
                        # })
                        for _ in range(120):
                            time.sleep(1.5)
                            status = self._dms.get_current_scan()
                            if not status.ok:
                                break
                            payload = status.payload or {}
                            if payload.get("state") == "finished":
                                break
                            # # --- SSE: emit scan-progress event (uncomment when DMS is connected) ---
                            # self._publish_event(job.id, {
                            #     "type": "job:scan_progress",
                            #     "job_id": job.id,
                            #     "state": "running",
                            #     "last_point_processed": job.last_point_processed,
                            #     "total_points": len(job.path),
                            #     "waypoint_index": i,
                            #     "scan_state": payload.get("state"),
                            #     "timestamp": datetime.now(timezone.utc).isoformat(),
                            # })
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

                self._publish_event(
                    job.id,
                    {
                        "type": "job:waypoint_completed",
                        "job_id": job.id,
                        "state": "running",
                        "last_point_processed": job.last_point_processed,
                        "total_points": len(job.path),
                        "waypoint_index": i,
                        "measurement": {
                            "waypointIndex": measurement.waypoint_index,
                            "waypoint": {"x": wp.x, "y": wp.y, "z": wp.z, "r": wp.r},
                            "pixelX": measurement.pixel_x,
                            "pixelY": measurement.pixel_y,
                            "scanResult": measurement.scan_result,
                            "simulated": measurement.simulated,
                            "timestamp": measurement.timestamp,
                        },
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    },
                )

            if job.state == "running":
                # Return to the starting position captured during calibration
                sp = self._starting_waypoints.get(job.id)
                if sp:
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
            self._starting_waypoints.pop(job.id, None)
            job.updated_at = datetime.now(timezone.utc)
            self._storage.update_job_state(
                job.id, job.state, job.last_point_processed, job.error
            )
            self._prune_old_data()

            self._publish_event(
                job.id,
                {
                    "type": f"job:{job.state}",
                    "job_id": job.id,
                    "state": job.state,
                    "last_point_processed": job.last_point_processed,
                    "total_points": len(job.path),
                    "error": job.error,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
            )

    # ---- Data retention ----

    def _prune_image_files(self) -> None:
        """Delete the oldest ``capture_*.jpg`` files beyond *max_jobs*.

        Captured JPEG files accumulate every time ``detect_path()`` is called
        (i.e. on every ``POST /paths`` calibration request), regardless of
        whether a job is running.  This helper is therefore called both after
        each capture *and* at the end of every job so that the output
        directory never grows without bound.

        The ``max_jobs`` newest files (sorted by modification time) are kept;
        everything older is removed.  A failed ``unlink`` is logged as a
        warning and does not raise so that a transient OS error never causes
        a calibration or job failure.

        When ``max_jobs`` is 0 (unlimited) this is a no-op.
        """
        if self._max_jobs <= 0:
            return
        image_dir: Path = self._camera_vision.output_dir
        if not image_dir.is_dir():
            return
        file_mtimes: list[tuple[float, Path]] = []
        for f in image_dir.glob("capture_*.jpg"):
            try:
                file_mtimes.append((f.stat().st_mtime, f))
            except OSError as exc:
                logger.debug(
                    "Retention policy: skipping image file %s during stat - %s",
                    f,
                    exc,
                )
        files = [f for _, f in sorted(file_mtimes, key=lambda item: item[0])]
        excess = len(files) - self._max_jobs
        if excess <= 0:
            return
        for f in files[:excess]:
            try:
                f.unlink()
                logger.debug("Retention policy: deleted image file %s", f)
            except OSError as exc:
                logger.warning("Retention policy: could not delete %s — %s", f, exc)

    def _prune_old_data(self) -> None:
        """Remove excess jobs (DB) and captured image files (disk).

        Called automatically at the end of every job execution.  When
        ``max_jobs`` is 0 (the default) this is a no-op.

        DB cleanup
        ----------
        The oldest jobs beyond the limit are hard-deleted.  Because the
        ``waypoints``, ``measurements``, and ``job_images`` tables all
        reference ``jobs`` with ``ON DELETE CASCADE``, a single
        ``DELETE FROM jobs`` removes every related row automatically.

        Disk cleanup
        ------------
        Delegates to :meth:`_prune_image_files`.
        """
        if self._max_jobs <= 0:
            return

        deleted_ids = self._storage.prune_jobs(self._max_jobs)
        if deleted_ids:
            logger.info(
                "Retention policy: pruned %d old job(s) — %s",
                len(deleted_ids),
                deleted_ids,
            )

        self._prune_image_files()

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

    @staticmethod
    def _pose_is_origin(pose: PoseResult, tolerance: float = 1e-6) -> bool:
        """Treat an all-zero Cartesian pose as an invalid calibration start."""
        return all(
            abs(value) <= tolerance for value in (pose.x, pose.y, pose.z, pose.r)
        )

    @property
    def is_calibrated(self) -> bool:
        return all(
            [
                self._cal_robot_start is not None,
                self._cal_canvas_start is not None,
                self._cal_pixels_per_mm is not None,
            ]
        )

    @property
    def calibration_robot_start(self) -> Waypoint | None:
        return self._cal_robot_start

    @property
    def calibration_canvas_start(self) -> tuple[float, float] | None:
        return self._cal_canvas_start

    @property
    def calibration_pixels_per_mm(self) -> float | None:
        return self._cal_pixels_per_mm

    def sort_pixel_path_from_canvas_start(
        self,
        waypoints: list[tuple[float, float]],
    ) -> list[tuple[float, float]]:
        """Order waypoints by direct distance to the calibrated canvas start."""
        if self._cal_canvas_start is None:
            raise RuntimeError(
                "Not calibrated — call POST /path/detect first "
                "(with robot arm at starting position)"
            )

        if not waypoints:
            return []

        start = self._cal_canvas_start
        return sorted(
            waypoints,
            key=lambda p: math.hypot(p[0] - start[0], p[1] - start[1]),
        )

    def _normalize_corners_clockwise_start_nearest(
        self,
        corners: list[tuple[float, float]],
        start: tuple[float, float],
    ) -> list[tuple[float, float]]:
        """Return corners ordered clockwise and rotated to start nearest to canvas start."""
        if len(corners) < 2:
            return list(corners)

        cx = sum(x for x, _ in corners) / len(corners)
        cy = sum(y for _, y in corners) / len(corners)

        # Ascending angle yields clockwise order in image coordinates (Y grows down).
        ordered = sorted(corners, key=lambda p: math.atan2(p[1] - cy, p[0] - cx))

        nearest_idx = min(
            range(len(ordered)),
            key=lambda i: math.hypot(
                ordered[i][0] - start[0],
                ordered[i][1] - start[1],
            ),
        )
        return ordered[nearest_idx:] + ordered[:nearest_idx]

    def populate_pixel_path_from_batteries(
        self,
        batteries: list[list[tuple[float, float]]],
        measuring_points_per_cm: float,
    ) -> list[dict[str, float | int | str]]:
        """Generate perimeter measurement points for frontend-provided battery corners."""
        if self._cal_canvas_start is None or self._cal_pixels_per_mm is None:
            raise RuntimeError(
                "Not calibrated — call POST /path/detect first "
                "(with robot arm at starting position)"
            )
        if measuring_points_per_cm <= 0:
            raise ValueError("measuring_points_per_cm must be > 0")
        if measuring_points_per_cm > MAX_MEASURING_POINTS_PER_CM:
            raise ValueError(
                f"measuring_points_per_cm must be <= {MAX_MEASURING_POINTS_PER_CM}"
            )

        canvas_start = self._cal_canvas_start
        step_px = (10.0 / measuring_points_per_cm) * self._cal_pixels_per_mm

        ordered_batteries: list[tuple[float, list[tuple[float, float]]]] = []
        for corners in batteries:
            clean = [(float(x), float(y)) for x, y in corners]
            if len(clean) < 2:
                continue

            normalized = self._normalize_corners_clockwise_start_nearest(
                clean,
                canvas_start,
            )
            nearest_dist = min(
                math.hypot(px - canvas_start[0], py - canvas_start[1])
                for px, py in normalized
            )
            ordered_batteries.append((nearest_dist, normalized))

        ordered_batteries.sort(key=lambda item: item[0])

        path: list[dict[str, float | int | str]] = []
        for battery_nr, (_, corners) in enumerate(ordered_batteries):
            corner_count = len(corners)
            for corner_idx in range(corner_count):
                x1, y1 = corners[corner_idx]
                x2, y2 = corners[(corner_idx + 1) % corner_count]
                edge_len = math.hypot(x2 - x1, y2 - y1)
                if edge_len == 0:
                    continue

                sample_count = max(1, int(math.ceil(edge_len / step_px)))
                if len(path) + sample_count > MAX_POPULATED_PATH_POINTS:
                    raise ValueError(
                        "Requested path is too dense; reduce measuringPointsPerCm or battery count"
                    )
                for measurement_idx in range(sample_count):
                    t = measurement_idx / sample_count
                    px = x1 + (x2 - x1) * t
                    py = y1 + (y2 - y1) * t
                    path.append(
                        {
                            "index": f"{battery_nr}-{corner_idx}-{measurement_idx}",
                            "batteryNr": battery_nr,
                            "cornerIndex": corner_idx,
                            "measurementIndex": measurement_idx,
                            "pixelX": px,
                            "pixelY": py,
                        }
                    )

        return path

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

        # Prune old capture files immediately after writing a new one so the
        # output directory never grows without bound even when no jobs are run.
        self._prune_image_files()

        # Replace any previous calibration with values derived from this capture.
        self._cal_robot_start = None
        self._cal_canvas_start = None
        self._cal_pixels_per_mm = None

        result = self._camera_vision.detect(capture.image_path)
        messages = [result.error] if result.error else []

        try:
            raw = Path(capture.image_path).read_bytes()
            result.image_base64 = base64.b64encode(raw).decode("ascii")
        except Exception:
            logger.debug("Image encoding failed", exc_info=True)

        # --- Calibration: capture robot pose + canvas start ----
        pose = self._robot.get_pose()
        if pose.ok and not self._pose_is_origin(pose):
            self._cal_robot_start = Waypoint(x=pose.x, y=pose.y, z=pose.z, r=pose.r)
            logger.info(
                "Calibration: robot start → (%.1f, %.1f, %.1f, %.1f)",
                pose.x,
                pose.y,
                pose.z,
                pose.r,
            )
        elif pose.ok:
            msg = (
                "Robot pose is still at origin (0, 0, 0, 0) — "
                "move the arm to the start position and retry"
            )
            messages.append(msg)
            logger.warning("Calibration: %s", msg)
        else:
            msg = pose.error or "Could not read robot pose"
            messages.append(f"Could not read robot pose: {msg}")
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
            msg = "No ArUco markers detected"
            messages.append(msg)
            logger.warning("Calibration: no ArUco markers — canvas start not set")

        # Keep detector output order unchanged so frontend receives initial values as-is.

        result.error = "; ".join(dict.fromkeys(msg for msg in messages if msg)) or None

        return result

    @property
    def camera_vision(self) -> CameraVisionAdapter:
        return self._camera_vision

    def latest_result(self) -> Optional[dict]:
        return self._storage.latest_result()

    # WEBSOCKET SERVICES
    async def initialize_dms(self) -> None:
        """Initialize async WebSocket handlers, etc"""
        await self._dms.initialize_websocket()
        self._dms.on_event("scan.resultsProcessed", self._handle_scan_results_processed)
        self._dms.on_event("scan.stopped", self._handle_scan_stopped)

    async def _close_dms(self) -> None:
        """Clean up DMS connection and handlers"""
        await self._dms.disconnect_websocket()
        self._dms.off_event(
            "scan.resultsProcessed", self._handle_scan_results_processed
        )
        self._dms.off_event("scan.stopped", self._handle_scan_stopped)

    async def _handle_scan_results_processed(self, data: dict) -> None:
        """The results of the previously finished scan have been
        processed to the device storage."""
        logger.info(f"Scan results have been processed: {data.get('body')}")

    async def _handle_scan_stopped(self, data: dict) -> None:
        """The scan has been stopped by the user or due to an error."""
        logger.info(f"Scan has been stopped: {data.get('body')}")

    async def _handle_error(self, data: dict) -> None:
        """
        (likely not necessary handle for this project)
        A scan has been stopped without finishing. No result data will be saved.
        """
        logger.warning(f"An error occurred: {data.get('code')}")
