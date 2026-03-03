""" 
Documentation for the HTTP IonVision API can be found here:
https://olfactomics.github.io/IonVision-API-docs/ 

Websocket API documentation:
https://github.com/Olfactomics/IonVision-API-docs/blob/main/IonVision-WS-API.md
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any, Dict, Optional
import httpx
import websockets


@dataclass
class IVResult:
    ok: bool
    payload: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

# Adapter for the IonVision HTTP API
class IVAdapter:
    def __init__(self, base_url: str, timeout_s: float = 5.0, client: Optional[httpx.Client] = None) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_s
        self._client = client
    
    def _request(self, method: str, endpoint: str, **kwargs) -> IVResult:
        """Helper method to make HTTP requests to the IonVision API."""
        try:
            if self._client is not None:
                response = self._client.request(
                    method,
                    f"{self._base_url}/{endpoint}",
                    timeout=self._timeout,
                    **kwargs
                )
            else:
                with httpx.Client(timeout=self._timeout) as client:
                    response = client.request(
                        method,
                        f"{self._base_url}/{endpoint}",
                        **kwargs
                    )

            response.raise_for_status()
            return IVResult(True, payload=response.json())

        except Exception as exc:
            return IVResult(False, error=str(exc))


    # scan management    
    def get_current_scan(self) -> IVResult:
        """
        Check if a scan is ongoing and get information about it.
        """
        return self._request("GET", "currentScan")

    def start_new_scan(self) -> IVResult:
        """
        Starts a new scan using the current project and parameter preset. 
        A new scan can only be started if there is no scan currently ongoing.
        """
        return self._request("POST", "currentScan")

    def stop_current_scan(self) -> IVResult:
        """
        Starts a new scan using the current project and parameter preset. 
        A new scan can only be started if there is no scan currently ongoing.
        """
        return self._request("DELETE", "currentScan")
    
    def get_scan_comments(self) -> IVResult:
        """
        Get the comments object associated with the ongoing or next scan. 
        The comments object is automatically reset once a scan finishes 
        and the previous comments object is saved to the result file 
        of the just finished scan.
        """
        return self._request("GET", "currentScan/comments")
    
    def replace_scan_comments(self, comments:dict) -> IVResult:
        """
        Add comments to the ongoing or next scan. Replaces the previous comments object. 
        The /currentScan/comments object can first be fetched for editing using GET.
        """
        return self._request("PUT", "currentScan/comments", json=comments)  


    #results
    def get_results(self, max_results:int, page:int, 
                    search:str, start_date:str, sort_by:str, 
                    only_metadata:bool, ids:str) -> IVResult:
        """
        Search the scan results that are stored on the device.       
        """
        return self._request("GET", "results", params={
            "maxResults": max_results,
            "page": page,
            "search": search,
            "startDate": start_date,
            "sortBy": sort_by,
            "onlyMetadata": only_metadata,
            "ids": ids
        })   

    def get_latest_dataobject(self) -> IVResult:
        """
        Get the data object of the latest scan result once it has been processed. 
        Please note that it can take some time for the device to process the scan 
        result data after a scan has already been finished.       
        """
        return self._request("GET", "results/latest")  

    def get_latest_gas_detection(self) -> IVResult:
        """
        Get built-in gas detection results for the latest scan result.
        """
        return self._request("GET", "results/latest/gasDetection") 
    
    def get_gas_detection_result(self, id:str) -> IVResult:
        """
        Get built-in gas detection results for a scan result.
        """
        return self._request("GET", f"results/id/{id}/gasDetection")

    def get_scan_dataobject(self, id:str) -> IVResult:
        """
        Get the complete data object of a scan result.
        """
        return self._request("GET", f"results/id/{id}")
    
    def get_scan_result_commentobject(self, id:str) -> IVResult:
        """
        Get the comment object of a scan result.
        """
        return self._request("GET", f"results/id/{id}/comments")


    # parameters
    def get_parameter_ID(self) -> IVResult:
        """
        Get the ID of the parameter preset that currently is used for all new scans. 
        To access other parameter related functionality, use the /parameter/* endpoints.        
        """
        return self._request("GET", "currentParameter")


# Adapter for the IonVision WebSocket API
class WebSocketAdapter:
    def __init__(self, base_url: str, timeout_s: float = 5.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_s

    
    async def wait_for_events(self, event_type: str, timeout_s: Optional[float] = None) -> IVResult:
        """
        Wait for all the event types
        """
        timeout = self._timeout if timeout_s is None else timeout_s

        async def _listen() -> Optional[Dict[str, Any]]:
            async with websockets.connect(self._base_url) as ws:
                async for raw in ws:
                    data = json.loads(raw)
                    if data.get("type") == event_type:
                        return data
            return None

        try:
            if timeout and timeout > 0:
                payload = await asyncio.wait_for(_listen(), timeout=timeout)
            else:
                payload = await _listen()

            if payload is None:
                return IVResult(False, error=f"WebSocket closed before {event_type}")

            return IVResult(True, payload=payload)
        except asyncio.TimeoutError:
            return IVResult(False, error=f"Timed out waiting for {event_type}")
        except Exception as exc:
            return IVResult(False, error=str(exc))


    async def scan_stopped(self, timeout_s: Optional[float] = None) -> IVResult:
        """
        A scan has been stopped without finishing. No result data will be saved.
        """
        return await self.wait_for_events("scan.stopped", timeout_s)

    async def scan_finished(self, timeout_s: Optional[float] = None) -> IVResult:
        """
        A scan has been finished successfully. The results of the scan are still being processed and are not yet available.
        """
        return await self.wait_for_events("scan.finished", timeout_s)
    
    async def results_processed(self, timeout_s: Optional[float] = None) -> IVResult:
        """
        The results of the previously finished scan have been processed to the device storage.
        """
        return await self.wait_for_events("scan.resultsProcessed", timeout_s)
    
    async def scan_progress(self, timeout_s: Optional[float] = None) -> IVResult:
        """
        The progress of an ongoing scan.

            in body->progress {number} The progress of an ongoing scan 
            as a percentage integer from 0 to 100.        
        """
        return await self.wait_for_events("scan.progress", timeout_s)

    async def standby_button_pressed(self, timeout_s: Optional[float] = None) -> IVResult:
        """
        The standby button at the front panel of the device has been pressed 
        shortly. This is mainly used to show a "Do you want to power off the 
        device?" dialog in the user interface.   
        """
        return await self.wait_for_events("device.standbyButtonPressed", timeout_s)
    
    async def device_shutdown(self, timeout_s: Optional[float] = None) -> IVResult:
        """
        The device is powering off once this message is received. The device APIs 
        will no be usable shortly after this message.
        """
        return await self.wait_for_events("device.shutdown", timeout_s)
    
    async def error_message(self, timeout_s: Optional[float] = None) -> IVResult:
        """
        A error or warning message from the back-end.
        in body->code: {string} An unique error code describing what the error is.        
        """
        return await self.wait_for_events("message.error", timeout_s)
    
    async def limit_error(self, timeout_s: Optional[float] = None) -> IVResult:
        """
        An user set or safety limit has been crossed. The message always contains 
        every possible limit error and whether they are off (false) or on (true).

        * {boolean} The state of a single value error.     
        """
        return await self.wait_for_events("message.limitError", timeout_s)
    
    async def backup_started(self, timeout_s: Optional[float] = None) -> IVResult:
        """
        A process to back up the device has started. Some device features 
        like scanning are not available during this.
        """
        return await self.wait_for_events("backup.started", timeout_s)
    
    async def backup_finished(self, timeout_s: Optional[float] = None) -> IVResult:
        """
        A process to back up the device has finished successfully.
        """
        return await self.wait_for_events("backup.finished", timeout_s)

    
