from __future__ import annotations

import json
import logging
import math
import queue
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from app.adapters.camera_vision import (
    FIXED_CALIBRATION_POINTS,
    CalibrationTarget,
    CameraVisionAdapter,
    DetectionResults,
)
from app.adapters.ionVision import IVAdapter
from app.adapters.robot import PoseResult, RobotAdapter, RobotResult
from app.adapters.storage import StorageAdapter
from app.domain.models import Job, Measurement, Waypoint

logger = logging.getLogger(__name__)

MAX_MEASURING_POINTS_PER_CM = 10.0
MAX_POPULATED_PATH_POINTS = 20000
TOTAL_CALIBRATION_STEPS = len(FIXED_CALIBRATION_POINTS)
MIN_ROBOT_REACH_MM = 120.0
MAX_ROBOT_REACH_MM = 360.0


@dataclass
class CalibrationSession:
    reference_image_base64: str
    targets: list[CalibrationTarget]
    start_pose: Waypoint
    captured_robot_points: list[tuple[float, float, float]] = field(
        default_factory=list
    )

    @property
    def current_step(self) -> int:
        return len(self.captured_robot_points)


class OrchestratorService:
    def __init__(
        self,
        camera_vision: CameraVisionAdapter,
        robot: RobotAdapter,
        dms: IVAdapter,
        storage: StorageAdapter,
        mapping_path: str = "data/calibration/robot_mapping.json",
    ) -> None:
        self._camera_vision = camera_vision
        self._robot = robot
        self._dms = dms
        self._storage = storage
        self._mapping_path = Path(mapping_path)
        self._started_at = time.monotonic()
        self._profiles = [
            {"name": "default", "description": "Default inspection profile"},
            {"name": "fast", "description": "Faster run, lower accuracy"},
        ]
        self._running_job_id: str | None = None
        self._stop_requested = False
        self._job_thread: threading.Thread | None = None

        self._calibration_lock = threading.Lock()
        self._calibration_session: CalibrationSession | None = None
        self._mapping_data: dict | None = self._load_mapping_file()

        self._pixel_paths: dict[str, list[tuple[float, float]]] = {}
        self._starting_waypoints: dict[str, Waypoint] = {}

        self._job_subscribers: dict[str, list[queue.Queue]] = {}
        self._subscribers_lock = threading.Lock()

    # ---- Job CRUD (DB-backed) ----

    def subscribe(self, job_id: str) -> queue.Queue:
        q: queue.Queue = queue.Queue()
        with self._subscribers_lock:
            self._job_subscribers.setdefault(job_id, []).append(q)
        return q

    def unsubscribe(self, job_id: str, q: queue.Queue) -> None:
        with self._subscribers_lock:
            subscribers = self._job_subscribers.get(job_id, [])
            try:
                subscribers.remove(q)
            except ValueError:
                pass
            if not subscribers:
                self._job_subscribers.pop(job_id, None)

    def _publish_event(self, job_id: str, event: dict) -> None:
        with self._subscribers_lock:
            for subscriber in self._job_subscribers.get(job_id, []):
                try:
                    subscriber.put_nowait(event)
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

        self._pixel_paths[job_id] = pixel_path or []
        if starting_point:
            self._starting_waypoints[job_id] = starting_point
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
            target=self._execute_job,
            args=(job,),
            daemon=True,
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
        if not self._running_job_id:
            return False
        self._stop_requested = True
        self._robot.stop()
        return True

    def get_robot_pose(self) -> PoseResult:
        return self._robot.get_pose()

    def move_robot(self, x: float, y: float, z: float, r: float) -> RobotResult:
        logger.info("Manual move → (%.1f, %.1f, %.1f, %.1f)", x, y, z, r)
        return self._robot.move(x, y, z, r)

    def _execute_job(self, job: Job) -> None:
        try:
            for index, waypoint in enumerate(job.path):
                if self._stop_requested:
                    job.state = "stopped"
                    logger.info("Job %s stopped at waypoint %d", job.id, index)
                    break

                logger.info(
                    "Job %s — WP %d/%d (%.1f, %.1f, %.1f, %.1f) dry=%s",
                    job.id,
                    index + 1,
                    len(job.path),
                    waypoint.x,
                    waypoint.y,
                    waypoint.z,
                    waypoint.r,
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
                        "waypoint_index": index,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    },
                )

                pixel_coords: tuple[float, float] | None = None
                if index < len(self._pixel_paths.get(job.id, [])):
                    pixel_coords = self._pixel_paths[job.id][index]

                scan_result: dict | None = None
                if not job.dry_run:
                    move_result = self._robot.move(
                        waypoint.x,
                        waypoint.y,
                        waypoint.z,
                        waypoint.r,
                    )
                    if not move_result.ok:
                        raise RuntimeError(f"Robot move failed: {move_result.error}")

                    arrival = self._robot.wait_for_position(
                        waypoint.x,
                        waypoint.y,
                        waypoint.z,
                        waypoint.r,
                        tolerance_mm=1.0,
                        timeout_s=30.0,
                    )
                    if not arrival.ok:
                        raise RuntimeError(
                            f"Arm did not reach waypoint {index + 1}: {arrival.error}"
                        )

                    time.sleep(1.5)
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
                    time.sleep(0.3)

                measurement = Measurement(
                    waypoint_index=index,
                    waypoint=waypoint,
                    pixel_x=pixel_coords[0] if pixel_coords else None,
                    pixel_y=pixel_coords[1] if pixel_coords else None,
                    scan_result=scan_result,
                    simulated=job.dry_run,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                )
                job.measurements.append(measurement)
                job.last_point_processed = index + 1
                job.updated_at = datetime.now(timezone.utc)

                self._storage.save_measurement(job.id, measurement)
                self._storage.update_job_state(
                    job.id,
                    job.state,
                    job.last_point_processed,
                    job.error,
                )

                self._publish_event(
                    job.id,
                    {
                        "type": "job:waypoint_completed",
                        "job_id": job.id,
                        "state": "running",
                        "last_point_processed": job.last_point_processed,
                        "total_points": len(job.path),
                        "waypoint_index": index,
                        "measurement": {
                            "waypointIndex": measurement.waypoint_index,
                            "waypoint": {
                                "x": waypoint.x,
                                "y": waypoint.y,
                                "z": waypoint.z,
                                "r": waypoint.r,
                            },
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
                self._return_job_to_start(job)
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
                job.id,
                job.state,
                job.last_point_processed,
                job.error,
            )

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

    def _return_job_to_start(self, job: Job) -> None:
        start_point = self._starting_waypoints.get(job.id)
        if not start_point:
            return
        if job.dry_run:
            logger.info(
                "Job %s (dry run) — would return to start (%.1f, %.1f, %.1f, %.1f)",
                job.id,
                start_point.x,
                start_point.y,
                start_point.z,
                start_point.r,
            )
            return

        logger.info(
            "Job %s — returning to start (%.1f, %.1f, %.1f, %.1f)",
            job.id,
            start_point.x,
            start_point.y,
            start_point.z,
            start_point.r,
        )
        move_result = self._robot.move(
            start_point.x,
            start_point.y,
            start_point.z,
            start_point.r,
        )
        if not move_result.ok:
            logger.warning("Return-to-start failed: %s", move_result.error)
            return

        arrival = self._robot.wait_for_position(
            start_point.x,
            start_point.y,
            start_point.z,
            start_point.r,
            tolerance_mm=1.0,
            timeout_s=30.0,
        )
        if not arrival.ok:
            logger.warning("Return-to-start validation failed: %s", arrival.error)

    # ---- Misc ----

    def health(self) -> dict[str, object]:
        components: dict[str, dict[str, str | None]] = {}

        try:
            result = self._robot.ping()
            components["robot"] = {
                "status": "connected" if result.ok else "disconnected",
                "error": result.error,
            }
        except Exception as exc:
            components["robot"] = {"status": "error", "error": str(exc)}

        try:
            result = self._camera_vision.ping()
            components["camera"] = {
                "status": "connected" if result.ok else "disconnected",
                "error": result.error,
            }
        except Exception as exc:
            components["camera"] = {"status": "error", "error": str(exc)}

        try:
            result = self._dms.ping()
            components["dms"] = {
                "status": "connected" if result.ok else "disconnected",
                "error": result.error,
            }
        except Exception as exc:
            components["dms"] = {"status": "error", "error": str(exc)}

        overall = (
            "degraded"
            if any(component["status"] == "error" for component in components.values())
            else "ok"
        )

        return {
            "status": overall,
            "uptime_s": round(time.monotonic() - self._started_at, 2),
            **components,
        }

    def status(self) -> dict[str, object]:
        checkerboard = self._camera_vision.checkerboard_status()
        session = self._calibration_session
        return {
            "state": "busy" if self._running_job_id else "ready",
            "calibration": {
                "intrinsics_loaded": self._camera_vision.intrinsics_loaded,
                "checkerboard_visible": bool(checkerboard["visible"]),
                "calibration_in_progress": session is not None,
                "current_step": session.current_step if session else 0,
                "total_steps": TOTAL_CALIBRATION_STEPS,
                "calibrated": self.is_calibrated,
                "last_calibrated_at": self.last_calibrated_at,
            },
        }

    def profiles(self) -> list[dict]:
        return list(self._profiles)

    def default_profile(self) -> dict:
        return self._profiles[0]

    def validate_job_waypoints(
        self,
        path: list[Waypoint],
        dry_run: bool,
    ) -> None:
        if not path:
            raise ValueError("Job path is empty")

        for index, waypoint in enumerate(path, start=1):
            coords = (waypoint.x, waypoint.y, waypoint.z, waypoint.r)
            if any(not math.isfinite(value) for value in coords):
                raise ValueError(f"Waypoint {index} contains non-finite values")

            reach = math.hypot(waypoint.x, waypoint.y)
            if reach < MIN_ROBOT_REACH_MM or reach > MAX_ROBOT_REACH_MM:
                raise ValueError(
                    "Waypoint "
                    f"{index} is outside the Dobot working radius: "
                    f"reach={reach:.1f} mm, expected {MIN_ROBOT_REACH_MM:.0f}-{MAX_ROBOT_REACH_MM:.0f} mm"
                )

        if dry_run:
            return

        robot_status = self._robot.ping()
        if not robot_status.ok:
            raise RuntimeError(
                f"Robot not ready: {robot_status.error or 'unknown error'}"
            )

    # ---- Calibration ----

    @staticmethod
    def _pose_is_origin(pose: PoseResult, tolerance: float = 1e-6) -> bool:
        return all(
            abs(value) <= tolerance for value in (pose.x, pose.y, pose.z, pose.r)
        )

    @property
    def is_calibrated(self) -> bool:
        return self._camera_vision.intrinsics_loaded and self._mapping_data is not None

    @property
    def calibration_robot_start(self) -> Waypoint | None:
        if not self._mapping_data:
            return None
        start_pose = self._mapping_data.get("start_pose") or {}
        return Waypoint(
            x=float(start_pose["x"]),
            y=float(start_pose["y"]),
            z=float(start_pose["z"]),
            r=float(start_pose["r"]),
        )

    @property
    def last_calibrated_at(self) -> str | None:
        if not self._mapping_data:
            return None
        return self._mapping_data.get("calibrated_at")

    def calibration_action(self, action: str) -> dict[str, object]:
        action = action.strip().lower()
        if action == "start":
            return self._start_calibration()
        if action == "capture":
            return self._capture_calibration_point()
        return self._calibration_response(
            ok=False,
            message=f"Unsupported calibration action: {action}",
            checkerboard_visible=False,
        )

    def _start_calibration(self) -> dict[str, object]:
        frame = self._camera_vision.get_latest_frame()
        if frame is None:
            return self._calibration_response(
                ok=False,
                message="No camera frame available",
                checkerboard_visible=False,
            )

        checkerboard = self._camera_vision.find_checkerboard(frame)
        if not checkerboard.ok:
            return self._calibration_response(
                ok=False,
                message=checkerboard.error or "Checkerboard not found",
                checkerboard_visible=False,
            )

        pose = self._robot.get_pose()
        if not pose.ok:
            return self._calibration_response(
                ok=False,
                message=f"Could not read robot pose: {pose.error}",
                checkerboard_visible=True,
            )
        if self._pose_is_origin(pose):
            return self._calibration_response(
                ok=False,
                message="Robot pose is still at origin (0, 0, 0, 0)",
                checkerboard_visible=True,
            )

        session = CalibrationSession(
            reference_image_base64=self._camera_vision.frame_to_base64(frame),
            targets=checkerboard.target_specs
            or [
                CalibrationTarget(
                    x=point.x,
                    y=point.y,
                    row=row,
                    col=col,
                    step=step,
                )
                for step, ((row, col), point) in enumerate(
                    zip(FIXED_CALIBRATION_POINTS, checkerboard.target_points),
                    start=1,
                )
            ],
            start_pose=Waypoint(x=pose.x, y=pose.y, z=pose.z, r=pose.r),
        )
        with self._calibration_lock:
            self._calibration_session = session

        return self._calibration_response(
            ok=True,
            message=(
                "Calibration started. Move the robot tip to "
                f"{session.targets[0].label} and press Capture Current Point."
            ),
            checkerboard_visible=True,
            session=session,
            include_reference=True,
        )

    def _capture_calibration_point(self) -> dict[str, object]:
        with self._calibration_lock:
            session = self._calibration_session

        if session is None:
            return self._calibration_response(
                ok=False,
                message="Calibration has not been started",
                checkerboard_visible=self._camera_vision.checkerboard_visible(),
            )

        pose = self._robot.get_pose()
        if not pose.ok:
            return self._calibration_response(
                ok=False,
                message=f"Could not read robot pose: {pose.error}",
                checkerboard_visible=self._camera_vision.checkerboard_visible(),
                session=session,
            )
        if self._pose_is_origin(pose):
            return self._calibration_response(
                ok=False,
                message="Robot pose is still at origin (0, 0, 0, 0)",
                checkerboard_visible=self._camera_vision.checkerboard_visible(),
                session=session,
            )

        session.captured_robot_points.append((pose.x, pose.y, pose.z))
        if session.current_step < TOTAL_CALIBRATION_STEPS:
            next_target = session.targets[session.current_step]
            return self._calibration_response(
                ok=True,
                message=(
                    f"Captured point {session.current_step}/{TOTAL_CALIBRATION_STEPS}. "
                    f"Move to {next_target.label} and press Capture Current Point."
                ),
                checkerboard_visible=self._camera_vision.checkerboard_visible(),
                session=session,
            )

        try:
            mapping = self._solve_and_store_calibration(session)
        except Exception as exc:
            logger.exception("Calibration solve failed: %s", exc)
            with self._calibration_lock:
                self._calibration_session = None
            return self._calibration_response(
                ok=False,
                message=f"Calibration solve failed: {exc}",
                checkerboard_visible=self._camera_vision.checkerboard_visible(),
            )

        with self._calibration_lock:
            self._mapping_data = mapping
            self._calibration_session = None

        return self._calibration_response(
            ok=True,
            message="Calibration completed",
            checkerboard_visible=self._camera_vision.checkerboard_visible(),
            current_step=TOTAL_CALIBRATION_STEPS,
            captured_targets=session.targets,
            calibrated=True,
            last_calibrated_at=mapping["calibrated_at"],
        )

    def _calibration_response(
        self,
        ok: bool,
        message: str,
        checkerboard_visible: bool,
        session: CalibrationSession | None = None,
        include_reference: bool = False,
        current_step: int | None = None,
        captured_points: list[tuple[float, float]] | None = None,
        captured_targets: list[CalibrationTarget] | None = None,
        calibrated: bool | None = None,
        last_calibrated_at: str | None = None,
    ) -> dict[str, object]:
        active_session = session or self._calibration_session
        if captured_targets is not None:
            captured = captured_targets
        elif captured_points is not None:
            captured = [
                CalibrationTarget(
                    x=point[0],
                    y=point[1],
                    row=row,
                    col=col,
                    step=step,
                )
                for step, ((row, col), point) in enumerate(
                    zip(FIXED_CALIBRATION_POINTS, captured_points),
                    start=1,
                )
            ]
        elif active_session is not None:
            captured = active_session.targets[: active_session.current_step]
        else:
            captured = []

        step = current_step
        if step is None:
            step = active_session.current_step if active_session else 0

        target_point: CalibrationTarget | None = None
        if active_session and active_session.current_step < TOTAL_CALIBRATION_STEPS:
            target_point = active_session.targets[active_session.current_step]

        response: dict[str, object] = {
            "ok": ok,
            "message": message,
            "checkerboardVisible": checkerboard_visible,
            "currentStep": step,
            "totalSteps": TOTAL_CALIBRATION_STEPS,
            "targetPoint": (
                {
                    "pixelX": target_point.x,
                    "pixelY": target_point.y,
                    "gridRow": target_point.row,
                    "gridCol": target_point.col,
                    "step": target_point.step,
                    "label": target_point.label,
                }
                if target_point is not None
                else None
            ),
            "capturedPoints": [
                {
                    "pixelX": point.x,
                    "pixelY": point.y,
                    "gridRow": point.row,
                    "gridCol": point.col,
                    "step": point.step,
                    "label": point.label,
                }
                for point in captured
            ],
            "calibrated": self.is_calibrated if calibrated is None else calibrated,
            "lastCalibratedAt": (
                self.last_calibrated_at
                if last_calibrated_at is None
                else last_calibrated_at
            ),
        }
        if include_reference and active_session is not None:
            response["referenceImageBase64"] = active_session.reference_image_base64
        return response

    def _solve_and_store_calibration(self, session: CalibrationSession) -> dict:
        import cv2
        import numpy as np

        if not self._camera_vision.intrinsics_loaded:
            raise RuntimeError(
                self._camera_vision.intrinsics_error or "Intrinsics missing"
            )

        image_points = np.array(
            [[target.x, target.y] for target in session.targets], dtype=np.float64
        ).reshape(-1, 1, 2)
        robot_points = np.array(
            session.captured_robot_points, dtype=np.float64
        ).reshape(-1, 3)
        success, rvec, tvec = cv2.solvePnP(
            robot_points,
            image_points,
            self._camera_vision.camera_matrix,
            self._camera_vision.dist_coeff,
        )
        if not success:
            raise RuntimeError("solvePnP failed")

        plane = self._build_plane_metadata(robot_points, rvec, tvec)

        calibrated_at = datetime.now(timezone.utc).isoformat()
        mapping = {
            "calibrated_at": calibrated_at,
            "intrinsics_path": self._camera_vision.intrinsics_path,
            "resolution": list(self._camera_vision.intrinsics_resolution or []),
            "checkerboard": {
                "inner_corners": list(self._camera_vision.checkerboard_size),
                "square_size_mm": self._camera_vision.checkerboard_square_mm,
                "fixed_points": [list(point) for point in FIXED_CALIBRATION_POINTS],
            },
            "image_points": [
                {
                    "row": target.row,
                    "col": target.col,
                    "pixelX": target.x,
                    "pixelY": target.y,
                }
                for target in session.targets
            ],
            "robot_points": [
                {
                    "row": row,
                    "col": col,
                    "robotX": point[0],
                    "robotY": point[1],
                    "robotZ": point[2],
                }
                for (row, col), point in zip(
                    FIXED_CALIBRATION_POINTS,
                    session.captured_robot_points,
                )
            ],
            "start_pose": {
                "x": session.start_pose.x,
                "y": session.start_pose.y,
                "z": session.start_pose.z,
                "r": session.start_pose.r,
            },
            "rvec": rvec.tolist(),
            "tvec": tvec.tolist(),
            "plane": plane,
        }

        self._mapping_path.parent.mkdir(parents=True, exist_ok=True)
        self._mapping_path.write_text(json.dumps(mapping, indent=4))
        return mapping

    def _load_mapping_file(self) -> dict | None:
        if not self._mapping_path.exists():
            return None
        try:
            data = json.loads(self._mapping_path.read_text())
            required = [
                "calibrated_at",
                "intrinsics_path",
                "resolution",
                "checkerboard",
                "image_points",
                "robot_points",
                "start_pose",
                "rvec",
                "tvec",
            ]
            for key in required:
                if key not in data:
                    raise ValueError(f"Missing mapping key: {key}")
            fixed_points = data.get("checkerboard", {}).get("fixed_points") or [
                list(point) for point in FIXED_CALIBRATION_POINTS
            ]
            if fixed_points != [list(point) for point in FIXED_CALIBRATION_POINTS]:
                raise ValueError("Unsupported checkerboard point order")
            if self._camera_vision.intrinsics_loaded:
                current_intrinsics_path = self._camera_vision.intrinsics_path
                if (
                    current_intrinsics_path
                    and data.get("intrinsics_path") != current_intrinsics_path
                ):
                    raise ValueError("Mapping intrinsics do not match current camera")
                expected_resolution = list(
                    self._camera_vision.intrinsics_resolution or []
                )
                if (
                    expected_resolution
                    and data.get("resolution") != expected_resolution
                ):
                    raise ValueError("Mapping resolution does not match intrinsics")
            return data
        except Exception as exc:
            logger.warning(
                "Ignoring invalid mapping file %s: %s", self._mapping_path, exc
            )
            return None

    def _build_plane_metadata(self, robot_points, rvec, tvec) -> dict[str, list[float]]:
        import cv2
        import numpy as np

        if len(robot_points) != TOTAL_CALIBRATION_STEPS:
            raise RuntimeError("Calibration requires four robot points")

        targets = [
            CalibrationTarget(
                x=0.0,
                y=0.0,
                row=row,
                col=col,
                step=step,
            )
            for step, (row, col) in enumerate(FIXED_CALIBRATION_POINTS, start=1)
        ]
        orientation = self._camera_vision._orientation_targets(targets)
        if orientation is None:
            raise RuntimeError("Calibration points do not define board orientation")

        origin_target, col_target, row_target = orientation
        robot_by_grid = {
            (target.row, target.col): np.array(robot_point, dtype=np.float64)
            for target, robot_point in zip(targets, robot_points)
        }

        origin = robot_by_grid[(origin_target.row, origin_target.col)]
        x_direction = robot_by_grid[(col_target.row, col_target.col)] - origin
        y_direction = robot_by_grid[(row_target.row, row_target.col)] - origin

        x_norm = np.linalg.norm(x_direction)
        y_direction = (
            y_direction
            - (np.dot(y_direction, x_direction) / max(x_norm**2, 1e-12)) * x_direction
        )
        y_norm = np.linalg.norm(y_direction)

        if x_norm <= 1e-9 or y_norm <= 1e-9:
            raise RuntimeError("Calibration points do not define a stable board plane")

        x_axis = x_direction / x_norm
        y_axis = y_direction / y_norm
        normal = np.cross(x_axis, y_axis)
        normal_norm = np.linalg.norm(normal)
        if normal_norm <= 1e-9:
            raise RuntimeError("Calibration plane is degenerate")
        normal = normal / normal_norm

        rotation, _ = cv2.Rodrigues(np.array(rvec, dtype=np.float64))
        tvec_array = np.array(tvec, dtype=np.float64).reshape(3, 1)
        camera_origin = (-rotation.T @ tvec_array).reshape(3)
        if np.dot(normal, camera_origin - origin) < 0:
            normal = -normal

        return {
            "origin": origin.tolist(),
            "x_axis": x_axis.tolist(),
            "y_axis": y_axis.tolist(),
            "normal": normal.tolist(),
        }

    def _plane_geometry(self) -> tuple[object, object, object]:
        import cv2
        import numpy as np

        if not self.is_calibrated or not self._mapping_data:
            raise RuntimeError("Not calibrated")

        rvec = np.array(self._mapping_data["rvec"], dtype=np.float64)
        tvec = np.array(self._mapping_data["tvec"], dtype=np.float64).reshape(3, 1)
        rotation, _ = cv2.Rodrigues(rvec)
        camera_origin = (-rotation.T @ tvec).reshape(3)

        plane_meta = self._mapping_data.get("plane") or {}
        if plane_meta:
            origin = np.array(plane_meta["origin"], dtype=np.float64)
            normal = np.array(plane_meta["normal"], dtype=np.float64)
        else:
            robot_points = np.array(
                [
                    [
                        point["robotX"],
                        point["robotY"],
                        point["robotZ"],
                    ]
                    for point in self._mapping_data["robot_points"]
                ],
                dtype=np.float64,
            )
            plane_meta = self._build_plane_metadata(robot_points, rvec, tvec)
            origin = np.array(plane_meta["origin"], dtype=np.float64)
            normal = np.array(plane_meta["normal"], dtype=np.float64)

        if np.dot(normal, camera_origin - origin) < 0:
            normal = -normal

        return rotation, camera_origin, (origin, normal)

    def _plane_point_from_pixel(
        self, px: float, py: float
    ) -> tuple[float, float, float]:
        import cv2
        import numpy as np

        if not self.is_calibrated or not self._mapping_data:
            raise RuntimeError("Not calibrated")

        undistorted = cv2.undistortPoints(
            np.array([[[px, py]]], dtype=np.float64),
            self._camera_vision.camera_matrix,
            self._camera_vision.dist_coeff,
        )
        ray_camera = np.array(
            [undistorted[0][0][0], undistorted[0][0][1], 1.0],
            dtype=np.float64,
        )

        rotation, camera_origin, plane = self._plane_geometry()
        origin, normal = plane
        ray_world = (rotation.T @ ray_camera.reshape(3, 1)).reshape(3)

        denominator = float(np.dot(normal, ray_world))
        if abs(denominator) <= 1e-9:
            raise RuntimeError("Pixel ray does not intersect calibration plane")

        scale = float(np.dot(normal, origin - camera_origin) / denominator)
        if scale <= 0:
            raise RuntimeError("Pixel ray intersects behind the camera")

        point = camera_origin + (ray_world * scale)
        return (float(point[0]), float(point[1]), float(point[2]))

    def pixel_to_robot(
        self, px: float, py: float, work_z: float, work_r: float
    ) -> Waypoint:
        plane_point = self._plane_point_from_pixel(px, py)
        return Waypoint(
            x=plane_point[0],
            y=plane_point[1],
            z=work_z,
            r=work_r,
        )

    def _distance_from_start(self, px: float, py: float) -> float:
        start = self.calibration_robot_start
        if start is None:
            raise RuntimeError("Not calibrated")
        plane_point = self._plane_point_from_pixel(px, py)
        return math.hypot(plane_point[0] - start.x, plane_point[1] - start.y)

    def _normalize_corners_clockwise_start_nearest(
        self,
        corners: list[tuple[float, float]],
    ) -> list[tuple[float, float]]:
        if len(corners) < 2:
            return list(corners)

        center_x = sum(x for x, _ in corners) / len(corners)
        center_y = sum(y for _, y in corners) / len(corners)
        ordered = sorted(
            corners,
            key=lambda point: math.atan2(point[1] - center_y, point[0] - center_x),
        )
        nearest_index = min(
            range(len(ordered)),
            key=lambda index: self._distance_from_start(
                ordered[index][0], ordered[index][1]
            ),
        )
        return ordered[nearest_index:] + ordered[:nearest_index]

    def populate_pixel_path_from_batteries(
        self,
        batteries: list[list[tuple[float, float]]],
        measuring_points_per_cm: float,
    ) -> list[dict[str, float | int | str]]:
        import numpy as np

        if not self.is_calibrated:
            raise RuntimeError("Not calibrated")
        if measuring_points_per_cm <= 0:
            raise ValueError("measuring_points_per_cm must be > 0")
        if measuring_points_per_cm > MAX_MEASURING_POINTS_PER_CM:
            raise ValueError(
                f"measuring_points_per_cm must be <= {MAX_MEASURING_POINTS_PER_CM}"
            )

        step_mm = 10.0 / measuring_points_per_cm
        ordered_batteries: list[tuple[float, list[tuple[float, float]]]] = []

        for battery in batteries:
            clean = [(float(x), float(y)) for x, y in battery]
            if len(clean) < 2:
                continue
            normalized = self._normalize_corners_clockwise_start_nearest(clean)
            nearest_distance = min(
                self._distance_from_start(x, y) for x, y in normalized
            )
            ordered_batteries.append((nearest_distance, normalized))

        ordered_batteries.sort(key=lambda item: item[0])

        path: list[dict[str, float | int | str]] = []
        for battery_number, (_distance, corners) in enumerate(ordered_batteries):
            corner_count = len(corners)
            for corner_index in range(corner_count):
                x1, y1 = corners[corner_index]
                x2, y2 = corners[(corner_index + 1) % corner_count]
                point_a = np.array(self._plane_point_from_pixel(x1, y1))
                point_b = np.array(self._plane_point_from_pixel(x2, y2))
                edge_length_mm = float(np.linalg.norm(point_b - point_a))
                if edge_length_mm == 0:
                    continue

                sample_count = max(1, int(math.ceil(edge_length_mm / step_mm)))
                if len(path) + sample_count > MAX_POPULATED_PATH_POINTS:
                    raise ValueError(
                        "Requested path is too dense; reduce measuringPointsPerCm or battery count"
                    )

                for measurement_index in range(sample_count):
                    t = measurement_index / sample_count
                    pixel_x = x1 + ((x2 - x1) * t)
                    pixel_y = y1 + ((y2 - y1) * t)
                    path.append(
                        {
                            "index": f"{battery_number}-{corner_index}-{measurement_index}",
                            "batteryNr": battery_number,
                            "cornerIndex": corner_index,
                            "measurementIndex": measurement_index,
                            "pixelX": pixel_x,
                            "pixelY": pixel_y,
                        }
                    )

        return path

    def detect_path(self) -> DetectionResults:
        return self._camera_vision.detect_latest()

    @property
    def camera_vision(self) -> CameraVisionAdapter:
        return self._camera_vision

    def latest_result(self) -> dict | None:
        return None

    # ---- WEBSOCKET SERVICES ----

    async def initialize_dms(self) -> None:
        await self._dms.initialize_websocket()
        self._dms.on_event("scan.resultsProcessed", self._handle_scan_results_processed)
        self._dms.on_event("scan.stopped", self._handle_scan_stopped)

    async def _close_dms(self) -> None:
        await self._dms.disconnect_websocket()
        self._dms.off_event(
            "scan.resultsProcessed", self._handle_scan_results_processed
        )
        self._dms.off_event("scan.stopped", self._handle_scan_stopped)

    async def _handle_scan_results_processed(self, data: dict) -> None:
        logger.info("Scan results have been processed: %s", data.get("body"))

    async def _handle_scan_stopped(self, data: dict) -> None:
        logger.info("Scan has been stopped: %s", data.get("body"))

    async def _handle_error(self, data: dict) -> None:
        logger.warning("An error occurred: %s", data.get("code"))
