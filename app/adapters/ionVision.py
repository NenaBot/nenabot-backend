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
    def __init__(self, base_url: str, ws_base_url: str, timeout_s: float = 5.0, 
                 client: Optional[httpx.Client] = None) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_s
        self._client = client
        self._ws = WebSocketAdapter(ws_base_url)
    
    def _request(self, method: str, endpoint: str, **kwargs) -> IVResult:
        """Helper method to make HTTP requests to the IonVision API."""
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


    # scan management    
    def get_current_scan(self) -> IVResult:
        """Check if a scan is ongoing and get information about it.
        """
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
    
    def replace_scan_comments(self, comments:dict) -> IVResult:
        """Add comments to the ongoing or next scan. Replaces the previous comments object.
        The /currentScan/comments object can first be fetched for editing using GET.
        """
        return self._request("PUT", "currentScan/comments", json=comments)  


    #results
    def get_results(self, max_results:int, page:int, 
                    search:str, start_date:str, sort_by:str, 
                    only_metadata:bool, ids:str) -> IVResult:
        """Search the scan results that are stored on the device.
        """
        return self._request("GET", "results", params={
            "maxResults": max_results,
            "page": page,
            "search": search,
            "startDate": start_date,
            "sortBy": sort_by,
            "onlyMetadata": only_metadata,
            "ids": ids,
        })   

    def get_latest_dataobject(self) -> IVResult:
        """Get the data object of the latest scan result once it has been processed.
        Please note that it can take some time for the device to process the scan 
        result data after a scan has already been finished.       
        """
        return self._request("GET", "results/latest")  

    def get_latest_gas_detection(self) -> IVResult:
        """Get built-in gas detection results for the latest scan result.
        """
        return self._request("GET", "results/latest/gasDetection") 
    
    def get_gas_detection_result(self, id:str) -> IVResult:
        """Get built-in gas detection results for a scan result.
        """
        return self._request("GET", f"results/id/{id}/gasDetection")

    def get_scan_dataobject(self, id:str) -> IVResult:
        """Get the complete data object of a scan result.
        """
        return self._request("GET", f"results/id/{id}")
    
    def get_scan_result_commentobject(self, id:str) -> IVResult:
        """Get the comment object of a scan result.
        """
        return self._request("GET", f"results/id/{id}/comments")
    
    def put_scan_result_commentobject(self, id:str, comments: Dict[str, Any]) -> IVResult:
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

    # WEBSCOKET EVENT HANDLING #
    async def initialize_websocket(self) -> None:
        """Initialize WebSocket connection for event streaming.
        Must be called after instantiation to open the WebSocket.
        """
        await self._ws.connect()
    
    async def disconnect_websocket(self) -> None:
        """Close WebSocket connection and stop listening for events."""
        await self._ws.disconnect()
    
    def on_event(self, event_type: str, handler: Callable[[Dict[str, Any]], Any]) -> None:
        """Register a handler for a WebSocket event.
        
        Args:
        ----
            event_type: The type of event to listen for (e.g., "message.error", "scan.finished")
            handler: Async or sync callable that receives the event data dict

        """
        self._ws.on(event_type, handler)
    
    def off_event(self, event_type: str, handler: Callable[[Dict[str, Any]], Any]) -> None:
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

    Supported event types:
    - "scan.resultsProcessed": The results of the finished scan have been processed to device storage.
    - "message.error": An error or warning message. Contains unique error code.
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
                    event_type = data.get("type")
                    
                    # Call all registered handlers for this event type
                    if event_type in self._handlers:
                        for handler in self._handlers[event_type]:
                            try:
                                if inspect.iscoroutinefunction(handler):
                                    await handler(data)
                                else:
                                    handler(data)
                            except Exception as e:
                                print(f"Handler error for {event_type}: {e}")
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
    
    def on(self, event_type: str, handler: Callable[[Dict[str, Any]], Any]) -> None:
        """Register a handler for an event type.
        
        Args:
        ----
            event_type: The type of event to listen for (e.g., "message.error", "scan.finished")
            handler: Async or sync callable that receives the event data dict
        
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

    
