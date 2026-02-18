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

## Endpoints

- `GET /health`
- `GET /status`
- `GET /jobs`
- `GET /jobs/{id}`
- `GET /jobs/{id}/image` — annotated overlay JPEG
- `GET /jobs/latest`
- `POST /jobs`
- `DELETE /jobs/{id}`
- `POST /robot/stop`
- `GET /profiles`
- `GET /profiles/default`
- `POST /streams/camera`
- `DELETE /streams/camera`
- `POST /streams/detection`
- `DELETE /streams/detection`
- `POST /paths`

## Hardware integration notes

- **Dobot**: `app/adapters/robot.py` wraps `DobotDllTypeMulti`. It mirrors the connection pattern from DobotDemoForPython/minimal_connect.py.
- **Camera/Vision**: `app/adapters/camera_vision.py` handles ArUco marker detection, battery-contour detection, overlay rendering, and MJPEG streaming.
- **DMS**: `app/adapters/ionVision/ionVision.py` calls the external DMS HTTP endpoint. Configure the base URL in `app/dependencies.py`.
- **Database**: SQLite (`data/nenabot.db`) stores all job state, waypoints, measurements, and overlay images. See [Database Documentation](docs/database.md).

## UI pages

| Page          | URL                                    | Description                                         |
| :------------ | :------------------------------------- | :-------------------------------------------------- |
| OpenAPI docs  | `/docs`                                | Auto-generated interactive API reference            |
| Job Tester    | Open `docs/job-tester.html` locally    | Create and monitor jobs                             |
| Job Results   | Open `docs/job-results.html` locally   | Browse jobs, view annotated images and measurements |
| Stream Viewer | Open `docs/stream-viewer.html` locally | Live camera / detection stream viewer               |

## Tests

```bash
pytest -q
```

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
