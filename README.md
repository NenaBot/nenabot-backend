# nenabot-main

Repo for hosting Hardware Controls and Machine Vision code

# Orchestrator (Initial Template)

Minimal FastAPI-based orchestrator that follows the planning document. Vision, camera, and robot integrations are in-process adapters (no per-module HTTP). DMS is accessed over HTTP.

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

OpenAPI spec is generated from the controllers and available at:

- http://127.0.0.1:8000/openapi.json
- http://127.0.0.1:8000/docs

## Running with Docker

```bash
# Build the image
docker build -t nenabot .

# Run (database is persisted in a named volume)
docker run -d --name nenabot \
  -p 8000:8000 \
  -v nenabot-data:/app/data \
  nenabot
```

The SQLite database (`data/nenabot.db`) is created automatically on first startup. The `nenabot-data` volume ensures it survives container restarts and rebuilds.

To stop and remove:

```bash
docker stop nenabot && docker rm nenabot
```

## Architecture overview

For the full system architecture (layer breakdown, folder tree, and dependency diagram), see:

- [Architecture Overview](docs/architecture-overview.md)
- [Database Documentation](docs/database.md)
- [Raspberry Pi Remote Access](docs/raspberry-pi-setup.md)
- [IonVision Integration Tests](docs/IonVision/ionVision.md)

## Endpoints

- `GET /health`
- `GET /status`
- `GET /jobs`
- `GET /jobs/{id}`
- `GET /jobs/{id}/image` — clean base JPEG snapshot
- `GET /jobs/{id}/events` — SSE stream of real-time job progress events
- `GET /jobs/latest`
- `GET /profiles`
- `GET /profiles/default`
- `GET /robot/pose` — current end-effector position and joint angles
- `GET /streams/camera/feed` — raw camera MJPEG stream
- `GET /streams/detection/feed` — detection overlay MJPEG stream
- `POST /jobs`
- `POST /robot/stop` — halt active job
- `POST /robot/move` — move robot to specific position (calibration)
- `POST /paths` — detect path and battery contours
- `DELETE /jobs/{id}`

## Configuration

The following environment variables control nenabot's runtime behaviour.

| Variable | Default | Description |
| :--- | :--- | :--- |
| `IONVISION_BASE_URL` / `NENABOT_DMS_BASE_URL` | `http://localhost:8080` | HTTP base URL of the IonVision DMS device |
| `IONVISION_WS_BASE_URL` / `NENABOT_DMS_WS_BASE_URL` | derived from HTTP URL | WebSocket base URL of the IonVision DMS device |
| `NENABOT_MAX_JOBS` | *(unset — unlimited)* | Maximum number of jobs to retain. When set to a positive integer, the oldest jobs beyond this limit are automatically deleted at the end of every job execution. Both the database records (job, waypoints, measurements, snapshot image) and the captured JPEG files in `data/images/` are cleaned up. Set this to a small number (e.g. `10`) on memory-constrained devices to prevent unbounded disk and SQLite growth. |

Example Docker run with a 10-job retention limit:

```bash
docker run -d --name nenabot \
  -p 8000:8000 \
  -v nenabot-data:/app/data \
  -e NENABOT_MAX_JOBS=10 \
  nenabot
```

## Hardware integration notes

- **Dobot**: `app/adapters/robot.py` wraps `DobotDllTypeMulti`. Supports both automated job execution and manual control via `/robot/move` and `/robot/pose` endpoints for calibration testing.
- **Camera/Vision**: `app/adapters/camera_vision.py` handles ArUco marker detection, battery-contour detection, and MJPEG streaming via `/streams/camera/feed` and `/streams/detection/feed`.
- **IonVision (DMS)**: `app/adapters/ionVision.py` is an HTTP client to the external IonVision API. Configure the base URL with `IONVISION_BASE_URL` / `IONVISION_WS_BASE_URL` or in `app/dependencies.py`.
- **Database**: SQLite (`data/nenabot.db`) stores all job state, waypoints, measurements, and snapshot images. See [Database Documentation](docs/database.md).

## UI pages

| Page          | URL                                    | Description                               |
| :------------ | :------------------------------------- | :---------------------------------------- |
| OpenAPI docs  | `/docs`                                | Auto-generated interactive API reference  |
| Job Tester    | Open `docs/job-tester.html` locally    | Create and monitor jobs                   |
| Job Results   | Open `docs/job-results.html` locally   | Browse jobs, view images and measurements |
| Stream Viewer | Open `docs/stream-viewer.html` locally | Live camera / detection stream viewer     |

## Tests

```bash
pytest -q
```

CI runs only unit tests. Hardware/integration tests are excluded via `-m "not hardware and not integration"` and must be run manually when connected to the devices.

### Robot arm hardware tests

```bash
RUN_ROBOT_HARDWARE_TESTS=1 pytest -s -v tests/test_robot_hardware.py
```

| Variable                     | Default | Description                                                                   |
| :--------------------------- | :------ | :---------------------------------------------------------------------------- |
| `RUN_ROBOT_HARDWARE_TESTS`   | —       | Set to `1` to enable the suite                                                |
| `DOBOT_ENABLE_LEGACY_HOMING` | `0`     | Set to `1` to use legacy `SetHOMECmd` (only if `SetHOMECmdEx` is unavailable) |

For full details see [`docs/robot.md`](docs/robot.md).

### IonVision hardware tests

Defaults to `http://192.168.1.109/api` / `ws://192.168.1.109/socket`. Override with env vars:

```bash
IONVISION_RUN_HARDWARE_TESTS=1 pytest -s -v tests/test_ionvision_hardware.py
```

Key env vars (all optional — hardcoded defaults are used if not set):

| Variable                                     | Default                     | Description                                      |
| :------------------------------------------- | :-------------------------- | :----------------------------------------------- |
| `IONVISION_BASE_URL`                         | `http://192.168.1.109/api`  | IonVision HTTP base URL                          |
| `IONVISION_WS_BASE_URL`                      | `ws://192.168.1.109/socket` | WebSocket URL (derived from base URL if omitted) |
| `IONVISION_REQUEST_TIMEOUT_S`                | `10.0`                      | Per-request timeout                              |
| `IONVISION_ENABLE_MUTATION_TESTS`            | `true`                      | Allow scan start/stop and comment writes         |
| `IONVISION_RUN_WS_TEST`                      | `true`                      | Enable WebSocket tests                           |
| `IONVISION_SCAN_RESULTS_PROCESSED_TIMEOUT_S` | `120.0`                     | How long to wait for `scan.resultsProcessed`     |

For full details see [`docs/ionVision.md`](docs/ionVision.md).

# GitHub Workflow & Contribution Guidelines

This section outlines the standards for branching, committing, and managing Pull Requests within this repository.

---

## 1. Branch Naming Conventions

Always use a prefix that describes the intent of your work. Use **kebab-case** (all lowercase, hyphens as separators).

| Prefix      | Purpose                                                       | Example              |
| :---------- | :------------------------------------------------------------ | :------------------- |
| `feat/`     | A new feature or enhancement                                  | `feat/user-login`    |
| `fix/`      | A bug fix                                                     | `fix/broken-button`  |
| `docs/`     | Documentation changes                                         | `docs/update-readme` |
| `refactor/` | Code changes that improve structure without changing behavior | `refactor/api-calls` |
| `chore/`    | Maintenance, dependencies, or build tasks                     | `chore/update-deps`  |

**Command:** `git checkout -b feat/your-branch-name`

---

## 2. Commit Message Standards

We follow the **Conventional Commits** format. This keeps the history clean and allows for automated changelogs.

**Format:** `<type>(optional-scope): <description>`

- **Type:** Use the prefixes mentioned above (feat, fix, docs, etc.).
- **Description:** Use the imperative, present tense (e.g., "add" instead of "added").
- **Case:** Start the description with a lowercase letter and do not end with a period.

**Examples:**

- `feat(ui): add toggle for dark mode`
- `fix(auth): resolve token expiration bug`
- `docs: clarify installation steps`

---

## 3. Pull Request (PR) Details

### PR Title

The title should be concise and follow the commit naming convention.

- **Good:** `feat: implement user dashboard`
- **Bad:** `Merge my code` or `Finished the task`
