"""
Documentation for the HTTP IonVision API can be found here:
https://olfactomics.github.io/IonVision-API-docs/

Websocket API documentation:
https://github.com/Olfactomics/IonVision-API-docs/blob/main/IonVision-WS-API.md
"""

from __future__ import annotations

import asyncio
import inspect
import json
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

import httpx
import websockets


@dataclass
class IVResult:
    ok: bool
    payload: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class IVAdapter:
    """HTTP adapter for the IonVision API.
    
    Provides methods to interact with the IonVision device via HTTP API,
    including scan management, results retrieval, and WebSocket event handling.
    
    Args:
    ----
        base_url: Base URL of the IonVision HTTP API
        ws_base_url: Base URL of the IonVision WebSocket API for event streaming
        timeout_s: HTTP request timeout in seconds (default: 5.0)
        client: Optional pre-configured httpx.Client instance (creates new one if not provided)
    """
    
    def __init__(
        self,
        base_url: str,
        ws_base_url: str,
        timeout_s: float = 5.0,
        client: Optional[httpx.Client] = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_s
        self._client = client
        self._ws = WebSocketAdapter(ws_base_url)

    def _request(self, method: str, endpoint: str, **kwargs) -> IVResult:
        """Make HTTP requests to the IonVision API.
        
        Handles both custom client instances and automatic client creation.
        All exceptions are caught and returned as IVResult failures.
        
        Args:
        ----
            method: HTTP method (GET, POST, PUT, DELETE, etc.)
            endpoint: API endpoint path (appended to base_url)
            **kwargs: Additional arguments passed to httpx.request()
        
        Returns:
        -------
            IVResult: Success result with JSON payload, or failure result with error string
        """
        try:
            if self._client is not None:
                response = self._client.request(
                    method,
                    f"{self._base_url}/{endpoint}",
                    timeout=self._timeout,
                    **kwargs,
                )
            else:
                with httpx.Client(timeout=self._timeout) as client:
                    response = client.request(
                        method,
                        f"{self._base_url}/{endpoint}",
                        **kwargs,
                    )

            response.raise_for_status()
            return IVResult(True, payload=response.json())

        except Exception as exc:
            return IVResult(False, error=str(exc))

    @staticmethod
    def _normalize_optional_string(value: Optional[str]) -> Optional[str]:
        """Normalize an optional string by stripping whitespace.
        
        Converts empty strings to None after stripping.
        
        Args:
        ----
            value: String to normalize, or None
        
        Returns:
        -------
            Stripped string or None if empty
        """
        if value is None:
            return None

        stripped = value.strip()
        return stripped or None

    @staticmethod
    def _normalize_search_string(value: Optional[str]) -> Optional[str]:
        """Normalize a search string by stripping whitespace.
        
        Args:
        ----
            value: Search string to normalize, or None
        
        Returns:
        -------
            Stripped search string or None
        """
        if value is None:
            return None
        return value.strip()

    @staticmethod
    def _validate_optional_int(
        name: str,
        value: Optional[int],
        *,
        minimum: Optional[int] = None,
    ) -> None:
        """Validate an optional integer parameter.
        
        Ensures the value is a true integer (not bool), and optionally
        checks that it meets a minimum threshold.
        
        Args:
        ----
            name: Parameter name (used in error messages)
            value: Integer to validate, or None
            minimum: Optional minimum allowed value (inclusive)
        
        Raises:
        ------
            ValueError: If value is not an integer or below minimum threshold
        """
        if value is None:
            return
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{name} must be an integer")
        if minimum is not None and value < minimum:
            raise ValueError(f"{name} must be greater than or equal to {minimum}")

    @staticmethod
    def _validate_optional_bool(name: str, value: Optional[bool]) -> None:
        """Validate an optional boolean parameter.
        
        Args:
        ----
            name: Parameter name (used in error messages)
            value: Boolean to validate, or None
        
        Raises:
        ------
            ValueError: If value is not a boolean
        """
        if value is None:
            return
        if not isinstance(value, bool):
            raise ValueError(f"{name} must be a boolean")

    def _build_results_params(
        self,
        *,
        max_results: Optional[int],
        page: Optional[int],
        search: Optional[str],
        start_date: Optional[str],
        end_date: Optional[str],
        sort_by: Optional[str],
        only_metadata: Optional[bool],
        ids: Optional[str],
    ) -> dict[str, Any]:
        """Build and validate query parameters for results endpoint.
        
        Validates input parameters and normalizes strings.
        Filters out None values from the parameter dictionary.
        
        Args:
        ----
            max_results: Maximum number of results to return (must be >= 0)
            page: Page number for pagination (must be >= 1)
            search: Search query string
            start_date: Start date filter (ISO format)
            end_date: End date filter (ISO format)
            sort_by: Sort field name
            only_metadata: Return only metadata if True
            ids: Comma-separated result IDs
        
        Returns:
        -------
            Dictionary of validated and normalized query parameters
        
        Raises:
        ------
            ValueError: If any parameter fails validation
        """
        self._validate_optional_int("max_results", max_results, minimum=0)
        self._validate_optional_int("page", page, minimum=1)
        self._validate_optional_bool("only_metadata", only_metadata)

        raw_params = {
            "max_results": max_results,
            "page": page,
            "search": self._normalize_search_string(search),
            "start_date": self._normalize_optional_string(start_date),
            "end_date": self._normalize_optional_string(end_date),
            "sort_by": self._normalize_optional_string(sort_by),
            "only_metadata": only_metadata,
            "ids": self._normalize_optional_string(ids),
        }
        return {key: value for key, value in raw_params.items() if value is not None}

    def ping(self) -> IVResult:
        """Lightweight reachability check against the IonVision API.
        
        Returns:
        -------
            IVResult with current parameter information if successful
        """
        return self._request("GET", "currentParameter")

    def get_current_scan(self) -> IVResult:
        """Check if a scan is ongoing and get information about it.
        
        Returns:
        -------
            IVResult with current scan details if a scan is running, empty if none
        """
        return self._request("GET", "currentScan")

    def start_new_scan(self) -> IVResult:
        """Start a new scan using the current project and parameter preset.
        
        A new scan can only be started if there is no scan currently ongoing.
        
        Returns:
        -------
            IVResult with scan start confirmation
        """
        return self._request("POST", "currentScan")

    def stop_current_scan(self) -> IVResult:
        """Stop the currently ongoing scan.
        
        Returns:
        -------
            IVResult with scan stop confirmation
        """
        return self._request("DELETE", "currentScan")

    def get_scan_comments(self) -> IVResult:
        """Get the comments object for the ongoing or next scan.
        
        The comments object is automatically reset when a scan finishes,
        and the previous comments are saved to the scan result file.
        
        Returns:
        -------
            IVResult with current comments object
        """
        return self._request("GET", "currentScan/comments")

    def replace_scan_comments(self, comments: dict) -> IVResult:
        """Replace the comments object for the ongoing or next scan.
        
        Args:
        ----
            comments: Dictionary containing the comment data
        
        Returns:
        -------
            IVResult with update confirmation
        """
        return self._request("PUT", "currentScan/comments", json=comments)

    def get_results(
        self,
        max_results: Optional[int] = None,
        page: Optional[int] = None,
        search: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        sort_by: Optional[str] = None,
        only_metadata: Optional[bool] = None,
        ids: Optional[str] = None,
    ) -> IVResult:
        """Search scan results stored on the device.
        
        Args:
        ----
            max_results: Maximum number of results to return
            page: Page number for pagination
            search: Search query string
            start_date: Filter by start date (ISO format)
            end_date: Filter by end date (ISO format)
            sort_by: Field to sort results by
            only_metadata: Return only metadata if True
            ids: Comma-separated result IDs to retrieve
        
        Returns:
        -------
            IVResult with list of matching scan results
        """
        try:
            params = self._build_results_params(
                max_results=max_results,
                page=page,
                search=search,
                start_date=start_date,
                end_date=end_date,
                sort_by=sort_by,
                only_metadata=only_metadata,
                ids=ids,
            )
        except ValueError as exc:
            return IVResult(False, error=str(exc))

        return self._request(
            "GET",
            "results",
            params=params,
        )

    def get_latest_dataobject(self) -> IVResult:
        """Get the data object of the latest scan result once processing is complete.
        
        Note: Processing may take time after a scan finishes. Check availability
        before calling this method to avoid null results.
        
        Returns:
        -------
            IVResult with latest scan data object
        """
        return self._request("GET", "results/latest")

    def get_latest_gas_detection(self) -> IVResult:
        """Get built-in gas detection results for the latest scan result.
        
        Returns:
        -------
            IVResult with gas detection data for latest scan
        """
        return self._request("GET", "results/latest/gasDetection")

    def get_gas_detection_result(self, id: str) -> IVResult:
        """Get built-in gas detection results for a specific scan result.
        
        Args:
        ----
            id: Scan result ID
        
        Returns:
        -------
            IVResult with gas detection data for specified scan
        """
        return self._request("GET", f"results/id/{id}/gasDetection")

    def get_scan_dataobject(self, id: str) -> IVResult:
        """Get the complete data object of a scan result.
        
        Args:
        ----
            id: Scan result ID
        
        Returns:
        -------
            IVResult with complete scan data object
        """
        return self._request("GET", f"results/id/{id}")

    def get_scan_result_commentobject(self, id: str) -> IVResult:
        """Get the comment object associated with a scan result.
        
        Args:
        ----
            id: Scan result ID
        
        Returns:
        -------
            IVResult with comment object for specified scan
        """
        return self._request("GET", f"results/id/{id}/comments")

    def put_scan_result_commentobject(
        self, id: str, comments: Dict[str, Any]
    ) -> IVResult:
        """Replace the comments object of a scan result.
        
        Args:
        ----
            id: Scan result ID
            comments: Dictionary containing updated comment data
        
        Returns:
        -------
            IVResult with update confirmation
        """
        return self._request("PUT", f"results/id/{id}/comments", json=comments)

    def get_parameter_ID(self) -> IVResult:
        """Get the ID of the parameter preset used for new scans.
        
        Returns:
        -------
            IVResult with current parameter preset ID
        """
        return self._request("GET", "currentParameter")

    async def initialize_websocket(self) -> None:
        """Initialize WebSocket connection for event streaming.
        
        Must be called after instantiation to open and enable event listening.
        """
        await self._ws.connect()

    async def disconnect_websocket(self) -> None:
        """Close WebSocket connection and stop listening for events."""
        await self._ws.disconnect()

    def on_event(
        self, event_type: str, handler: Callable[[Dict[str, Any]], Any]
    ) -> None:
        """Register a handler for a WebSocket event.

        Args:
        ----
            event_type: The type of event to listen for (e.g., "message.error", "scan.finished")
            handler: Async or sync callable that receives the full IonVision
                message envelope with ``type``, ``time`` and ``body`` keys
        """
        self._ws.on(event_type, handler)

    def off_event(
        self, event_type: str, handler: Callable[[Dict[str, Any]], Any]
    ) -> None:
        """Unregister a handler for a WebSocket event.

        Args:
        ----
            event_type: The event type to stop listening for
            handler: The handler function to remove
        """
        self._ws.off(event_type, handler)


class WebSocketAdapter:
    """Event-driven WebSocket adapter for IonVision API.

    Maintains a persistent WebSocket connection and dispatches events to registered handlers.
    IonVision WebSocket messages are JSON objects with ``type``, ``time`` and
    ``body`` keys. Any documented message type can be registered here, such as
    ``controllers.status``, ``scan.progress``, or ``message.error``. Handlers
    receive the full parsed message object.
    
    Supports both sync and async handler callbacks.
    """

    def __init__(self, base_url: str) -> None:
        """Initialize the WebSocket adapter.
        
        Args:
        ----
            base_url: WebSocket endpoint URL
        """
        self._base_url = base_url.rstrip("/")
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._running = False
        self._listen_task: Optional[asyncio.Task] = None
        self._handlers: Dict[str, List[Callable[[Dict[str, Any]], Any]]] = {}

    async def connect(self) -> None:
        """Establish the WebSocket connection and start listening for events.
        
        Raises:
        ------
            Exception: If connection fails
        """
        try:
            self._ws = await websockets.connect(self._base_url)
            self._running = True
            self._listen_task = asyncio.create_task(self._listen_loop())
        except Exception as exc:
            self._running = False
            raise Exception(f"Failed to connect to WebSocket: {exc}")

    async def disconnect(self) -> None:
        """Close the WebSocket connection and stop listening for events.
        
        Cancels the listen loop task and closes the connection.
        """
        self._running = False
        if self._listen_task:
            self._listen_task.cancel()
            try:
                await self._listen_task
            except asyncio.CancelledError:
                pass
        if self._ws:
            await self._ws.close()

    async def _listen_loop(self) -> None:
        """Continuously listen for WebSocket messages and dispatch to registered handlers.
        
        Parses incoming JSON messages and calls matching event handlers.
        Handles both sync and async handlers gracefully.
        """
        try:
            if self._ws is None:
                return

            async for raw_message in self._ws:
                try:
                    data = json.loads(raw_message)
                    if not isinstance(data, dict):
                        print(
                            "Ignoring websocket message because it is not a JSON object."
                        )
                        continue

                    await self._dispatch_event(data)
                except json.JSONDecodeError as e:
                    print(f"Failed to parse message: {e}")
                except Exception as e:
                    print(f"Error processing message: {e}")
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"Listen loop error: {e}")
        finally:
            self._running = False

    async def _dispatch_event(self, message: Dict[str, Any]) -> None:
        """Dispatch a parsed IonVision WebSocket message to matching handlers.
        
        Calls all registered handlers for the message event type,
        supporting both sync and async callables.
        
        Args:
        ----
            message: Parsed JSON message from WebSocket (contains 'type' key)
        """
        event_type = message.get("type")
        if not isinstance(event_type, str) or not event_type:
            return

        for handler in list(self._handlers.get(event_type, [])):
            try:
                result = handler(message)
                if inspect.isawaitable(result):
                    await result
            except Exception as exc:
                print(f"Handler error for {event_type}: {exc}")

    def on(self, event_type: str, handler: Callable[[Dict[str, Any]], Any]) -> None:
        """Register a handler for an event type.

        Args:
        ----
            event_type: The type of event to listen for (e.g., "message.error", "scan.finished")
            handler: Async or sync callable that receives the full IonVision
                message envelope with ``type``, ``time`` and ``body`` keys

        Example:
        -------
            async def handle_error(data):
                print(f"Error: {data}")

            ws_adapter.on("message.error", handle_error)

        """
        if event_type not in self._handlers:
            self._handlers[event_type] = []
        self._handlers[event_type].append(handler)

    def off(self, event_type: str, handler: Callable[[Dict[str, Any]], Any]) -> None:
        """Unregister a handler for an event type.

        Args:
        ----
            event_type: The event type
            handler: The handler to remove

        """
        if event_type in self._handlers:
            try:
                self._handlers[event_type].remove(handler)
            except ValueError:
                pass  # Handler not in list
