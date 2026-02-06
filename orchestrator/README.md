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

- `POST /jobs/start`
- `GET /jobs/{id}`
- `POST /jobs/{id}/cancel`
- `GET /health`
- `GET /results/latest`

## Hardware integration notes

- **Dobot**: `app/adapters/robot.py` wraps `DobotDllTypeMulti`. It mirrors the connection pattern from DobotDemoForPython/minimal_connect.py.
- **Camera/Vision**: `app/adapters/camera.py` and `app/adapters/vision.py` are based on camera_detection/main.py (ArUco marker detection). These adapters currently return placeholder pose values.
- **DMS**: `app/adapters/dms.py` calls the external DMS HTTP endpoint (`/dms/read`). Configure the base URL in `app/dependencies.py`.

## Tests

```bash
pytest -q
```

## Next steps

- Replace placeholder pose estimation with calibrated pose → robot coordinates.
- Add persistent job storage and real result persistence.
- Wire the state machine to the adapters to perform end-to-end runs.
