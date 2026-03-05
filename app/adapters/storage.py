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
        self._db.execute(
            """INSERT OR REPLACE INTO jobs
               (id, options, dry_run, state, log, error,
                last_point_processed, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                job.id,
                json.dumps(job.options) if job.options else None,
                int(job.dry_run),
                job.state,
                job.log,
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
                "(job_id, seq, x, y, z, r) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                [(job.id, i, w.x, w.y, w.z, w.r) for i, w in enumerate(job.path)],
            )
        self._db.commit()

    def update_job_state(
        self,
        job_id: str,
        state: str,
        last_point_processed: int,
        error: str | None = None,
    ) -> None:
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
        row = self._db.fetchone("SELECT * FROM jobs WHERE id = ?", (job_id,))
        if not row:
            return None
        return self._row_to_job(row)

    def list_jobs(self) -> list[Job]:
        rows = self._db.fetchall("SELECT * FROM jobs ORDER BY created_at ASC")
        return [self._row_to_job(r) for r in rows]

    def latest_job(self) -> Job | None:
        row = self._db.fetchone("SELECT * FROM jobs ORDER BY created_at DESC LIMIT 1")
        if not row:
            return None
        return self._row_to_job(row)

    def delete_job(self, job_id: str) -> bool:
        cur = self._db.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
        self._db.commit()
        return cur.rowcount > 0

    # ---- Measurements ----

    def save_measurement(self, job_id: str, m: Measurement) -> None:
        self._db.execute(
            """INSERT INTO measurements
               (job_id, waypoint_index, x, y, z, r, scan_result, simulated, timestamp)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                job_id,
                m.waypoint_index,
                m.waypoint.x,
                m.waypoint.y,
                m.waypoint.z,
                m.waypoint.r,
                json.dumps(m.scan_result) if m.scan_result else None,
                int(m.simulated),
                m.timestamp,
            ),
        )
        self._db.commit()

    def get_measurements(self, job_id: str) -> list[Measurement]:
        rows = self._db.fetchall(
            "SELECT * FROM measurements WHERE job_id = ? ORDER BY waypoint_index ASC",
            (job_id,),
        )
        return [
            Measurement(
                waypoint_index=r["waypoint_index"],
                waypoint=Waypoint(x=r["x"], y=r["y"], z=r["z"], r=r["r"]),
                scan_result=json.loads(r["scan_result"]) if r["scan_result"] else None,
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
        self._db.execute(
            """INSERT OR REPLACE INTO job_images (job_id, image, content_type)
               VALUES (?, ?, ?)""",
            (job_id, image_bytes, content_type),
        )
        self._db.commit()

    def get_job_image(self, job_id: str) -> bytes | None:
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
        path = [Waypoint(x=w["x"], y=w["y"], z=w["z"], r=w["r"]) for w in wp_rows]

        # Measurements
        measurements = self.get_measurements(job_id)

        return Job(
            id=job_id,
            options=json.loads(row["options"]) if row["options"] else None,
            path=path,
            dry_run=bool(row["dry_run"]),
            log=row["log"],
            measurements=measurements,
            state=row["state"],
            last_point_processed=row["last_point_processed"],
            error=row["error"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )
