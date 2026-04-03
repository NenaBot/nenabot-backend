"""Thin wrapper around sqlite3 for the nenabot application database."""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path


class Database:
    """Thread-safe SQLite wrapper.

    Uses WAL journal mode so the background job thread can write while
    the FastAPI request thread reads concurrently.
    """

    def __init__(self, db_path: str = "data/nenabot.db") -> None:
        self._db_path = db_path
        self._conn: sqlite3.Connection | None = None
        self._lock = threading.RLock()

    # ---- lifecycle ----

    def connect(self) -> None:
        with self._lock:
            if self._conn is not None:
                return
            # Ensure parent directory exists (unless :memory:)
            if self._db_path != ":memory:":
                Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(
                self._db_path,
                check_same_thread=False,
                isolation_level="DEFERRED",
            )
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")

    def close(self) -> None:
        with self._lock:
            if self._conn:
                self._conn.close()
                self._conn = None

    @property
    def conn(self) -> sqlite3.Connection:
        with self._lock:
            if self._conn is None:
                self.connect()
            return self._conn

    @contextmanager
    def locked(self):
        """Serialize access to the shared SQLite connection."""
        with self._lock:
            yield

    # ---- helpers ----

    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        with self._lock:
            return self.conn.execute(sql, params)

    def executemany(self, sql: str, seq: list[tuple]) -> sqlite3.Cursor:
        with self._lock:
            return self.conn.executemany(sql, seq)

    def fetchone(self, sql: str, params: tuple = ()) -> sqlite3.Row | None:
        with self._lock:
            return self.conn.execute(sql, params).fetchone()

    def fetchall(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self.conn.execute(sql, params).fetchall()

    def commit(self) -> None:
        with self._lock:
            self.conn.commit()

    # ---- schema ----

    def init_db(self) -> None:
        """Create tables if they don't already exist."""
        with self._lock:
            self.connect()
            self.conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id            TEXT PRIMARY KEY,
                    options       TEXT,
                    dry_run       INTEGER NOT NULL DEFAULT 0,
                    state         TEXT NOT NULL DEFAULT 'created',
                    error         TEXT,
                    last_point_processed INTEGER NOT NULL DEFAULT 0,
                    created_at    TEXT NOT NULL,
                    updated_at    TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS waypoints (
                    id      INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id  TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                    seq     INTEGER NOT NULL,
                    x       REAL NOT NULL,
                    y       REAL NOT NULL,
                    z       REAL NOT NULL DEFAULT 0,
                    r       REAL NOT NULL DEFAULT 0,
                    index_label TEXT,
                    battery_nr INTEGER,
                    corner_index INTEGER,
                    measurement_index INTEGER
                );

                CREATE TABLE IF NOT EXISTS measurements (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id          TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                    waypoint_index  INTEGER NOT NULL,
                    x               REAL NOT NULL,
                    y               REAL NOT NULL,
                    z               REAL NOT NULL DEFAULT 0,
                    r               REAL NOT NULL DEFAULT 0,
                    pixel_x         REAL,
                    pixel_y         REAL,
                    scan_result     TEXT,
                    simulated       INTEGER NOT NULL DEFAULT 0,
                    timestamp       TEXT
                );

                CREATE TABLE IF NOT EXISTS job_images (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id        TEXT NOT NULL UNIQUE
                                  REFERENCES jobs(id) ON DELETE CASCADE,
                    image         BLOB NOT NULL,
                    content_type  TEXT NOT NULL DEFAULT 'image/jpeg'
                );
                """
            )
            self.commit()

            # Migrate existing databases: add pixel_x/pixel_y if missing
            try:
                self.conn.execute("ALTER TABLE measurements ADD COLUMN pixel_x REAL")
                self.conn.execute("ALTER TABLE measurements ADD COLUMN pixel_y REAL")
                self.commit()
            except sqlite3.OperationalError:
                pass  # columns already exist

            # Migrate existing databases: add waypoint index metadata if missing
            for ddl in (
                "ALTER TABLE waypoints ADD COLUMN index_label TEXT",
                "ALTER TABLE waypoints ADD COLUMN battery_nr INTEGER",
                "ALTER TABLE waypoints ADD COLUMN corner_index INTEGER",
                "ALTER TABLE waypoints ADD COLUMN measurement_index INTEGER",
            ):
                try:
                    self.conn.execute(ddl)
                    self.commit()
                except sqlite3.OperationalError:
                    pass  # column already exists
