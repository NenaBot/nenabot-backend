# Robot Arm (Dobot) Documentation

The robot adapter wraps the Dobot Magician DLL and is the only component that
talks directly to the arm. It lives at `app/adapters/robot.py`.

## Key Responsibilities

- Serial port discovery and connection management
- PTP (point-to-point) movement commands, blocking and queued
- Built-in homing routine
- Command queue control: pause, resume, stop (clear)
- Pose read-back for arrival validation

## Core Methods

**`connect_first_available()`** <br>
Scans all candidate serial ports for the current platform and connects to the
first Dobot found. Preferred for normal use.

**`connect(port: str)`** <br>
Connect to a Dobot on a specific port (e.g. `"COM3"`, `"/dev/cu.usbserial-*"`).
Useful when the port is known in advance or auto-detection fails.

**`home()`** <br>
Runs the Dobot's built-in homing routine. Calibrates the arm and moves it to
its mechanical home position. Blocks until finished.
Uses `SetHOMECmdEx` when available; falls back to `SetHOMECmd` only when
`DOBOT_ENABLE_LEGACY_HOMING=1` is set (see env vars below).

## Application Startup

The API connects to the robot during startup, but startup homing is disabled by
default. Set `NENABOT_ENABLE_STARTUP_HOMING=1` to opt in to automatic homing
after the robot connection succeeds.

**`move(x, y, z, r, wait=True)`** / **`move_to_coordinates(coords, wait=True)`** <br>
Move the end-effector to a Cartesian position. With `wait=True` (default) the
call blocks until the arm reaches the target (`SetPTPCmdEx`). With `wait=False`
the command is queued and the call returns immediately (`SetPTPCmd`).

**`execute_route(coordinates)`** <br>
Execute a list of `(x, y, z, r)` waypoints in sequence, then run the homing
routine. Blocks until complete.

**`pause()` / `resume()`** <br>
Pause and resume the command queue. Queued commands are preserved across a
pause/resume cycle.

**`stop()`** <br>
Stop execution and clear the entire command queue. Use `pause()`/`resume()` if
you want to preserve queued commands.

**`get_pose()`** <br>
Read the current Cartesian position `(x, y, z, r)` and joint angles from the
arm. Returns a `PoseResult`.

**`wait_for_position(x, y, z, r, tolerance_mm, timeout_s)`** <br>
Poll `get_pose()` until the arm is within `tolerance_mm` of the target or the
timeout expires. Used by the orchestrator for arrival validation.

**`is_reachable_mm(x_mm, y_mm, z_mm)`** <br>
Fast reachability guard used by the debug sweep endpoint before issuing motion
commands. It applies conservative bounds to reject risky points early:

- `z_mm` must be between `-30` and `0`
- `x_mm` must be at least `10`
- radial distance `sqrt(x_mm^2 + y_mm^2)` must be between `180` and `320`

If a point is outside those limits the function returns `False`; otherwise
`True`. This check is intentionally conservative and should be treated as a
quick pre-filter rather than a full kinematics proof.

**`wait_until_queue_empty(timeout_s)`** <br>
Block until `GetQueuedCmdMotionFinish` reports the queue is empty.

**`ping()`** <br>
Lightweight connectivity check used by the health endpoint. Returns `ok=True`
if the DLL has been loaded and a connection established.

**`disconnect()`** <br>
Disconnect from the arm and release the DLL handle.

## Debug Reachability API

These development endpoints are implemented in [app/api/routes.py](../app/api/routes.py)
and are intended for manual workspace validation, not production workflows.

**`GET/POST /api/debug/robot/reachability`** <br>
Runs a grid sweep through Cartesian points and reports reachability + motion
outcome per point.

Query parameters:

- `x_min`, `x_max`, `y_min`, `y_max`, `z_min`, `z_max`
- Optional grid step sizes: `step_x` (default `50`), `step_y` (default `50`),
  `step_z` (default `10`)
- Optional wrist rotation: `r` (default `0`)

Behavior summary:

- Builds inclusive X/Y/Z ranges and iterates all points
- Uses `is_reachable_mm` before attempting movement
- For reachable points, performs `move` then waits for arrival
- The wait is interruptible, so stop requests are honored during in-flight
  motion checks
- Returns early when stop is requested or when a move/arrival fails

Response includes:

- `stoppedEarly`, `stopReason`, `failedAt`
- `testedPoints`, `totalPlannedPoints`
- `checks`: per-point records with reachability and movement outcome

**`GET/POST /api/debug/robot/reachability/stop`** <br>
Requests immediate stop of the active reachability sweep.

Behavior summary:

- Sets the shared reachability stop event
- Attempts to stop robot queue execution via the adapter
- Also calls service-level stop handling for active job contexts

Response fields:

- `stopRequested`: always `true` when endpoint is hit
- `robotStopped`: `true` if robot stop or service stop succeeded

---

## Hardware Integration Tests

The test suite lives at `tests/test_robot_hardware.py` and is marked
`@pytest.mark.hardware` + `@pytest.mark.integration`. CI excludes these markers
so tests are never run automatically — they must be triggered manually when the
arm is connected.

### Before you run

1. Power on the Dobot and connect it via USB.
2. Confirm the work area is clear — the arm moves immediately after homing.
3. Activate the virtualenv:

```bash
source .venv/bin/activate
```

### Running the tests

```bash
RUN_ROBOT_HARDWARE_TESTS=1 pytest -s -v tests/test_robot_hardware.py
```

The fixture auto-detects the serial port. On Windows it falls back to `COM3`
if auto-detection finds nothing. If the arm still cannot be reached the test
is skipped with a clear message.

### Environment variables

| Variable | Default | Description |
| :--- | :--- | :--- |
| `RUN_ROBOT_HARDWARE_TESTS` | — | Set to `1` to enable the suite |
| `NENABOT_ENABLE_STARTUP_HOMING` | `0` | Set to `1` to home the arm automatically during app startup after connect |
| `DOBOT_ENABLE_LEGACY_HOMING` | `0` | Set to `1` to use `SetHOMECmd` instead of `SetHOMECmdEx` (known to crash on some Windows setups — only enable if `SetHOMECmdEx` is unavailable) |

### What the tests cover

| Test | What it does |
| :--- | :--- |
| `test_live_hardware_route` | Home → execute a rectangular 4-point route → return home |
| `test_stop_command_queue` | Home → queue a route → stop (clear queue) |
| `test_pause_and_resume_route` | Home → queue a route → pause 3 s → resume → wait for completion → home |

The rectangular route used in all tests visits these waypoints (mm):

```
(304, -40, -30, 0)
(304,  40, -30, 0)
(201,  40, -30, 0)
(201, -40, -30, 0)
```

### Running a specific test

```bash
RUN_ROBOT_HARDWARE_TESTS=1 pytest -s -v tests/test_robot_hardware.py::test_live_hardware_route
```

### Safety notes

- The arm runs the homing routine at the start of every test — make sure the
  work area is clear before enabling tests.
- `stop()` clears the queue; use `pause()`/`resume()` if you want to preserve
  queued commands across an interruption.
- The legacy `SetHOMECmd` path is gated behind `DOBOT_ENABLE_LEGACY_HOMING`
  because it has been observed to crash some Windows setups.
