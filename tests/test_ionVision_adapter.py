"""Tests for the IonVision HTTP adapter."""

from unittest.mock import AsyncMock, Mock

import httpx
import pytest
import respx

from app.adapters.ionVision import IVAdapter, WebSocketAdapter

BASE_URL = "http://localhost:8080"
WS_BASE_URL = "ws://localhost:8080"

@pytest.fixture
def iv_adapter() -> IVAdapter:
    """Create an IonVision adapter for unit tests."""
    return IVAdapter(base_url=BASE_URL,
                     ws_base_url=WS_BASE_URL)


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
def test_start_new_scan(iv_adapter: IVAdapter) -> None:
    """Test POST /currentScan request."""
    respx.post("http://localhost:8080/currentScan").mock(
        return_value=httpx.Response(201, 
                                    json={"message": "The new scan is now starting."}),
    )
    
    result = iv_adapter.start_new_scan()
    
    assert result.ok is True
    assert "message" in result.payload

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
        return_value=httpx.Response(200, 
                                    json={"message": "Comments updated successfully."}),
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
def test_replace_scan_commets_with_empty_dict(iv_adapter: IVAdapter) -> None:
    """Test PUT /currentScan/comments with empty dict."""
    respx.put("http://localhost:8080/currentScan/comments").mock(
        return_value=httpx.Response(200, 
                                    json={"message": "Comments updated successfully."}),
    )
    
    result = iv_adapter.replace_scan_comments({})
    
    assert result.ok is True
    assert "message" in result.payload

# IVAdapter _request tests
@respx.mock
def test__request_returns_ivresult_on_2xx(iv_adapter: IVAdapter) -> None:
    """Test that _request returns IVResult(ok=True, payload=parsed_json, error=None) on 2xx."""  # noqa: E501
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
    """Test that _request returns IVResult(ok=False, payload=None, error=str) on non-2xx."""  # noqa: E501
    respx.get("http://localhost:8080/health").mock(
        return_value=httpx.Response(500, json={"error": "Internal error"}),
    )

    result = iv_adapter._request("GET", "health")

    assert result.ok is False
    assert result.payload is None
    assert "500" in result.error


@respx.mock
def test__request_returns_ivresult_on_network_error(iv_adapter: IVAdapter) -> None:
    """Test that _request returns IVResult(ok=False, payload=None, error=str) on network errors."""  # noqa: E501
    respx.get("http://localhost:8080/health").mock(
        side_effect=httpx.ConnectError("connection failed"),
    )

    result = iv_adapter._request("GET", "health")

    assert result.ok is False
    assert result.payload is None
    assert "connection failed" in result.error

@respx.mock
def test__request_json_decode_error(iv_adapter: IVAdapter) -> None:
    """Test that _request returns IVResult(ok=False, payload=None, error=str) on JSON decode errors."""  # noqa: E501
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
    iv_test_adapter = IVAdapter(base_url="http://localhost:8080/", ws_base_url="ws://localhost:8080")

    respx.get("http://localhost:8080/health").mock(
        return_value=httpx.Response(
            200, json={"message": "ok"},
        ),
    )

    result = iv_test_adapter._request("GET", "health")

    assert result.ok is True
    assert result.payload == {"message": "ok"}
    assert result.error is None
    
# WebSocket test cases
@pytest.mark.asyncio
async def test_websocket_connect_and_disconnect_called_once(iv_adapter: IVAdapter) -> None:  # noqa: E501
    """Test that initialize_websocket and disconnect_websocket call the underlying WebSocketAdapter methods exactly once without parameters.""" #noqa: E501
    # Arrange: replace WebSocketAdapter methods with awaitable mocks
    iv_adapter._ws.connect = AsyncMock()
    iv_adapter._ws.disconnect = AsyncMock()

    # Act: single connect/disconnect flow
    await iv_adapter.initialize_websocket()
    await iv_adapter.disconnect_websocket()

    # Assert: each called exactly once and no args were forwarded
    iv_adapter._ws.connect.assert_awaited_once_with()
    iv_adapter._ws.disconnect.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_initialize_websocket_propagates_connect_error(iv_adapter: IVAdapter) -> None:  # noqa: E501
    """Test that initialize_websocket re-raises the same connect exception."""
    connect_error = RuntimeError("connect failed")
    iv_adapter._ws.connect = AsyncMock(side_effect=connect_error)

    with pytest.raises(RuntimeError) as exc_info:
        await iv_adapter.initialize_websocket()

    assert exc_info.value is connect_error
    iv_adapter._ws.connect.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_disconnect_websocket_propagates_disconnect_error(iv_adapter: IVAdapter) -> None:  # noqa: E501
    """Test that disconnect_websocket re-raises the same disconnect exception."""
    disconnect_error = RuntimeError("disconnect failed")
    iv_adapter._ws.disconnect = AsyncMock(side_effect=disconnect_error)

    with pytest.raises(RuntimeError) as exc_info:
        await iv_adapter.disconnect_websocket()

    assert exc_info.value is disconnect_error
    iv_adapter._ws.disconnect.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_websocket_connect_failure_resets_state(
    monkeypatch: pytest.MonkeyPatch, iv_adapter: IVAdapter) -> None:
    """Test that failed websocket connect raises and leaves no partial connected state."""  # noqa: E501
    connect_error = RuntimeError("connect failed")
    mock_connect = AsyncMock(side_effect=connect_error)
    monkeypatch.setattr("app.adapters.ionVision.websockets.connect", mock_connect)

    with pytest.raises(Exception, 
                       match="Failed to connect to WebSocket: connect failed"):
        await iv_adapter.initialize_websocket()

    assert iv_adapter._ws._running is False
    assert iv_adapter._ws._listen_task is None
    assert iv_adapter._ws._ws is None
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

@pytest.mark.asyncio
async def test_connect_success_path(iv_adapter: IVAdapter) -> None:
    """Test that initialize_websocket successfully calls connect on the WebSocketAdapter."""  # noqa: E501
    iv_adapter._ws.connect = AsyncMock(return_value=None)

    await iv_adapter.initialize_websocket()
    iv_adapter._ws.connect.assert_awaited_once_with()

@pytest.mark.asyncio
async def test_disconnect_success_path(iv_adapter: IVAdapter) -> None:
    """Test that disconnect_websocket successfully calls disconnect on the WebSocketAdapter."""  # noqa: E501
    iv_adapter._ws.disconnect = AsyncMock(return_value=None)

    await iv_adapter.disconnect_websocket()
    iv_adapter._ws.disconnect.assert_awaited_once_with()


def test_on_event_delegates_to_websocket_on_with_same_args(iv_adapter: IVAdapter) -> None:
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


def test_off_event_delegates_to_websocket_off_with_same_args(iv_adapter: IVAdapter) -> None:
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





