import pytest
import respx
import httpx
from app.adapters.ionVision import IVAdapter


BASE_URL = "http://localhost:8080"
WS_BASE_URL = "ws://localhost:8080"

@pytest.fixture
def iv_adapter() -> IVAdapter:
    return IVAdapter(base_url=BASE_URL,
                     ws_base_url=WS_BASE_URL)


@respx.mock
def test_get_current_scan_success(iv_adapter) -> None:
    """Test successful GET /currentScan request."""
    respx.get("http://localhost:8080/currentScan").mock(
        return_value=httpx.Response(200, json={"scanId": "123", "status": "ongoing"})
    )
    
    result = iv_adapter.get_current_scan()
    
    assert result.ok is True
    assert result.payload["scanId"] == "123"


@respx.mock
def test_get_current_scan_error(iv_adapter: IVAdapter) -> None:
    """Test failed GET /currentScan request."""
    respx.get("http://localhost:8080/currentScan").mock(
        return_value=httpx.Response(500, json={"error": "Internal error"})
    )
    
    result = iv_adapter.get_current_scan()
    
    assert result.ok is False
    assert "500" in result.error


@respx.mock
def test_start_new_scan(iv_adapter: IVAdapter) -> None:
    """Test POST /currentScan request."""
    respx.post("http://localhost:8080/currentScan").mock(
        return_value=httpx.Response(201, json={"scanId": "456"})
    )
    
    result = iv_adapter.start_new_scan()
    
    assert result.ok is True
    assert result.payload["scanId"] == "456"


@respx.mock
def test_replace_scan_comments(iv_adapter: IVAdapter) -> None:
    """Test PUT /currentScan/comments request."""
    comments = {"notes": "test scan"}
    respx.put("http://localhost:8080/currentScan/comments").mock(
        return_value=httpx.Response(200, json={"success": True})
    )
    
    result = iv_adapter.replace_scan_comments(comments)
    
    assert result.ok is True


@respx.mock
def test__request_returns_ivresult_on_2xx(iv_adapter: IVAdapter) -> None:
    """Test that _request returns IVResult(ok=True, payload=parsed_json, error=None) on 2xx."""
    payload = {"status": "ok", "version": "1.2.3"}
    respx.get("http://localhost:8080/health").mock(
        return_value=httpx.Response(200, json=payload)
    )

    result = iv_adapter._request("GET", "health")

    assert result.ok is True
    assert result.payload == payload
    assert result.error is None