# Database Documentation

## Overview

Nenabot uses a **SQLite** database for all persistent state. The stdlib `sqlite3` module is used directly — no ORM.

The database file is created automatically at startup at `data/nenabot.db` (configurable via `db_path` in `app/dependencies.py`). When running in Docker the `data/` directory is a named volume so the database survives container restarts.

## Connection settings

| Setting             | Value    | Reason                                                                                    |
| :------------------ | :------- | :---------------------------------------------------------------------------------------- |
| Journal mode        | WAL      | Allows concurrent reads (API thread) while the background job thread writes               |
| `check_same_thread` | `False`  | Required because FastAPI request handlers and background job threads share the connection |
| Foreign keys        | ON       | Enforces referential integrity; enables cascade deletes                                   |
| Isolation level     | DEFERRED | Default SQLite behaviour; explicit `commit()` calls control transaction boundaries        |

## Schema

Four tables are created by `Database.init_db()`:

### `jobs`

Stores job metadata and current state.

| Column                 | Type    | Constraints                   | Description                                                    |
| :--------------------- | :------ | :---------------------------- | :------------------------------------------------------------- |
| `id`                   | TEXT    | PRIMARY KEY                   | UUID generated at job creation                                 |
| `options`              | TEXT    | nullable                      | JSON-encoded dict of job options                               |
| `dry_run`              | INTEGER | NOT NULL, default 0           | 1 = simulated run (no robot/DMS)                               |
| `state`                | TEXT    | NOT NULL, default `'created'` | One of: `created`, `running`, `completed`, `failed`, `stopped` |
| `error`                | TEXT    | nullable                      | Error message if `state = 'failed'`                            |
| `last_point_processed` | INTEGER | NOT NULL, default 0           | Number of waypoints completed so far                           |
| `created_at`           | TEXT    | NOT NULL                      | ISO-8601 timestamp                                             |
| `updated_at`           | TEXT    | NOT NULL                      | ISO-8601 timestamp, updated on every state change              |

### `waypoints`

Ordered list of XYZ+R waypoints that define the job path.

| Column   | Type    | Constraints                                 | Description                  |
| :------- | :------ | :------------------------------------------ | :--------------------------- |
| `id`     | INTEGER | PRIMARY KEY AUTOINCREMENT                   | Internal row id              |
| `job_id` | TEXT    | NOT NULL, FK → `jobs(id)` ON DELETE CASCADE | Parent job                   |
| `seq`    | INTEGER | NOT NULL                                    | 0-based position in the path |
| `x`      | REAL    | NOT NULL                                    | X coordinate                 |
| `y`      | REAL    | NOT NULL                                    | Y coordinate                 |
| `z`      | REAL    | NOT NULL, default 0                         | Z coordinate                 |
| `r`      | REAL    | NOT NULL, default 0                         | Rotation (degrees)           |

### `measurements`

One row per completed waypoint, recorded during job execution.

| Column           | Type    | Constraints                                 | Description                       |
| :--------------- | :------ | :------------------------------------------ | :-------------------------------- |
| `id`             | INTEGER | PRIMARY KEY AUTOINCREMENT                   | Internal row id                   |
| `job_id`         | TEXT    | NOT NULL, FK → `jobs(id)` ON DELETE CASCADE | Parent job                        |
| `waypoint_index` | INTEGER | NOT NULL                                    | 0-based index into the job path   |
| `x`              | REAL    | NOT NULL                                    | Waypoint X at time of measurement |
| `y`              | REAL    | NOT NULL                                    | Waypoint Y                        |
| `z`              | REAL    | NOT NULL, default 0                         | Waypoint Z                        |
| `r`              | REAL    | NOT NULL, default 0                         | Waypoint R                        |
| `scan_result`    | TEXT    | nullable                                    | JSON-encoded DMS scan payload     |
| `simulated`      | INTEGER | NOT NULL, default 0                         | 1 = dry-run measurement           |
| `timestamp`      | TEXT    | nullable                                    | ISO-8601 timestamp of measurement |

### `job_images`

Stores a single annotated overlay image per job (JPEG BLOB).

| Column         | Type    | Constraints                                         | Description      |
| :------------- | :------ | :-------------------------------------------------- | :--------------- |
| `id`           | INTEGER | PRIMARY KEY AUTOINCREMENT                           | Internal row id  |
| `job_id`       | TEXT    | NOT NULL, UNIQUE, FK → `jobs(id)` ON DELETE CASCADE | Parent job       |
| `image`        | BLOB    | NOT NULL                                            | JPEG image bytes |
| `content_type` | TEXT    | NOT NULL, default `'image/jpeg'`                    | MIME type        |

## Cascade deletes

All child tables (`waypoints`, `measurements`, `job_images`) use `ON DELETE CASCADE` on their `job_id` foreign key. Deleting a job via `DELETE /jobs/{id}` removes all related rows automatically.

## Code organisation

| Module                     | Class                   | Responsibility                                                                                                |
| :------------------------- | :---------------------- | :------------------------------------------------------------------------------------------------------------ |
| `app/adapters/database.py` | `Database`              | Connection lifecycle, schema creation, raw SQL helpers (`execute`, `fetchone`, `fetchall`, `commit`)          |
| `app/adapters/storage.py`  | `StorageAdapter`        | Domain-level CRUD — accepts/returns `Job`, `Measurement`, `Waypoint` dataclasses. Handles JSON serialisation. |
| `app/dependencies.py`      | `create_orchestrator()` | Instantiates `Database`, calls `init_db()`, passes it to `StorageAdapter`                                     |

### Typical call flow

```
Route handler
  → OrchestratorService.create_job()
    → StorageAdapter.save_job(job)
      → Database.execute(INSERT INTO jobs …)
      → Database.executemany(INSERT INTO waypoints …)
      → Database.commit()
```

## Job images

When a job is created with an attached camera frame (`image_base64` in the POST body), the clean snapshot is stored as a BLOB in `job_images`. No server-side annotations are drawn on the image — measurement points are rendered by the frontend using pixel coordinates from the measurement data.

The image can be retrieved via `GET /api/job/{id}/image` (returns raw JPEG).

## Backup and migration

The database is a single file (`data/nenabot.db`). To back up:

```bash
sqlite3 data/nenabot.db ".backup backup.db"
```

There is currently no schema migration tool. The `CREATE TABLE IF NOT EXISTS` statements in `init_db()` ensure forward compatibility for fresh installs. For schema changes on an existing database, write a migration script or recreate the database.

## Testing

Tests use a temporary SQLite database per test function via pytest's `tmp_path` fixture:

```python
db = Database(db_path=str(tmp_path / "test.db"))
db.init_db()
store = StorageAdapter(db=db)
```

This ensures full isolation between tests with no cleanup needed.
