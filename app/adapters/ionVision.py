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


# Adapter for the IonVision HTTP API
class IVAdapter:
    UCV_VALID_RANGE = (0, 2)

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
        """Make HTTP requests to the IonVision API."""
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
        if value is None:
            return None

        stripped = value.strip()
        return stripped or None

    @staticmethod
    def _normalize_search_string(value: Optional[str]) -> Optional[str]:
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
        if value is None:
            return
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{name} must be an integer")
        if minimum is not None and value < minimum:
            raise ValueError(f"{name} must be greater than or equal to {minimum}")

    @staticmethod
    def _validate_optional_bool(name: str, value: Optional[bool]) -> None:
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

    # health check
    def ping(self) -> IVResult:
        """Lightweight reachability check against the IonVision API."""
        return self._request("GET", "currentParameter")

    # scan management
    def get_current_scan(self) -> IVResult:
        """Check if a scan is ongoing and get information about it."""
        return self._request("GET", "currentScan")

    def start_new_scan(self) -> IVResult:
        """Starts a new scan using the current project and parameter preset.
        A new scan can only be started if there is no scan currently ongoing.
        """
        return self._request("POST", "currentScan")

    def stop_current_scan(self) -> IVResult:
        """Starts a new scan using the current project and parameter preset.
        A new scan can only be started if there is no scan currently ongoing.
        """
        return self._request("DELETE", "currentScan")

    def get_scan_comments(self) -> IVResult:
        """Get the comments object associated with the ongoing or next scan.
        The comments object is automatically reset once a scan finishes
        and the previous comments object is saved to the result file
        of the just finished scan.
        """
        return self._request("GET", "currentScan/comments")

    def replace_scan_comments(self, comments: dict) -> IVResult:
        """Add comments to the ongoing or next scan. Replaces the previous comments object.

        The /currentScan/comments object can first be fetched for editing using GET.
        """
        return self._request("PUT", "currentScan/comments", json=comments)

    # results
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
        """Search the scan results that are stored on the device."""
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
        """Get the data object of the latest scan result once it has been processed.

        Please note that it can take some time for the device to process the scan
        result data after a scan has already been finished.
        """
        return self._request("GET", "results/latest")

    def get_latest_gas_detection(self) -> IVResult:
        """Get built-in gas detection results for the latest scan result."""
        return self._request("GET", "results/latest/gasDetection")

    def get_gas_detection_result(self, id: str) -> IVResult:
        """Get built-in gas detection results for a scan result."""
        return self._request("GET", f"results/id/{id}/gasDetection")

    def get_scan_dataobject(self, id: str) -> IVResult:
        """Get the complete data object of a scan result."""
        return self._request("GET", f"results/id/{id}")

    def get_scan_result_commentobject(self, id: str) -> IVResult:
        """Get the comment object of a scan result."""
        return self._request("GET", f"results/id/{id}/comments")

    def put_scan_result_commentobject(
        self, id: str, comments: Dict[str, Any]
    ) -> IVResult:
        """Replaces the previous comments object of a scan result.
        The /results/id/{id}/comments object can first be
        fetched for editing using GET.
        """
        return self._request("PUT", f"results/id/{id}/comments", json=comments)

    # parameters
    def get_parameter_ID(self) -> IVResult:
        """Get the ID of the parameter preset that currently is used for all new scans.
        To access other parameter related functionality, use the /parameter/* endpoints.
        """
        return self._request("GET", "currentParameter")

    def evaluate_scan_data(self, data: dict) -> Optional[float]:
        """Evaluate scan payload and return an average intensity score.

        The function expects a websocket-style message envelope containing
        ``body.measurementData.ucv`` and ``body.measurementData.intensityTop``.
        It uses only UCV entries in the inclusive range defined by
        ``UCV_VALID_RANGE``, maps those indexes to
        ``intensityTop``, keeps the 3 highest numeric intensity values, and
        returns their arithmetic mean.

        Returns:
            Optional[float]: Average of the top 3 mapped intensity values, or
                ``None`` if the payload structure is invalid or fewer than 3
                usable intensity values are available.
        """
        if not isinstance(data, dict):
            return None

        # Get ucv list
        body = data.get("body", {})
        if not isinstance(body, dict):
            return None
        measurementData = body.get("measurementData", {})
        if not isinstance(measurementData, dict):
            return None

        ucv = measurementData.get("ucv", [])
        intensityTop = measurementData.get("intensityTop", [])
        if not isinstance(ucv, list) or not isinstance(intensityTop, list):
            return None

        # Get indexes of valid ucv values in the configured valid range.
        valid_indexes = [
            i
            for i, value in enumerate(ucv)
            if not isinstance(value, bool)
            and isinstance(value, (int, float))
            and self.UCV_VALID_RANGE[0] <= float(value) <= self.UCV_VALID_RANGE[1]
        ]

        # map the ucv values to their corresponding intensity values and take only
        # the 3 highest values
        valid_intensity_values = sorted(
            (
                float(intensityTop[i])
                for i in valid_indexes
                if i < len(intensityTop)
                and not isinstance(intensityTop[i], bool)
                and isinstance(intensityTop[i], (int, float))
            ),
            reverse=True,
        )[:3]

        if len(valid_intensity_values) != 3:
            return None

        return sum(valid_intensity_values) / len(valid_intensity_values)

    # WEBSCOKET EVENT HANDLING #
    async def initialize_websocket(self) -> None:
        """Initialize WebSocket connection for event streaming.
        Must be called after instantiation to open the WebSocket.
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
            event_type: The event type
            handler: The handler to remove

        """
        self._ws.off(event_type, handler)


# Adapter for the IonVision WebSocket API
class WebSocketAdapter:
    """Event-driven WebSocket adapter for IonVision API.

    Maintains a persistent connection and dispatches events to registered handlers.
    IonVision WebSocket messages are JSON objects with ``type``, ``time`` and
    ``body`` keys. Any documented message type can be registered here, such as
    ``controllers.status``, ``scan.progress`` or ``message.error``. Handlers
    receive the full parsed message object.
    """

    def __init__(self, base_url: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._running = False
        self._listen_task: Optional[asyncio.Task] = None
        self._handlers: Dict[str, List[Callable[[Dict[str, Any]], Any]]] = {}

    async def connect(self) -> None:
        """Establish the WebSocket connection and start listening for events."""
        try:
            self._ws = await websockets.connect(self._base_url)
            self._running = True
            self._listen_task = asyncio.create_task(self._listen_loop())
        except Exception as exc:
            self._running = False
            raise Exception(f"Failed to connect to WebSocket: {exc}")

    async def disconnect(self) -> None:
        """Close the WebSocket connection and stop listening."""
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
        """Continuously listen for messages and dispatch to registered handlers."""
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
        """Dispatch one parsed IonVision websocket message to matching handlers."""
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
