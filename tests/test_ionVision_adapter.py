"""Tests for the IonVision adapter."""

import asyncio
import json
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
import respx

from app.adapters.ionVision import IVAdapter, IVResult, WebSocketAdapter

BASE_URL = "http://localhost:8080"
WS_BASE_URL = "ws://localhost:8080"


class FakeAsyncWebSocket:
    """Async iterator that yields pre-baked websocket frames."""

    def __init__(self, messages: list[str]) -> None:
        self._messages = messages
        self._index = 0

    def __aiter__(self) -> "FakeAsyncWebSocket":
        return self

    async def __anext__(self) -> str:
        if self._index >= len(self._messages):
            raise StopAsyncIteration
        message = self._messages[self._index]
        self._index += 1
        return message


@pytest.fixture
def iv_adapter() -> IVAdapter:
    """Create an IonVision adapter for unit tests."""
    return IVAdapter(base_url=BASE_URL, ws_base_url=WS_BASE_URL)


@respx.mock
def test_start_new_scan(iv_adapter: IVAdapter) -> None:
    """Test POST /currentScan request."""
    respx.post("http://localhost:8080/currentScan").mock(
        return_value=httpx.Response(
            201, json={"message": "The new scan is now starting."}
        ),
    )

    result = iv_adapter.start_new_scan()

    assert result.ok is True
    assert "message" in result.payload


@respx.mock
def test_stop_current_scan(iv_adapter: IVAdapter) -> None:
    """Test DELETE /currentScan request."""
    respx.delete("http://localhost:8080/currentScan").mock(
        return_value=httpx.Response(
            200, json={"message": "The current scan has been stopped."}
        ),
    )

    result = iv_adapter.stop_current_scan()

    assert result.ok is True
    assert "message" in result.payload


@respx.mock
def test_get_current_scan_success(iv_adapter: IVAdapter) -> None:
    """Test successful GET /currentScan request."""
    respx.get("http://localhost:8080/currentScan").mock(
        return_value=httpx.Response(200, json={"progress": 50}),
    )

    result = iv_adapter.get_current_scan()

    assert result.ok is True
    assert "progress" in result.payload


@respx.mock
def test_get_scan_comments(iv_adapter: IVAdapter) -> None:
    """Test GET /currentScan/comments request."""
    respx.get("http://localhost:8080/currentScan/comments").mock(
        return_value=httpx.Response(200, json={}),
    )

    result = iv_adapter.get_scan_comments()

    assert result.ok is True
    assert result.payload == {}


@respx.mock
def test_replace_scan_comments(iv_adapter: IVAdapter) -> None:
    """Test PUT /currentScan/comments request."""
    comments = {"notes": "test scan"}
    respx.put("http://localhost:8080/currentScan/comments").mock(
        return_value=httpx.Response(
            200, json={"message": "Comments updated successfully."}
        ),
    )

    result = iv_adapter.replace_scan_comments(comments)

    assert result.ok is True
    assert "message" in result.payload


@respx.mock
def test_get_latest_dataobject(iv_adapter: IVAdapter) -> None:
    """Test GET /results/latest request."""
    respx.get("http://localhost:8080/results/latest").mock(
        return_value=httpx.Response(200, json={}),
    )

    result = iv_adapter.get_latest_dataobject()

    assert result.ok is True
    assert result.payload == {}


@respx.mock
def test_get_latest_gas_detection(iv_adapter: IVAdapter) -> None:
    """Test GET /results/latest/gasDetection request."""
    payload = {"gasName": "ethanol", "confidence": 0.92}
    respx.get("http://localhost:8080/results/latest/gasDetection").mock(
        return_value=httpx.Response(200, json=payload),
    )

    result = iv_adapter.get_latest_gas_detection()

    assert result.ok is True
    assert result.payload == payload


@respx.mock
def test_get_gas_detection_result_by_id(iv_adapter: IVAdapter) -> None:
    """Test GET /results/id/{id}/gasDetection request."""
    payload = {"gasName": "acetone", "confidence": 0.81}
    respx.get("http://localhost:8080/results/id/result-123/gasDetection").mock(
        return_value=httpx.Response(200, json=payload),
    )

    result = iv_adapter.get_gas_detection_result("result-123")

    assert result.ok is True
    assert result.payload == payload


@respx.mock
def test_get_scan_dataobject_by_id(iv_adapter: IVAdapter) -> None:
    """Test GET /results/id/{id} request."""
    payload = {"id": "result-123", "scanName": "Scan 1"}
    respx.get("http://localhost:8080/results/id/result-123").mock(
        return_value=httpx.Response(200, json=payload),
    )

    result = iv_adapter.get_scan_dataobject("result-123")

    assert result.ok is True
    assert result.payload == payload


@respx.mock
def test_get_scan_result_commentobject_by_id(iv_adapter: IVAdapter) -> None:
    """Test GET /results/id/{id}/comments request."""
    payload = {"operator": "qa"}
    respx.get("http://localhost:8080/results/id/result-123/comments").mock(
        return_value=httpx.Response(200, json=payload),
    )

    result = iv_adapter.get_scan_result_commentobject("result-123")

    assert result.ok is True
    assert result.payload == payload


@respx.mock
def test_put_scan_result_commentobject_by_id(iv_adapter: IVAdapter) -> None:
    """Test PUT /results/id/{id}/comments request."""
    comments = {"operator": "qa"}
    respx.put("http://localhost:8080/results/id/result-123/comments").mock(
        return_value=httpx.Response(
            200, json={"message": "Stored result comments updated successfully."}
        ),
    )

    result = iv_adapter.put_scan_result_commentobject("result-123", comments)

    assert result.ok is True
    assert "message" in result.payload


@respx.mock
def test_get_parameter_id(iv_adapter: IVAdapter) -> None:
    """Test GET /currentParameter through get_parameter_ID()."""
    payload = {"id": "preset-1"}
    respx.get("http://localhost:8080/currentParameter").mock(
        return_value=httpx.Response(200, json=payload),
    )

    result = iv_adapter.get_parameter_ID()

    assert result.ok is True
    assert result.payload == payload


@respx.mock
def test_get_results_passes_expected_query_params(iv_adapter: IVAdapter) -> None:
    """Test GET /results request and query parameter mapping."""
    route = respx.get("http://localhost:8080/results").mock(
        return_value=httpx.Response(200, json={"results": []}),
    )

    result = iv_adapter.get_results(
        max_results=3,
        page=1,
        search="",
        start_date="2026-03-17T13:01:11.874Z",
        end_date="2026-03-25T13:01:11.874Z",
        sort_by="date_dsc",
        only_metadata=True,
    )

    assert result.ok is True
    assert result.payload == {"results": []}
    assert route.called is True

    params = route.calls.last.request.url.params
    assert params["max_results"] == "3"
    assert params["page"] == "1"
    assert params["search"] == ""
    assert params["start_date"] == "2026-03-17T13:01:11.874Z"
    assert params["end_date"] == "2026-03-25T13:01:11.874Z"
    assert params["sort_by"] == "date_dsc"
    assert params["only_metadata"].lower() == "true"


@respx.mock
def test_replace_scan_comments_with_empty_dict(iv_adapter: IVAdapter) -> None:
    """Test PUT /currentScan/comments with empty dict."""
    respx.put("http://localhost:8080/currentScan/comments").mock(
        return_value=httpx.Response(
            200, json={"message": "Comments updated successfully."}
        ),
    )

    result = iv_adapter.replace_scan_comments({})

    assert result.ok is True
    assert "message" in result.payload


def test_get_results_omits_empty_params(iv_adapter: IVAdapter) -> None:
    """Test that get_results does not forward empty query parameters."""
    iv_adapter._request = Mock(return_value=IVResult(ok=True, payload={"items": []}))

    iv_adapter.get_results(
        max_results=50,
        page=1,
        search="",
        start_date="  ",
        end_date="",
        sort_by=None,
        only_metadata=None,
        ids="",
    )

    iv_adapter._request.assert_called_once_with(
        "GET",
        "results",
        params={
            "max_results": 50,
            "page": 1,
            "search": "",
        },
    )


def test_get_results_keeps_false_and_zero_values(iv_adapter: IVAdapter) -> None:
    """Test that get_results keeps meaningful falsy values (False/0)."""
    iv_adapter._request = Mock(return_value=IVResult(ok=True, payload={"items": []}))

    iv_adapter.get_results(
        max_results=0,
        page=1,
        search=None,
        start_date=None,
        end_date=None,
        sort_by="timestamp",
        only_metadata=False,
        ids=None,
    )

    iv_adapter._request.assert_called_once_with(
        "GET",
        "results",
        params={
            "max_results": 0,
            "page": 1,
            "sort_by": "timestamp",
            "only_metadata": False,
        },
    )


@pytest.mark.parametrize("page", [-1, 0])
def test_get_results_rejects_page_numbers_below_one(
    iv_adapter: IVAdapter, page: int
) -> None:
    """Test that get_results validates page numbers before issuing a request."""
    iv_adapter._request = Mock(return_value=IVResult(ok=True, payload={"items": []}))

    result = iv_adapter.get_results(page=page)

    assert result.ok is False
    assert result.payload is None
    assert result.error == "page must be greater than or equal to 1"
    iv_adapter._request.assert_not_called()


# IVAdapter _request tests
@respx.mock
def test__request_returns_ivresult_on_2xx(iv_adapter: IVAdapter) -> None:
    """Test that _request returns IVResult(ok=True, payload=parsed_json, error=None) on 2xx."""
    payload = {"status": "ok", "version": "1.2.3"}
    respx.get("http://localhost:8080/health").mock(
        return_value=httpx.Response(200, json=payload),
    )

    result = iv_adapter._request("GET", "health")

    assert result.ok is True
    assert result.payload == payload
    assert result.error is None


@respx.mock
def test__request_returns_ivresult_on_non2xx(iv_adapter: IVAdapter) -> None:
    """Test that _request returns IVResult(ok=False, payload=None, error=str) on non-2xx."""
    respx.get("http://localhost:8080/health").mock(
        return_value=httpx.Response(500, json={"error": "Internal error"}),
    )

    result = iv_adapter._request("GET", "health")

    assert result.ok is False
    assert result.payload is None
    assert "500" in result.error


@respx.mock
def test__request_returns_ivresult_on_network_error(iv_adapter: IVAdapter) -> None:
    """Test that _request returns IVResult(ok=False, payload=None, error=str) on network errors."""
    respx.get("http://localhost:8080/health").mock(
        side_effect=httpx.ConnectError("connection failed"),
    )

    result = iv_adapter._request("GET", "health")

    assert result.ok is False
    assert result.payload is None
    assert "connection failed" in result.error


@respx.mock
def test__request_json_decode_error(iv_adapter: IVAdapter) -> None:
    """Test that _request returns IVResult(ok=False, payload=None, error=str) on JSON decode errors."""
    respx.get("http://localhost:8080/health").mock(
        return_value=httpx.Response(
            200,
            text="not valid json",
            headers={"Content-Type": "application/json"},
        ),
    )

    result = iv_adapter._request("GET", "health")

    assert result.ok is False
    assert result.payload is None
    assert "Expecting value" in result.error


@respx.mock
def test__request_base_url_with_trailing_slashes() -> None:
    """Test that _request doesn't fail on double trailing slashes."""
    iv_test_adapter = IVAdapter(
        base_url="http://localhost:8080/", ws_base_url="ws://localhost:8080"
    )

    respx.get("http://localhost:8080/health").mock(
        return_value=httpx.Response(
            200,
            json={"message": "ok"},
        ),
    )

    result = iv_test_adapter._request("GET", "health")

    assert result.ok is True
    assert result.payload == {"message": "ok"}
    assert result.error is None


# WebSocket test cases
def test_websocket_connect_and_disconnect_called_once(
    iv_adapter: IVAdapter,
) -> None:
    """Test that initialize_websocket and disconnect_websocket call the underlying WebSocketAdapter methods exactly once without parameters."""

    async def _exercise() -> None:
        iv_adapter._ws.connect = AsyncMock()
        iv_adapter._ws.disconnect = AsyncMock()

        await iv_adapter.initialize_websocket()
        await iv_adapter.disconnect_websocket()

    asyncio.run(_exercise())
    iv_adapter._ws.connect.assert_awaited_once_with()
    iv_adapter._ws.disconnect.assert_awaited_once_with()


def test_initialize_websocket_propagates_connect_error(
    iv_adapter: IVAdapter,
) -> None:
    """Test that initialize_websocket re-raises the same connect exception."""

    async def _exercise() -> RuntimeError:
        connect_error = RuntimeError("connect failed")
        iv_adapter._ws.connect = AsyncMock(side_effect=connect_error)

        with pytest.raises(RuntimeError) as exc_info:
            await iv_adapter.initialize_websocket()

        iv_adapter._ws.connect.assert_awaited_once_with()
        return exc_info.value

    exc = asyncio.run(_exercise())
    assert str(exc) == "connect failed"


def test_disconnect_websocket_propagates_disconnect_error(
    iv_adapter: IVAdapter,
) -> None:
    """Test that disconnect_websocket re-raises the same disconnect exception."""

    async def _exercise() -> RuntimeError:
        disconnect_error = RuntimeError("disconnect failed")
        iv_adapter._ws.disconnect = AsyncMock(side_effect=disconnect_error)

        with pytest.raises(RuntimeError) as exc_info:
            await iv_adapter.disconnect_websocket()

        iv_adapter._ws.disconnect.assert_awaited_once_with()
        return exc_info.value

    exc = asyncio.run(_exercise())
    assert str(exc) == "disconnect failed"


def test_websocket_connect_failure_resets_state(
    monkeypatch: pytest.MonkeyPatch, iv_adapter: IVAdapter
) -> None:
    """Test that failed websocket connect raises and leaves no partial connected state."""

    async def _exercise() -> AsyncMock:
        connect_error = RuntimeError("connect failed")
        mock_connect = AsyncMock(side_effect=connect_error)
        monkeypatch.setattr("app.adapters.ionVision.websockets.connect", mock_connect)

        with pytest.raises(
            Exception, match="Failed to connect to WebSocket: connect failed"
        ):
            await iv_adapter.initialize_websocket()

        assert iv_adapter._ws._running is False
        assert iv_adapter._ws._listen_task is None
        assert iv_adapter._ws._ws is None
        return mock_connect

    mock_connect = asyncio.run(_exercise())
    mock_connect.assert_awaited_once_with("ws://localhost:8080")


def test_ws_base_url_trimmed_on_initialization() -> None:
    """Test that ws_base_url trailing slashes are removed when creating _ws."""
    # Create adapter with trailing slash in ws_base_url
    iv_adapter = IVAdapter(
        base_url="http://localhost:8080",
        ws_base_url="ws://localhost:8080/",
    )

    # Verify the internal _ws was initialized with the trimmed URL
    assert iv_adapter._ws._base_url == "ws://localhost:8080"


def test_connect_success_path(iv_adapter: IVAdapter) -> None:
    """Test that initialize_websocket successfully calls connect on the WebSocketAdapter."""

    async def _exercise() -> None:
        iv_adapter._ws.connect = AsyncMock(return_value=None)

        await iv_adapter.initialize_websocket()

    asyncio.run(_exercise())
    iv_adapter._ws.connect.assert_awaited_once_with()


def test_disconnect_success_path(iv_adapter: IVAdapter) -> None:
    """Test that disconnect_websocket successfully calls disconnect on the WebSocketAdapter."""

    async def _exercise() -> None:
        iv_adapter._ws.disconnect = AsyncMock(return_value=None)

        await iv_adapter.disconnect_websocket()

    asyncio.run(_exercise())
    iv_adapter._ws.disconnect.assert_awaited_once_with()


def test_on_event_delegates_to_websocket_on_with_same_args(
    iv_adapter: IVAdapter,
) -> None:
    """Test that on_event forwards event key and callback reference to ws.on."""
    event_type = "message.error"
    handler = Mock()
    iv_adapter._ws.on = Mock()

    iv_adapter.on_event(event_type, handler)

    iv_adapter._ws.on.assert_called_once_with(event_type, handler)


def test_websocket_on_registers_handler_under_event_key() -> None:
    """Test that on() stores the exact callback reference under the provided event key."""
    ws_adapter = WebSocketAdapter("ws://localhost:8080")
    event_type = "scan.resultsProcessed"

    def handler(data: dict) -> None:
        _ = data

    ws_adapter.on(event_type, handler)

    assert event_type in ws_adapter._handlers
    assert len(ws_adapter._handlers[event_type]) == 1
    assert ws_adapter._handlers[event_type][0] is handler


def test_websocket_listen_loop_dispatches_full_documented_message_to_sync_handler() -> (
    None
):
    """Test that the listen loop forwards the full IonVision message envelope."""
    ws_adapter = WebSocketAdapter("ws://localhost:8080")
    payload = {
        "type": "controllers.status",
        "time": 1616057824108,
        "body": {
            "status": {"rtmReady": True},
            "sample": {},
            "sensor": {},
            "ambient": {},
        },
    }
    handler = Mock()
    ws_adapter.on("controllers.status", handler)
    ws_adapter._ws = FakeAsyncWebSocket([json.dumps(payload)])

    asyncio.run(ws_adapter._listen_loop())

    handler.assert_called_once_with(payload)


def test_websocket_listen_loop_dispatches_full_documented_message_to_async_handler() -> (
    None
):
    """Test that async handlers receive the same parsed websocket message."""
    ws_adapter = WebSocketAdapter("ws://localhost:8080")
    payload = {
        "type": "scan.progress",
        "time": 1616057824108,
        "body": {"progress": 12},
    }
    handler = AsyncMock()
    ws_adapter.on("scan.progress", handler)
    ws_adapter._ws = FakeAsyncWebSocket([json.dumps(payload)])

    asyncio.run(ws_adapter._listen_loop())

    handler.assert_awaited_once_with(payload)


def test_websocket_listen_loop_ignores_invalid_json_and_unknown_event() -> None:
    """Test that malformed or unregistered websocket frames do not dispatch."""
    ws_adapter = WebSocketAdapter("ws://localhost:8080")
    handler = Mock()
    ws_adapter.on("controllers.status", handler)
    ws_adapter._ws = FakeAsyncWebSocket(
        [
            "not-json",
            json.dumps({"type": "scan.finished", "time": 1, "body": {}}),
        ]
    )

    asyncio.run(ws_adapter._listen_loop())

    handler.assert_not_called()


def test_off_event_delegates_to_websocket_off_with_same_args(
    iv_adapter: IVAdapter,
) -> None:
    """Test that off_event forwards event key and callback reference to ws.off."""
    event_type = "scan.resultsProcessed"
    handler = Mock()
    iv_adapter._ws.off = Mock()

    iv_adapter.off_event(event_type, handler)

    iv_adapter._ws.off.assert_called_once_with(event_type, handler)


def test_websocket_off_removes_registered_handler_and_stops_callbacks() -> None:
    """Test that off() removes a registered handler so it no longer receives callbacks."""
    ws_adapter = WebSocketAdapter("ws://localhost:8080")
    event_type = "scan.resultsProcessed"
    handler = Mock()

    ws_adapter.on(event_type, handler)
    ws_adapter.off(event_type, handler)

    assert ws_adapter._handlers[event_type] == []

    # Simulate event dispatch from the underlying system.
    for callback in ws_adapter._handlers.get(event_type, []):
        callback({"type": event_type})

    handler.assert_not_called()
