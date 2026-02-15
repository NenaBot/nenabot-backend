""" 
Documentation for the HTTP IonVision API can be found here:
https://olfactomics.github.io/IonVision-API-docs/ 
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional
from urllib.parse import quote
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
    

    # scope mode (continouous scanning mode) management
    def is_in_scope_mode(self) -> IVResult:
        """
        Check if the device is in scope mode.
        """
        return self._request("GET", "scope")
    
    def switch_to_scopemode(self) -> IVResult:
        """
        Move the device to scope mode using the current scope mode parameters.
        """
        return self._request("POST", "scope")
    
    def switch_to_idlemode(self) -> IVResult:
        """
        This starts moving the device away from scope mode into idle. The change is not instant, 
        the ongoing or just starting scan is completed before the device is idle again. 
        New scans or scope mode can't be started before that. In rare cases the stop signal 
        can hapen in a transitory state and scope scanning will continue even after the user stops it. 
        In those cases simply attempt to stop the scope mode again until it actually stops.
        """
        return self._request("DELETE", "scope")
    
    def get_latest_scopemode_result(self) -> IVResult:
        """
        Get the latest scope mode result data if available.
        """
        return self._request("GET", "scope/latestResult")

    def get_current_scopemode_parameters(self) -> IVResult:
        """
        Get the current scope mode parameters.
        """
        return self._request("GET", "scope/parameters")
    
    def set_current_scopemode_parameters(self, params:dict) -> IVResult:
        """
        Sets the current scope mode parameters. If scope mode is currently enabled, 
        the currently used parameteres won't be updated unless scope mode is stopped 
        and started again.
        """
        return self._request("PUT", "scope/parameters", json=params)
    
    
    # user management
    def get_current_username(self) -> IVResult:
        """
        Get the username that will be saved to the results of all scans made with this device..        
        """
        return self._request("GET", "currentUser")
    
    def set_new_username(self, username:dict) -> IVResult:
        """
        Replaces the previosuly set username. The username is just a string 
        aappended to scan results and can be any string desired.        
        """
        return self._request("PUT", "currentUser", json=username)
    

    # parameters
    def get_parameter_ID(self) -> IVResult:
        """
        Get the ID of the parameter preset that currently is used for all new scans. 
        To access other parameter related functionality, use the /parameter/* endpoints.        
        """
        return self._request("GET", "currentParameter")
    
    def set_parameter_preset(self, paramID:dict) -> IVResult:
        """
        Sets a new parameter preset for the device to use for new scans using the ID of the parameter. 
        The parameter must be included in the current project for it to work here. 
        To access other parameter related functionality, use the /parameter/* endpoints.
        """
        return self._request("PUT", "currentParameter", json=paramID)
    
    def preload_current_parameter_preset(self) -> IVResult:
        """
        Preload the current parameter preset so environmental parameters 
        can take effect before a scan is started.
        """
        return self._request("POST", "currentParameter/preload")
    
    def get_all_parameters(self) -> IVResult:
        """
        Get a list of names and ID's of all of the parameters on the device.        
        """
        return self._request("GET", "parameter")
    
    def add_new_parameter(self, parameter:dict) -> IVResult:
        """
        Save a new parameter to the device
        """
        return self._request("POST", "parameter", json=parameter)
    
    def get_parameter_definition_object(self, parameter_id:str) -> IVResult:
        """
        Get a parameter definition object.
        """
        safe_id = quote(parameter_id, safe="")
        return self._request("GET", f"parameter/{safe_id}")
    
    def update_parameter_preset(self, parameter_id:str, definition_obj:dict) -> IVResult:
        """
        Update a parameter that has already been created. This will only work if the parameter does 
        not have any scan results that have used it saved on the device. Otherwise a new parameter 
        must be created.
        """
        safe_id = quote(parameter_id, safe="")
        return self._request("PUT", "parameter/{safe_id}", json=definition_obj)
    
    def remove_parameter(self, parameter_id:str) -> IVResult:
        """
        Removes a parameter if it does not have any scan results that have used it saved on the device. 
        If there are scan results that use the parameter, you must remove all scan results made with 
        the parameter first. The correct results can be quickly found using the /parameter/{ID}/result endpoint.
        """
        safe_id = quote(parameter_id, safe="")
        return self._request("DELETE", f"parameter/{safe_id}")
    
    def get_parameter_metadata(self,parameter_id:str) -> IVResult:
        """
        Get just the metadata of the parameter.
        """
        safe_id = quote(parameter_id, safe="")
        return self._request("GET", f"parameter/{safe_id}/metadata")
    
    def get_parameter_scan_results(self,parameter_id:str) -> IVResult:
        """
        Get a list of ID's of scan results that have been measured using this parameter.
        """
        safe_id = quote(parameter_id, safe="")
        return self._request("GET", f"parameter/{safe_id}/results")
    
    def get_parameter_gases(self, parameter_id:str) -> IVResult:
        """
        Get a list of gases that this parameter preset can be used to detect.
        """
        safe_id = quote(parameter_id, safe="")
        return self._request("GET", f"parameter/{safe_id}/gasDetection")
    
    def get_parameter_templates(self, parameter_name:str, gas_detection:bool) -> IVResult:
        """
        Get a list of parameter templates available on the device.
        """
        return self._request("GET", 
                             "parameterTemplate", 
                             params={
                                    "parameterName": parameter_name,
                                    "gasDetection": gas_detection
                                    }
                            )
    
    def get_parameter_preset_template_contens(self, unique_name:str) -> IVResult:
        """
        Get the contents of a parameter preset template.
        """
        safe_name = quote(unique_name, safe="")
        return self._request("GET", f"parameterTemplate/{safe_name}")
    
    def get_parameter_template_metadata(self, unique_name:str) -> IVResult:
        """
        Get the metadata of a single parameter preset template.
        """
        safe_name = quote(unique_name, safe="")
        return self._request("GET", f"parameterTemplate/{safe_name}/metadata")

    
