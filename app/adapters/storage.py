"""SQLite-backed storage adapter."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from app.adapters.database import Database
from app.domain.models import Job, Measurement, Waypoint


class StorageAdapter:
    def __init__(self, db: Database) -> None:
        self._db = db

    # ---- Jobs ----

    def save_job(self, job: Job) -> None:
        """Insert or replace a full job (with waypoints)."""
        with self._db.locked():
            self._db.execute(
                """INSERT OR REPLACE INTO jobs
                   (id, options, dry_run, state, error,
                    last_point_processed, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    job.id,
                    json.dumps(job.options) if job.options else None,
                    int(job.dry_run),
                    job.state,
                    job.error,
                    job.last_point_processed,
                    (
                        job.created_at.isoformat()
                        if hasattr(job.created_at, "isoformat")
                        else str(job.created_at)
                    ),
                    (
                        job.updated_at.isoformat()
                        if hasattr(job.updated_at, "isoformat")
                        else str(job.updated_at)
                    ),
                ),
            )
            # Clear old waypoints and re-insert
            self._db.execute("DELETE FROM waypoints WHERE job_id = ?", (job.id,))
            if job.path:
                self._db.executemany(
                    "INSERT INTO waypoints "
                    "(job_id, seq, x, y, z, r, index_label, battery_nr, corner_index, measurement_index) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    [
                        (
                            job.id,
                            i,
                            w.x,
                            w.y,
                            w.z,
                            w.r,
                            w.index,
                            w.battery_nr,
                            w.corner_index,
                            w.measurement_index,
                        )
                        for i, w in enumerate(job.path)
                    ],
                )
            self._db.commit()

    def update_job_state(
        self,
        job_id: str,
        state: str,
        last_point_processed: int,
        error: str | None = None,
    ) -> None:
        with self._db.locked():
            self._db.execute(
                """UPDATE jobs SET state = ?, last_point_processed = ?,
                   error = ?, updated_at = ? WHERE id = ?""",
                (
                    state,
                    last_point_processed,
                    error,
                    datetime.now(timezone.utc).isoformat(),
                    job_id,
                ),
            )
            self._db.commit()

    def get_job(self, job_id: str) -> Job | None:
        with self._db.locked():
            row = self._db.fetchone("SELECT * FROM jobs WHERE id = ?", (job_id,))
            if not row:
                return None
            return self._row_to_job(row)

    def list_jobs(self) -> list[Job]:
        with self._db.locked():
            rows = self._db.fetchall("SELECT * FROM jobs ORDER BY created_at ASC")
            return [self._row_to_job(r) for r in rows]

    def latest_job(self) -> Job | None:
        with self._db.locked():
            row = self._db.fetchone(
                "SELECT * FROM jobs ORDER BY created_at DESC, updated_at DESC, rowid DESC LIMIT 1"
            )
            if not row:
                return None
            return self._row_to_job(row)

    def delete_job(self, job_id: str) -> bool:
        with self._db.locked():
            cur = self._db.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
            self._db.commit()
            return cur.rowcount > 0

    def prune_jobs(self, max_jobs: int) -> list[str]:
        """Delete the oldest jobs so that at most *max_jobs* remain.

        Jobs are ordered by ``created_at`` ascending; the oldest ones are
        removed first.  Cascade constraints on the ``waypoints``,
        ``measurements``, and ``job_images`` tables ensure all child rows
        are deleted automatically.

        Parameters
        ----------
        max_jobs:
            Maximum number of jobs to retain.  Values ≤ 0 are a no-op.

        Returns
        -------
        list[str]
            IDs of the jobs that were deleted.
        """
        if max_jobs <= 0:
            return []
        count_row = self._db.fetchone("SELECT COUNT(*) AS n FROM jobs")
        total_jobs = int(count_row["n"]) if count_row else 0
        excess = total_jobs - max_jobs
        if excess <= 0:
            return []

        oldest_rows = self._db.fetchall(
            "SELECT id FROM jobs ORDER BY created_at ASC LIMIT ?",
            (excess,),
        )
        to_delete = [r["id"] for r in oldest_rows]
        if not to_delete:
            return []

        placeholders = ",".join("?" for _ in to_delete)
        self._db.execute(
            f"DELETE FROM jobs WHERE id IN ({placeholders})",
            tuple(to_delete),
        )
        self._db.commit()
        return to_delete

    # ---- Measurements ----

    def save_measurement(self, job_id: str, m: Measurement) -> None:
        with self._db.locked():
            self._db.execute(
                """INSERT INTO measurements
                   (job_id, waypoint_index, x, y, z, r, pixel_x, pixel_y,
                    scan_result, simulated, timestamp)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    job_id,
                    m.waypoint_index,
                    m.waypoint.x,
                    m.waypoint.y,
                    m.waypoint.z,
                    m.waypoint.r,
                    m.pixel_x,
                    m.pixel_y,
                    json.dumps(m.scan_result) if m.scan_result else None,
                    int(m.simulated),
                    m.timestamp,
                ),
            )
            self._db.commit()

    def get_measurements(self, job_id: str) -> list[Measurement]:
        with self._db.locked():
            rows = self._db.fetchall(
                "SELECT * FROM measurements WHERE job_id = ? ORDER BY waypoint_index ASC",
                (job_id,),
            )
            return [
                Measurement(
                    waypoint_index=r["waypoint_index"],
                    waypoint=Waypoint(x=r["x"], y=r["y"], z=r["z"], r=r["r"]),
                    pixel_x=r["pixel_x"],
                    pixel_y=r["pixel_y"],
                    scan_result=(
                        json.loads(r["scan_result"]) if r["scan_result"] else None
                    ),
                    simulated=bool(r["simulated"]),
                    timestamp=r["timestamp"],
                )
                for r in rows
            ]

    # ---- Images ----

    def save_job_image(
        self,
        job_id: str,
        image_bytes: bytes,
        content_type: str = "image/jpeg",
    ) -> None:
        with self._db.locked():
            self._db.execute(
                """INSERT INTO job_images (job_id, image, content_type)
                   VALUES (?, ?, ?)
                   ON CONFLICT(job_id) DO UPDATE SET image = excluded.image,
                                                     content_type = excluded.content_type""",
                (job_id, image_bytes, content_type),
            )
            self._db.commit()

    def get_job_image(self, job_id: str) -> bytes | None:
        with self._db.locked():
            row = self._db.fetchone(
                "SELECT image FROM job_images WHERE job_id = ?",
                (job_id,),
            )
            if not row:
                return None
            return row["image"]

    # ---- internal ----

    def _row_to_job(self, row: sqlite3.Row) -> Job:
        job_id = row["id"]
        # Waypoints
        wp_rows = self._db.fetchall(
            "SELECT * FROM waypoints WHERE job_id = ? ORDER BY seq ASC", (job_id,)
        )
        path = [
            Waypoint(
                x=w["x"],
                y=w["y"],
                z=w["z"],
                r=w["r"],
                index=w["index_label"],
                battery_nr=w["battery_nr"],
                corner_index=w["corner_index"],
                measurement_index=w["measurement_index"],
            )
            for w in wp_rows
        ]

        # Measurements
        measurements = self.get_measurements(job_id)

        return Job(
            id=job_id,
            options=json.loads(row["options"]) if row["options"] else None,
            path=path,
            dry_run=bool(row["dry_run"]),
            measurements=measurements,
            state=row["state"],
            last_point_processed=row["last_point_processed"],
            error=row["error"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )
