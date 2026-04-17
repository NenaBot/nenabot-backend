"""Manual hardware coverage tests for a real IonVision machine."""

from __future__ import annotations

import asyncio
import json
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import pytest

from app.adapters.ionVision import IVAdapter, IVResult

pytestmark = [pytest.mark.hardware, pytest.mark.ionvision]

# Default connection settings — override with env vars (see below)
_DEFAULT_BASE_URL = "http://192.168.1.109/api"
_DEFAULT_WS_BASE_URL = "ws://192.168.1.109/socket"


@dataclass(frozen=True)
class ResultsQuery:
    """Query configuration for reading stored IonVision results."""

    max_results: int
    page: int | None
    search: str
    start_date: str
    end_date: str
    sort_by: str
    only_metadata: bool
    ids: str


@dataclass(frozen=True)
class HardwareConfig:
    """Runtime settings for the manual IonVision hardware tests."""

    base_url: str
    ws_base_url: str
    timeout_s: float
    allow_mutations: bool
    run_websocket_test: bool
    websocket_event_timeout_s: float
    scan_results_processed_timeout_s: float
    results_query: ResultsQuery


def _env_flag(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _coerce_bool(name: str, value: Any, *, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    raise pytest.UsageError(f"{name} must be a boolean, got {value!r}.")


def _coerce_int(name: str, value: Any, *, default: int) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise pytest.UsageError(f"{name} must be an integer, got {value!r}.") from exc


def _coerce_optional_int(name: str, value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, str) and value.strip() == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise pytest.UsageError(f"{name} must be an integer, got {value!r}.") from exc


def _coerce_float(name: str, value: Any, *, default: float) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise pytest.UsageError(f"{name} must be a number, got {value!r}.") from exc


def _derive_ws_base_url(base_url: str) -> str:
    parsed = urlsplit(base_url)
    scheme = "wss" if parsed.scheme == "https" else "ws"
    return urlunsplit(
        (scheme, parsed.netloc, parsed.path, parsed.query, parsed.fragment)
    ).rstrip("/")


def _assert_ok(result: IVResult, action: str, config: HardwareConfig) -> None:
    assert result.ok, f"{action} failed against {config.base_url}: {result.error}"


def _is_unavailable_error(error: str | None) -> bool:
    normalized = (error or "").lower()
    unavailable_markers = (
        "404",
        "not found",
        "no result",
        "no results",
        "no gas",
        "no detection",
        "no data",
    )
    return any(marker in normalized for marker in unavailable_markers)


def _assert_ok_or_skip_if_unavailable(
    result: IVResult,
    action: str,
    config: HardwareConfig,
) -> None:
    if result.ok:
        return

    if _is_unavailable_error(result.error):
        pytest.skip(f"{action} is unavailable on this machine: {result.error}")

    _assert_ok(result, action, config)


def _print_payload(label: str, payload: Any, *, limit: int = 5000) -> None:
    try:
        rendered = json.dumps(payload, indent=2, sort_keys=True, default=str)
    except TypeError:
        rendered = repr(payload)

    if len(rendered) > limit:
        rendered = f"{rendered[:limit]}\n... <truncated {len(rendered) - limit} chars>"

    print(f"{label}:\n{rendered}")


def _results_query_as_dict(query: ResultsQuery) -> dict[str, Any]:
    return {
        "max_results": query.max_results,
        "page": query.page,
        "search": query.search,
        "start_date": query.start_date,
        "end_date": query.end_date,
        "sort_by": query.sort_by,
        "only_metadata": query.only_metadata,
        "ids": query.ids,
    }


def _extract_result_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]

    if not isinstance(payload, dict):
        return []

    for key in ("results", "items", "entries", "data", "records", "rows"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]

    for value in payload.values():
        items = _extract_result_items(value)
        if items:
            return items

    return []


def _extract_result_id(payload: Any) -> str | None:
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key.lower() in {"id", "scanid", "resultid"} and value not in (
                None,
                "",
            ):
                return str(value)

        for value in payload.values():
            result_id = _extract_result_id(value)
            if result_id:
                return result_id

    if isinstance(payload, list):
        for item in payload:
            result_id = _extract_result_id(item)
            if result_id:
                return result_id

    return None


def _has_stored_results(payload: Any) -> bool:
    return bool(_extract_result_items(payload) or _extract_result_id(payload))


def _scan_looks_active(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False

    status = str(payload.get("status", "")).lower()
    if status in {"ongoing", "running", "active", "started"}:
        return True

    if payload.get("active") is True:
        return True

    if "progress" in payload:
        return True

    return bool(payload.get("scanId") and status != "stopped")


def _scan_looks_finished(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False

    status = str(payload.get("status", "")).lower()
    state = str(payload.get("state", "")).lower()

    if state in {"finished", "completed", "done"}:
        return True

    if status in {"finished", "completed", "done"}:
        return True

    return bool(payload.get("scanId") and state == "finished")


def _scan_has_identifier(payload: Any) -> bool:
    return isinstance(payload, dict) and any(
        value not in (None, "")
        for key, value in payload.items()
        if key.lower() in {"scanid", "id"}
    )


def _poll_for_active_scan(
    adapter: IVAdapter,
    config: HardwareConfig,
    *,
    timeout_s: float = 5.0,
    interval_s: float = 1.0,
) -> IVResult:
    deadline = time.monotonic() + timeout_s
    last_result = adapter.get_current_scan()

    while True:
        _assert_ok(
            last_result,
            "GET /currentScan while polling scan state",
            config,
        )
        if _scan_looks_active(last_result.payload):
            return last_result
        if time.monotonic() >= deadline:
            return last_result
        time.sleep(interval_s)
        last_result = adapter.get_current_scan()


async def _wait_for_finished_scan(
    adapter: IVAdapter,
    config: HardwareConfig,
    *,
    timeout_s: float,
    interval_s: float = 1.0,
) -> IVResult:
    deadline = time.monotonic() + timeout_s
    last_result = await asyncio.to_thread(adapter.get_current_scan)

    while True:
        if not last_result.ok:
            # Some IonVision firmwares stop exposing /currentScan immediately
            # after scan completion; treat that as terminal once we have entered
            # the scan lifecycle for this test.
            if _is_unavailable_error(last_result.error):
                return IVResult(
                    ok=True,
                    payload={
                        "state": "finished",
                        "status": "finished",
                        "_source": "currentScan unavailable",
                        "_error": last_result.error,
                    },
                )

            _assert_ok(
                last_result,
                "GET /currentScan while waiting for scan completion",
                config,
            )

        if _scan_looks_finished(last_result.payload):
            return last_result
        if time.monotonic() >= deadline:
            return last_result
        await asyncio.sleep(interval_s)
        last_result = await asyncio.to_thread(adapter.get_current_scan)


async def _wait_for_latest_dataobject(
    adapter: IVAdapter,
    config: HardwareConfig,
    *,
    timeout_s: float,
    interval_s: float = 1.0,
) -> IVResult:
    deadline = time.monotonic() + timeout_s
    last_result = await asyncio.to_thread(adapter.get_latest_dataobject)

    while True:
        if last_result.ok and _has_stored_results(last_result.payload):
            return last_result
        if time.monotonic() >= deadline:
            _assert_ok(
                last_result,
                "GET /results/latest after scan.resultsProcessed",
                config,
            )
            assert _has_stored_results(last_result.payload), (
                "GET /results/latest did not return a stored result after the scan "
                f"completed: {last_result.payload}"
            )
            return last_result
        await asyncio.sleep(interval_s)
        last_result = await asyncio.to_thread(adapter.get_latest_dataobject)


def _comment_object(payload: Any) -> dict[str, Any]:
    if isinstance(payload, dict):
        return dict(payload)
    return {}


def _assert_websocket_message_envelope(
    payload: Any,
    *,
    expected_type: str,
) -> dict[str, Any]:
    assert isinstance(payload, dict), (
        "IonVision websocket payload must be a JSON object, got "
        f"{type(payload).__name__}: {payload!r}"
    )
    assert payload.get("type") == expected_type, (
        f"Expected websocket event {expected_type!r}, got {payload.get('type')!r}: "
        f"{payload}"
    )
    assert isinstance(payload.get("time"), int), (
        "IonVision websocket payload is missing the documented integer "
        f"'time' field: {payload}"
    )
    assert isinstance(payload.get("body"), dict), (
        "IonVision websocket payload is missing the documented object "
        f"'body' field: {payload}"
    )
    return payload["body"]


def _assert_controllers_status_message(payload: Any) -> None:
    body = _assert_websocket_message_envelope(
        payload,
        expected_type="controllers.status",
    )
    for section in ("status", "sample", "sensor", "ambient"):
        assert isinstance(body.get(section), dict), (
            "controllers.status must include the documented "
            f"{section!r} object: {payload}"
        )


async def _wait_for_websocket_event(
    event_queue: asyncio.Queue[dict[str, Any]],
    *,
    event_type: str,
    timeout_s: float,
    action_description: str,
) -> dict[str, Any]:
    try:
        return await asyncio.wait_for(event_queue.get(), timeout=timeout_s)
    except asyncio.TimeoutError as exc:
        raise AssertionError(
            f"Timed out after {timeout_s:.1f}s waiting for websocket event "
            f"{event_type!r} after {action_description}."
        ) from exc


async def _capture_websocket_event_for_sync_call(
    adapter: IVAdapter,
    *,
    event_type: str,
    timeout_s: float,
    trigger: Callable[[], IVResult],
    action_description: str,
) -> tuple[IVResult, dict[str, Any] | None]:
    event_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=1)

    def _event_handler(data: dict[str, Any]) -> None:
        if event_queue.empty():
            event_queue.put_nowait(data)

    adapter.on_event(event_type, _event_handler)
    assert _event_handler in adapter._ws._handlers.get(event_type, [])

    await adapter.initialize_websocket()
    try:
        result = await asyncio.to_thread(trigger)
        if not result.ok:
            return result, None

        event_payload = await _wait_for_websocket_event(
            event_queue,
            event_type=event_type,
            timeout_s=timeout_s,
            action_description=action_description,
        )
        return result, event_payload
    finally:
        await adapter.disconnect_websocket()
        adapter.off_event(event_type, _event_handler)
        assert _event_handler not in adapter._ws._handlers.get(event_type, [])


def _ensure_active_scan(
    adapter: IVAdapter,
    config: HardwareConfig,
) -> tuple[IVResult, bool]:
    started = adapter.start_new_scan()
    if started.ok:
        _print_payload("start_new_scan payload", started.payload)
        return _poll_for_active_scan(adapter, config), True

    if "409" in (started.error or ""):
        current = adapter.get_current_scan()
        _assert_ok(current, "GET /currentScan after POST /currentScan conflict", config)
        return current, False

    _assert_ok(started, "POST /currentScan before GET /currentScan", config)
    return started, False


@pytest.fixture(scope="module")
def hardware_config() -> HardwareConfig:
    if not _env_flag("IONVISION_RUN_HARDWARE_TESTS"):
        pytest.skip(
            "Set IONVISION_RUN_HARDWARE_TESTS=1 to run against a real IonVision machine."
        )

    base_url = os.getenv("IONVISION_BASE_URL", _DEFAULT_BASE_URL).rstrip("/")
    ws_base_url = (os.getenv("IONVISION_WS_BASE_URL") or _DEFAULT_WS_BASE_URL).rstrip(
        "/"
    )

    return HardwareConfig(
        base_url=base_url,
        ws_base_url=ws_base_url,
        timeout_s=_coerce_float(
            "IONVISION_REQUEST_TIMEOUT_S",
            os.getenv("IONVISION_REQUEST_TIMEOUT_S"),
            default=10.0,
        ),
        allow_mutations=_coerce_bool(
            "IONVISION_ENABLE_MUTATION_TESTS",
            os.getenv("IONVISION_ENABLE_MUTATION_TESTS"),
            default=True,
        ),
        run_websocket_test=_coerce_bool(
            "IONVISION_RUN_WS_TEST",
            os.getenv("IONVISION_RUN_WS_TEST"),
            default=True,
        ),
        websocket_event_timeout_s=_coerce_float(
            "IONVISION_WS_EVENT_TIMEOUT_S",
            os.getenv("IONVISION_WS_EVENT_TIMEOUT_S"),
            default=10.0,
        ),
        scan_results_processed_timeout_s=_coerce_float(
            "IONVISION_SCAN_RESULTS_PROCESSED_TIMEOUT_S",
            os.getenv("IONVISION_SCAN_RESULTS_PROCESSED_TIMEOUT_S"),
            default=120.0,
        ),
        results_query=ResultsQuery(
            max_results=_coerce_int(
                "IONVISION_RESULTS_MAX_RESULTS",
                os.getenv("IONVISION_RESULTS_MAX_RESULTS"),
                default=100,
            ),
            page=_coerce_optional_int(
                "IONVISION_RESULTS_PAGE",
                os.getenv("IONVISION_RESULTS_PAGE"),
            ),
            search=os.getenv("IONVISION_RESULTS_SEARCH", ""),
            start_date=os.getenv(
                "IONVISION_RESULTS_START_DATE", "2026-03-17T13:01:11.874Z"
            ),
            end_date=os.getenv(
                "IONVISION_RESULTS_END_DATE", "2026-03-25T13:01:11.874Z"
            ),
            sort_by=os.getenv("IONVISION_RESULTS_SORT_BY", "date_dsc"),
            only_metadata=_coerce_bool(
                "IONVISION_RESULTS_ONLY_METADATA",
                os.getenv("IONVISION_RESULTS_ONLY_METADATA"),
                default=True,
            ),
            ids=os.getenv("IONVISION_RESULTS_IDS", ""),
        ),
    )


@pytest.fixture(scope="module")
def adapter(hardware_config: HardwareConfig) -> IVAdapter:
    return IVAdapter(
        base_url=hardware_config.base_url,
        ws_base_url=hardware_config.ws_base_url,
        timeout_s=hardware_config.timeout_s,
    )


@pytest.fixture(scope="module")
def results_listing(adapter: IVAdapter, hardware_config: HardwareConfig) -> IVResult:
    return adapter.get_results(
        max_results=hardware_config.results_query.max_results,
        page=hardware_config.results_query.page,
        search=hardware_config.results_query.search,
        start_date=hardware_config.results_query.start_date,
        end_date=hardware_config.results_query.end_date,
        sort_by=hardware_config.results_query.sort_by,
        only_metadata=hardware_config.results_query.only_metadata,
        ids=hardware_config.results_query.ids,
    )


@pytest.fixture(scope="module")
def latest_result(
    adapter: IVAdapter,
    results_listing: IVResult,
    hardware_config: HardwareConfig,
) -> IVResult:
    if not results_listing.ok:
        pytest.skip(
            "GET /results failed, so /results/latest cannot be exercised safely."
        )
    if not _has_stored_results(results_listing.payload):
        pytest.skip("IonVision returned no stored results for GET /results.")
    return adapter.get_latest_dataobject()


@pytest.fixture(scope="module")
def discovered_result_id(
    results_listing: IVResult,
    latest_result: IVResult,
) -> str:
    result_id = _extract_result_id(results_listing.payload)
    if result_id:
        return result_id

    result_id = _extract_result_id(latest_result.payload)
    if result_id:
        return result_id

    pytest.skip(
        "Could not discover a result id from GET /results or GET /results/latest."
    )


def test_ping_current_parameter_endpoint(
    adapter: IVAdapter,
    hardware_config: HardwareConfig,
) -> None:
    """Exercise the same ping path that the backend health check uses."""
    result = adapter.ping()
    _assert_ok(result, "GET /currentParameter via IVAdapter.ping()", hardware_config)
    _print_payload("ping payload", result.payload)


def test_get_parameter_id_endpoint(
    adapter: IVAdapter,
    hardware_config: HardwareConfig,
) -> None:
    """Exercise the explicit parameter-id helper on the same endpoint."""
    result = adapter.get_parameter_ID()
    _assert_ok(
        result,
        "GET /currentParameter via IVAdapter.get_parameter_ID()",
        hardware_config,
    )
    _print_payload("currentParameter payload", result.payload)


def test_current_scan_endpoint(
    adapter: IVAdapter,
    hardware_config: HardwareConfig,
) -> None:
    """Read current scan status, starting a scan first when the test owns it."""
    if not hardware_config.allow_mutations:
        pytest.skip(
            "Enable mutation calls in the local IonVision hardware config or set "
            "IONVISION_ENABLE_MUTATION_TESTS=1 so the test can start a scan "
            "before reading current scan state."
        )

    result, started_here = _ensure_active_scan(adapter, hardware_config)
    try:
        _assert_ok(result, "GET /currentScan", hardware_config)
        assert _scan_looks_active(result.payload), (
            "GET /currentScan did not report an active scan after the test "
            f"prepared one: {result.payload}"
        )
        _print_payload("currentScan payload", result.payload)
    finally:
        if started_here:
            stopped = adapter.stop_current_scan()
            _assert_ok(
                stopped, "DELETE /currentScan after GET /currentScan", hardware_config
            )
            _print_payload("stop_current_scan payload", stopped.payload)


def test_scan_comments_endpoint(
    adapter: IVAdapter,
    hardware_config: HardwareConfig,
) -> None:
    """Confirm scan-comment reads work against the real machine."""
    result = adapter.get_scan_comments()
    _assert_ok(result, "GET /currentScan/comments", hardware_config)
    _print_payload("currentScan/comments payload", result.payload)


def test_results_listing_endpoint(
    results_listing: IVResult,
    hardware_config: HardwareConfig,
) -> None:
    """Read back stored result metadata so downstream tests can inspect it."""
    _assert_ok(results_listing, "GET /results", hardware_config)
    _print_payload(
        "results query",
        _results_query_as_dict(hardware_config.results_query),
    )
    _print_payload("results payload", results_listing.payload)


def test_latest_result_dataobject_endpoint(
    latest_result: IVResult,
    hardware_config: HardwareConfig,
) -> None:
    """Read the latest stored result payload."""
    _assert_ok(latest_result, "GET /results/latest", hardware_config)
    _print_payload("results/latest payload", latest_result.payload)


def test_result_dataobject_endpoint_by_id(
    adapter: IVAdapter,
    discovered_result_id: str,
    hardware_config: HardwareConfig,
) -> None:
    """Read a concrete stored result by id."""
    result = adapter.get_scan_dataobject(discovered_result_id)
    _assert_ok(result, f"GET /results/id/{discovered_result_id}", hardware_config)
    _print_payload(f"results/id/{discovered_result_id} payload", result.payload)


def test_result_comments_endpoint_by_id(
    adapter: IVAdapter,
    discovered_result_id: str,
    hardware_config: HardwareConfig,
) -> None:
    """Read the comment object for a concrete stored result."""
    result = adapter.get_scan_result_commentobject(discovered_result_id)
    _assert_ok(
        result,
        f"GET /results/id/{discovered_result_id}/comments",
        hardware_config,
    )
    _print_payload(
        f"results/id/{discovered_result_id}/comments payload",
        result.payload,
    )


def test_scan_comments_round_trip(
    adapter: IVAdapter,
    hardware_config: HardwareConfig,
) -> None:
    """Optionally confirm that current-scan comments can be updated and restored."""
    if not hardware_config.allow_mutations:
        pytest.skip(
            "Set IONVISION_ENABLE_MUTATION_TESTS=1 to allow mutation calls "
            "against the real machine."
        )

    original = adapter.get_scan_comments()
    _assert_ok(original, "GET /currentScan/comments before mutation", hardware_config)

    updated_comments = _comment_object(original.payload)
    marker = f"codex-hardware-test-{int(time.time())}"
    updated_comments["codexHardwareTestMarker"] = marker

    try:
        updated = adapter.replace_scan_comments(updated_comments)
        _assert_ok(updated, "PUT /currentScan/comments", hardware_config)

        reread = adapter.get_scan_comments()
        _assert_ok(reread, "GET /currentScan/comments after mutation", hardware_config)
        _print_payload("currentScan/comments after mutation", reread.payload)
        assert _comment_object(reread.payload).get("codexHardwareTestMarker") == marker
    finally:
        restored = adapter.replace_scan_comments(_comment_object(original.payload))
        _assert_ok(
            restored,
            "PUT /currentScan/comments while restoring original comments",
            hardware_config,
        )


def test_result_comments_round_trip_by_id(
    adapter: IVAdapter,
    discovered_result_id: str,
    hardware_config: HardwareConfig,
) -> None:
    """Optionally confirm that stored result comments can be updated and restored."""
    if not hardware_config.allow_mutations:
        pytest.skip(
            "Set IONVISION_ENABLE_MUTATION_TESTS=1 to allow mutation calls "
            "against the real machine."
        )

    original = adapter.get_scan_result_commentobject(discovered_result_id)
    _assert_ok(
        original,
        f"GET /results/id/{discovered_result_id}/comments before mutation",
        hardware_config,
    )

    updated_comments = _comment_object(original.payload)
    marker = f"codex-result-comment-test-{int(time.time())}"
    updated_comments["codexHardwareResultMarker"] = marker

    try:
        updated = adapter.put_scan_result_commentobject(
            discovered_result_id,
            updated_comments,
        )
        _assert_ok(
            updated,
            f"PUT /results/id/{discovered_result_id}/comments",
            hardware_config,
        )

        reread = adapter.get_scan_result_commentobject(discovered_result_id)
        _assert_ok(
            reread,
            f"GET /results/id/{discovered_result_id}/comments after mutation",
            hardware_config,
        )
        _print_payload(
            f"results/id/{discovered_result_id}/comments after mutation",
            reread.payload,
        )
        assert (
            _comment_object(reread.payload).get("codexHardwareResultMarker") == marker
        )
    finally:
        restored = adapter.put_scan_result_commentobject(
            discovered_result_id,
            _comment_object(original.payload),
        )
        _assert_ok(
            restored,
            f"PUT /results/id/{discovered_result_id}/comments while restoring original comments",
            hardware_config,
        )


def test_scan_lifecycle_start_and_stop(
    adapter: IVAdapter,
    hardware_config: HardwareConfig,
) -> None:
    """Optionally perform a real scan start/stop round trip and verify scan.stopped."""
    if not hardware_config.allow_mutations:
        pytest.skip(
            "Set IONVISION_ENABLE_MUTATION_TESTS=1 to allow start/stop calls "
            "against the real machine."
        )

    started = adapter.start_new_scan()
    if not started.ok and "409" in (started.error or ""):
        pytest.skip(
            "IonVision refused to start a new scan because one may already be active."
        )
    _assert_ok(started, "POST /currentScan", hardware_config)
    _print_payload("start_new_scan payload", started.payload)

    after_start = _poll_for_active_scan(adapter, hardware_config)
    _print_payload("currentScan after start payload", after_start.payload)
    saw_active_scan = _scan_looks_active(after_start.payload)

    if saw_active_scan:
        stopped_event = None
        if hardware_config.run_websocket_test:
            stopped, stopped_event = asyncio.run(
                _capture_websocket_event_for_sync_call(
                    adapter,
                    event_type="scan.stopped",
                    timeout_s=hardware_config.websocket_event_timeout_s,
                    trigger=adapter.stop_current_scan,
                    action_description="DELETE /currentScan",
                )
            )
        else:
            stopped = adapter.stop_current_scan()

        _assert_ok(stopped, "DELETE /currentScan", hardware_config)
        _print_payload("stop_current_scan payload", stopped.payload)
        if stopped_event is not None:
            _print_payload("websocket scan.stopped payload", stopped_event)
            _assert_websocket_message_envelope(
                stopped_event,
                expected_type="scan.stopped",
            )
    else:
        assert _scan_has_identifier(started.payload), (
            "The scan never appeared active after POST /currentScan, and the "
            f"start response did not include an identifier: {started.payload}"
        )


def test_websocket_endpoint_accepts_connections(
    hardware_config: HardwareConfig,
) -> None:
    """Verify the websocket connects and receives a documented status event."""
    if not hardware_config.run_websocket_test:
        pytest.skip("Set IONVISION_RUN_WS_TEST=1 to exercise the WebSocket endpoint.")

    async def _exercise_websocket() -> dict[str, Any]:
        ws_adapter = IVAdapter(
            base_url=hardware_config.base_url,
            ws_base_url=hardware_config.ws_base_url,
            timeout_s=hardware_config.timeout_s,
        )
        first_status_event: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=1)

        def _event_handler(data: dict[str, Any]) -> None:
            if first_status_event.empty():
                first_status_event.put_nowait(data)

        ws_adapter.on_event("controllers.status", _event_handler)
        assert ws_adapter._ws._handlers["controllers.status"] == [_event_handler]

        await ws_adapter.initialize_websocket()
        try:
            return await _wait_for_websocket_event(
                first_status_event,
                event_type="controllers.status",
                timeout_s=hardware_config.websocket_event_timeout_s,
                action_description="websocket connect",
            )
        finally:
            await ws_adapter.disconnect_websocket()
            ws_adapter.off_event("controllers.status", _event_handler)
            assert ws_adapter._ws._handlers["controllers.status"] == []

    websocket_payload = asyncio.run(_exercise_websocket())
    _print_payload("websocket event payload", websocket_payload)
    _assert_controllers_status_message(websocket_payload)
    print(f"websocket connection succeeded: {hardware_config.ws_base_url}")


def test_websocket_scan_results_processed_event(
    adapter: IVAdapter,
    hardware_config: HardwareConfig,
) -> None:
    """Run a full scan, wait for completion, and verify scan.resultsProcessed."""
    if not hardware_config.allow_mutations:
        pytest.skip(
            "Set IONVISION_ENABLE_MUTATION_TESTS=1 to allow scan completion "
            "calls against the real machine."
        )
    if not hardware_config.run_websocket_test:
        pytest.skip("Set IONVISION_RUN_WS_TEST=1 to exercise websocket scan events.")

    async def _exercise_scan_completion() -> tuple[IVResult, dict[str, Any]]:
        event_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=1)
        owned_scan_started = False

        def _event_handler(data: dict[str, Any]) -> None:
            if event_queue.empty():
                event_queue.put_nowait(data)

        adapter.on_event("scan.resultsProcessed", _event_handler)
        assert _event_handler in adapter._ws._handlers.get("scan.resultsProcessed", [])

        await adapter.initialize_websocket()
        try:
            started = await asyncio.to_thread(adapter.start_new_scan)
            if not started.ok and "409" in (started.error or ""):
                pytest.skip(
                    "IonVision refused to start a new scan because one may "
                    "already be active, so scan.resultsProcessed cannot be "
                    "attributed to this test safely."
                )
            _assert_ok(
                started, "POST /currentScan for scan.resultsProcessed", hardware_config
            )
            owned_scan_started = True

            finished_scan = await _wait_for_finished_scan(
                adapter,
                hardware_config,
                timeout_s=hardware_config.scan_results_processed_timeout_s,
            )
            _assert_ok(
                finished_scan,
                "GET /currentScan after scan finished",
                hardware_config,
            )
            _print_payload("currentScan finished payload", finished_scan.payload)
            assert _scan_looks_finished(finished_scan.payload), (
                "GET /currentScan never reported a finished scan after POST /currentScan: "
                f"{finished_scan.payload}"
            )

            event_payload = await _wait_for_websocket_event(
                event_queue,
                event_type="scan.resultsProcessed",
                timeout_s=hardware_config.scan_results_processed_timeout_s,
                action_description="waiting for scan completion",
            )
            latest_result = await _wait_for_latest_dataobject(
                adapter,
                hardware_config,
                timeout_s=hardware_config.scan_results_processed_timeout_s,
            )
            _print_payload(
                "results/latest after processing payload", latest_result.payload
            )
            return started, event_payload
        except AssertionError:
            if owned_scan_started:
                current = await asyncio.to_thread(adapter.get_current_scan)
                if current.ok and _scan_looks_active(current.payload):
                    stopped = await asyncio.to_thread(adapter.stop_current_scan)
                    _print_payload(
                        "stop_current_scan after scan.resultsProcessed timeout payload",
                        stopped.payload,
                    )
            raise
        finally:
            await adapter.disconnect_websocket()
            adapter.off_event("scan.resultsProcessed", _event_handler)
            assert _event_handler not in adapter._ws._handlers.get(
                "scan.resultsProcessed",
                [],
            )

    started, websocket_payload = asyncio.run(_exercise_scan_completion())
    _print_payload("start_new_scan payload", started.payload)
    _print_payload("websocket scan.resultsProcessed payload", websocket_payload)
    _assert_websocket_message_envelope(
        websocket_payload,
        expected_type="scan.resultsProcessed",
    )
