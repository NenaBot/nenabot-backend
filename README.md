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

## Endpoints

- `GET /health`
- `GET /status`
- `GET /jobs`
- `GET /jobs/{id}`
- `GET /jobs/latest`
- `POST /jobs`
- `DELETE /jobs/{id}`
- `GET /profiles`
- `GET /profiles/default`
- `POST /streams/camera`
- `DELETE /streams/camera`
- `POST /streams/detection`
- `DELETE /streams/detection`
- `POST /paths`

## Hardware integration notes

- **Dobot**: `app/adapters/robot.py` wraps `DobotDllTypeMulti`. It mirrors the connection pattern from DobotDemoForPython/minimal_connect.py.
- **Camera/Vision**: `app/adapters/camera.py` and `app/adapters/vision.py` are based on camera_detection/main.py (ArUco marker detection). These adapters currently return placeholder pose values.
- **DMS**: `app/adapters/ionVision/ionVision.py` calls the external DMS HTTP endpoint (`/dms/read`). Configure the base URL in `app/dependencies.py`.

## Tests

```bash
pytest -q
```

## Next steps

- Replace placeholder pose estimation with calibrated pose → robot coordinates.
- Add persistent job storage and real result persistence.
- Wire the state machine to the adapters to perform end-to-end runs.

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
