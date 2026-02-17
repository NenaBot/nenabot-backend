""" 
Documentation for the HTTP IonVision API can be found here:
https://olfactomics.github.io/IonVision-API-docs/ 
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional
import httpx


@dataclass
class IVResult:
    ok: bool
    payload: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


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