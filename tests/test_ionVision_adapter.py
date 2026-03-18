"""Tests for the IonVision HTTP adapter."""

from unittest.mock import AsyncMock

import httpx
import pytest
import respx

from app.adapters.ionVision import IVAdapter

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
    iv_test_adapter = IVAdapter(base_url="http://localhost:8080/", ws_base_url="ws://localhost:8080/")

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
    """Test that initialize_websocket and disconnect_websocket call the underlying WebSocketAdapter methods exactly once."""  # noqa: E501
    # Arrange: replace WebSocketAdapter methods with awaitable mocks
    iv_adapter._ws.connect = AsyncMock()
    iv_adapter._ws.disconnect = AsyncMock()

    # Act: single connect/disconnect flow
    await iv_adapter.initialize_websocket()
    await iv_adapter.disconnect_websocket()

    # Assert: each called exactly once
    iv_adapter._ws.connect.assert_awaited_once()
    iv_adapter._ws.disconnect.assert_awaited_once()