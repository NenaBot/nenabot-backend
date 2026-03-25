# IonVision Integration Tests

This is a manual hardware coverage test for a real IonVision machine. It exercises the
same `IVAdapter` code that the backend uses.

Because the test file now lives under `docs/ionvision-integration-tests/`, the
default `pytest` run and normal CI discovery do not pick it up by accident.

## What the test does

By default, the test prints compact payload snapshots and can load its
IonVision connection settings from
`docs/ionvision-integration-tests/.ionvision-hardware.json`.

Read-only coverage:

- `GET /currentParameter` via `IVAdapter.ping()`
- `GET /currentParameter` via `IVAdapter.get_parameter_ID()`
- `GET /currentScan/comments`
- `GET /results`
- `GET /results/latest`
- `GET /results/id/{id}`
- `GET /results/id/{id}/comments`

Optional checks are available for:

- Starting a scan automatically before `GET /currentScan`
- Updating and restoring current scan comments
- Updating and restoring stored result comments
- WebSocket connect plus receipt of a documented `controllers.status` event
- Starting and stopping a real scan plus receipt of `scan.stopped`
- Running a full scan to verify `scan.resultsProcessed`

The state-changing scan test is disabled unless you explicitly enable it.

## Before you run it

1. Make sure your laptop can reach the IonVision machine over the network.
2. Confirm the machine is idle before enabling the scan start/stop test.
3. Create and activate the project virtualenv if needed.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Fast read-only coverage test

With the saved local config file in place, you can just run:

```bash
.venv/bin/pytest -s -v tests/test_ionVision_adapter.py docs/ionvision-integration-tests/test_ionVision_hardware.py
```

If you want to override the saved settings for one run, you can still use env
vars. For example:

```bash
export IONVISION_RUN_HARDWARE_TESTS=1
export IONVISION_BASE_URL=http://192.168.1.109/api
pytest -s -v docs/ionvision-integration-tests/test_ionVision_hardware.py
```

Notes:

- `-s` prints the payload returned by the machine so you can inspect it live.
- `IONVISION_WS_BASE_URL` is optional. If omitted, the test derives it from
  `IONVISION_BASE_URL`.
- `IONVISION_REQUEST_TIMEOUT_S` is optional if the machine is slow to answer.
- `IONVISION_WS_EVENT_TIMEOUT_S` controls how long the manual websocket tests
  wait for quick events like `controllers.status` and `scan.stopped`.
- `IONVISION_SCAN_RESULTS_PROCESSED_TIMEOUT_S` controls how long the full-scan
  websocket test waits for `scan.resultsProcessed`.
- `IONVISION_RESULTS_MAX_RESULTS`, `IONVISION_RESULTS_PAGE`,
  `IONVISION_RESULTS_SEARCH`, `IONVISION_RESULTS_START_DATE`,
  `IONVISION_RESULTS_END_DATE`, `IONVISION_RESULTS_SORT_BY`,
  `IONVISION_RESULTS_ONLY_METADATA`, and `IONVISION_RESULTS_IDS` let you tune
  the `/results` query used for the readout and id discovery.
- Leave `IONVISION_RESULTS_PAGE` unset to use the device default. If you set it,
  the adapter now validates that the page number is greater than or equal to `1`.
- The local config file can enable mutation tests and the websocket validation
  test, so your manual run can cover those too without a long env block.

## Optional WebSocket check

The saved local config already enables the WebSocket check. If you want to run
just that test explicitly:

```bash
export IONVISION_RUN_HARDWARE_TESTS=1
export IONVISION_BASE_URL=http://192.168.1.109/api
export IONVISION_WS_BASE_URL=ws://192.168.1.109/socket
export IONVISION_RUN_WS_TEST=1
pytest -s -v docs/ionvision-integration-tests/test_ionVision_hardware.py::test_websocket_endpoint_accepts_connections
```

That test now waits for a real `controllers.status` event and validates the
documented websocket envelope: `type`, `time`, and `body`.

## Optional real scan start/stop test

The saved local config also enables mutation tests. If you want to run only the
scan lifecycle check:

```bash
export IONVISION_RUN_HARDWARE_TESTS=1
export IONVISION_BASE_URL=http://192.168.1.109/api
export IONVISION_ENABLE_MUTATION_TESTS=1
pytest -s -v docs/ionvision-integration-tests/test_ionVision_hardware.py::test_scan_lifecycle_start_and_stop
```

When websocket testing is also enabled, that lifecycle test now verifies that
the device emits `scan.stopped` after the manual stop call.

## Optional full scan completion test

If you want to verify that a completed scan emits `scan.resultsProcessed`, run:

```bash
export IONVISION_RUN_HARDWARE_TESTS=1
export IONVISION_BASE_URL=http://192.168.1.109/api
export IONVISION_ENABLE_MUTATION_TESTS=1
export IONVISION_RUN_WS_TEST=1
export IONVISION_SCAN_RESULTS_PROCESSED_TIMEOUT_S=120
pytest -s -v docs/ionvision-integration-tests/test_ionVision_hardware.py::test_websocket_scan_results_processed_event
```

This test starts a scan, waits for a real `scan.resultsProcessed` websocket
message, and stops the scan only if the timeout is hit while the test still
owns an active run.

Safety behavior:

- The current-scan test starts a scan itself before reading `/currentScan`, then
  stops that scan when it was created by the test.
- The lifecycle test does not call `GET /currentScan` before start or after stop.
- If `POST /currentScan` returns a conflict, the lifecycle test skips instead of
  probing scan state blindly.
- The scan-comment and stored-result-comment mutation tests restore the original
  comment objects after verification.

## If you want to verify through the backend too

The backend now accepts IonVision URLs through environment variables, so you
can point `/api/health` at the real machine without editing code:

```bash
export IONVISION_BASE_URL=http://192.168.1.109/api
export IONVISION_WS_BASE_URL=ws://192.168.1.109/socket
uvicorn app.main:app --reload
```

Then check:

```bash
curl http://127.0.0.1:8000/api/health
```

You should see the `dms` component report `connected` if the adapter can reach
IonVision.
