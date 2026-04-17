from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import inspect
import time
from copy import deepcopy
from typing import Any, Callable
import uuid

from app.adapters.ionVision import IVAdapter, IVResult


class MockIVAdapter:
    """Deterministic IonVision adapter for frontend/dev mock mode."""

    UCV_VALID_RANGE = IVAdapter.UCV_VALID_RANGE

    def __init__(
        self,
        base_url: str,
        ws_base_url: str,
        timeout_s: float = 1.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._ws_base_url = ws_base_url.rstrip("/")
        self._timeout_s = timeout_s

        self._scan_started_at: float | None = None
        self._scan_id: str | None = None
        self._scan_status = "idle"
        self._scan_progress = 0
        self._comments: dict[str, Any] = {}
        self._latest_payload = self._build_latest_dataobject()
        self._results_processed_emitted = False

        self._handlers: dict[str, list[Callable[[dict[str, Any]], Any]]] = {}
        self._connected = False

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _build_mock_measurement_data() -> dict[str, Any]:
        # Keep the shape close to real IonVision dumps while staying lightweight.
        ucv = [-3.0, -2.5, -2.0, -1.5, -1.0, -0.5, 0.0, 0.5, 1.0, 1.5, 2.0, 2.5]
        intensity_top = [
            0.016,
            1.445,
            1.331,
            1.623,
            1.412,
            1.558,
            52.253,
            72.918,
            115.448,
            91.634,
            58.26,
            1.38,
        ]
        return {
            "DataValid": True,
            "DataPoints": len(ucv),
            "IntensityTop": intensity_top,
            "IntensityBottom": [
                133.466,
                -2.224,
                -2.305,
                -2.24,
                -2.126,
                -2.143,
                -53.015,
                -74.831,
                -130.28,
                -84.246,
                -23.407,
                -2.451,
            ],
            "Usv": [400] * len(ucv),
            "Ucv": ucv,
            "Vb": [-6] * len(ucv),
            "PP": [1000] * len(ucv),
            "PW": [220] * len(ucv),
            "NForSampleAverages": [2048] * len(ucv),
        }

    @staticmethod
    def _build_mock_system_data() -> dict[str, Any]:
        return {
            "ErrorRegister": {
                "sampleFlowR1Over": True,
                "sensorFlowR1Over": True,
                "sampleHeaterTemperatureR1Under": True,
                "sensorHeaterTemperatureR1Under": True,
            },
            "FetTemperature": {"Avg": 26, "Min": 25, "Max": 26},
            "Sample": {
                "Flow": {"Avg": 3.11, "Min": 3.08, "Max": 3.15},
                "Temperature": {"Avg": 24.98, "Min": 24.98, "Max": 24.99},
                "Pressure": {"Avg": 1008.65, "Min": 1008.65, "Max": 1008.75},
                "Humidity": {"Avg": 1.83, "Min": 1.82, "Max": 1.83},
                "PumpPWM": {"Avg": 100, "Min": 100, "Max": 100},
            },
            "Sensor": {
                "Flow": {"Avg": 6.06, "Min": 6.01, "Max": 6.06},
                "Temperature": {"Avg": 24.22, "Min": 24.21, "Max": 24.22},
                "Pressure": {"Avg": 899.64, "Min": 899.64, "Max": 899.86},
                "Humidity": {"Avg": 2.48, "Min": 2.44, "Max": 2.48},
                "PumpPWM": {"Avg": 100, "Min": 100, "Max": 100},
            },
            "Ambient": {
                "Temperature": {"Avg": 26.44, "Min": 26.43, "Max": 26.44},
                "Pressure": {"Avg": 1008.66, "Min": 1008.66, "Max": 1008.66},
                "Humidity": {"Avg": 8.03, "Min": 8.01, "Max": 8.03},
            },
        }

    def _build_latest_dataobject(self) -> dict[str, Any]:
        result_id = f"mock-result-{uuid.uuid4()}"
        start_time = self._now_iso()
        finish_time = self._now_iso()
        measurement_data = self._build_mock_measurement_data()
        evaluation = self.evaluate_scan_data({"MeasurementData": measurement_data})
        intensity_average = (
            float(evaluation.payload["intensity_average"])
            if evaluation.ok and evaluation.payload
            else 0.0
        )
        gas_detection = {"gasName": "ethanol", "confidence": 0.92}
        return {
            "id": result_id,
            "Id": result_id,
            "Measurer": "Laser",
            "StartTime": start_time,
            "scanId": self._scan_id or "",
            "scanName": "Mock Scan",
            "FinishTime": finish_time,
            "Date": finish_time,
            "Parameters": "mock-parameter-1",
            "Project": "NenaBot",
            "Comments": deepcopy(self._comments),
            "FormatVersion": 3,
            "SystemData": self._build_mock_system_data(),
            "information": deepcopy(self._comments),
            "MeasurementData": measurement_data,
            "body": {
                "measurementData": measurement_data,
                "gasDetection": gas_detection,
            },
            "gasDetection": gas_detection,
            "evaluation": {"intensity_average": intensity_average},
            "intensity_average": intensity_average,
            "meta": {"totalResults": 1, "mock": True},
            "results": [
                {
                    "compound": "Ethanol",
                    "gasName": "ethanol",
                    "confidence": 0.92,
                    "ppb": 42.0,
                    "intensity_average": intensity_average,
                }
            ],
        }

    def ping(self) -> IVResult:
        return IVResult(
            ok=True,
            payload={
                "parameter": {"id": "mock-parameter-1", "name": "Laser Wellplate"}
            },
        )

    def get_parameter_ID(self) -> IVResult:
        return self.ping()

    def start_new_scan(self) -> IVResult:
        if self._scan_status in {"running", "ongoing"}:
            return IVResult(ok=False, error="409 Conflict: scan already active")

        self._scan_started_at = time.monotonic()
        self._scan_id = f"mock-scan-{uuid.uuid4()}"
        self._scan_status = "ongoing"
        self._scan_progress = 0
        self._results_processed_emitted = False
        self._latest_payload = self._build_latest_dataobject()
        self._latest_payload["scanId"] = self._scan_id
        self._latest_payload["information"] = deepcopy(self._comments)

        # In mock mode scans complete quickly; emit resultsProcessed to unblock
        # orchestrator wait loops and return realistic payloads immediately.
        self.emit_event_sync("scan.resultsProcessed", {})
        self._results_processed_emitted = True
        self._scan_status = "finished"
        self._scan_progress = 100

        return IVResult(
            ok=True,
            payload={
                "message": "The new scan is now starting.",
                "scanId": self._scan_id,
            },
        )

    def stop_current_scan(self) -> IVResult:
        self._scan_status = "stopped"
        self._scan_progress = min(self._scan_progress, 99)
        self.emit_event_sync("scan.stopped", {})
        return IVResult(
            ok=True, payload={"message": "The current scan has been stopped."}
        )

    def get_current_scan(self) -> IVResult:
        if self._scan_started_at is None:
            return IVResult(
                ok=True,
                payload={
                    "information": {},
                    "state": "idle",
                    "status": "idle",
                    "progress": 0,
                },
            )

        elapsed = time.monotonic() - self._scan_started_at
        if elapsed < 1.0 and self._scan_status in {"running", "ongoing"}:
            self._scan_status = "ongoing"
            self._scan_progress = min(99, int(elapsed * 100))
            return IVResult(
                ok=True,
                payload={
                    "information": deepcopy(self._comments),
                    "state": self._scan_status,
                    "status": self._scan_status,
                    "progress": self._scan_progress,
                    "scanId": self._scan_id,
                    "remainingTime": max(0, int(10 - elapsed)),
                },
            )

        if self._scan_status in {"running", "ongoing"}:
            self._scan_status = "finished"
            self._scan_progress = 100
            self._latest_payload = self._build_latest_dataobject()
            self._latest_payload["scanId"] = self._scan_id
            self._latest_payload["information"] = deepcopy(self._comments)
            if not self._results_processed_emitted:
                self.emit_event_sync("scan.resultsProcessed", {})
                self._results_processed_emitted = True

        return IVResult(
            ok=True,
            payload={
                "information": deepcopy(self._comments),
                "state": self._scan_status,
                "status": self._scan_status,
                "progress": self._scan_progress,
                "scanId": self._scan_id,
                "remainingTime": 0,
            },
        )

    def get_latest_dataobject(self) -> IVResult:
        payload = deepcopy(self._latest_payload)
        if self._scan_id:
            payload["scanId"] = self._scan_id
        return IVResult(ok=True, payload=payload)

    def get_results(
        self,
        max_results: int | None = None,
        page: int | None = None,
        search: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        sort_by: str | None = None,
        only_metadata: bool | None = None,
        ids: str | None = None,
    ) -> IVResult:
        _ = (
            max_results,
            page,
            search,
            start_date,
            end_date,
            sort_by,
            only_metadata,
            ids,
        )
        latest = deepcopy(self._latest_payload)
        return IVResult(
            ok=True,
            payload={
                "meta": {"totalResults": 1, "page": 1},
                "results": [latest],
            },
        )

    def get_latest_gas_detection(self) -> IVResult:
        latest = self.get_latest_dataobject().payload or {}
        gas = latest.get("gasDetection")
        if isinstance(gas, dict):
            return IVResult(ok=True, payload=gas)
        return IVResult(ok=True, payload={"gasName": "ethanol", "confidence": 0.92})

    def get_gas_detection_result(self, id: str) -> IVResult:
        _ = id
        return self.get_latest_gas_detection()

    def get_scan_dataobject(self, id: str) -> IVResult:
        payload = deepcopy(self._latest_payload)
        payload["Id"] = id
        payload["id"] = id
        return IVResult(ok=True, payload=payload)

    def get_scan_comments(self) -> IVResult:
        return IVResult(ok=True, payload=deepcopy(self._comments))

    def replace_scan_comments(self, comments: dict[str, Any]) -> IVResult:
        self._comments = deepcopy(comments)
        return IVResult(ok=True, payload={"message": "Comments updated successfully."})

    def get_scan_result_commentobject(self, id: str) -> IVResult:
        _ = id
        return IVResult(ok=True, payload={})

    def put_scan_result_commentobject(
        self, id: str, comments: dict[str, Any]
    ) -> IVResult:
        _ = (id, comments)
        return IVResult(
            ok=True,
            payload={"message": "Stored result comments updated successfully."},
        )

    def evaluate_scan_data(self, data: dict[str, Any]) -> IVResult:
        # Keep evaluation semantics in sync with the production adapter.
        return IVAdapter.evaluate_scan_data(self, data)

    async def initialize_websocket(self) -> None:
        self._connected = True

    async def disconnect_websocket(self) -> None:
        self._connected = False

    def on_event(
        self, event_type: str, handler: Callable[[dict[str, Any]], Any]
    ) -> None:
        self._handlers.setdefault(event_type, []).append(handler)

    def off_event(
        self, event_type: str, handler: Callable[[dict[str, Any]], Any]
    ) -> None:
        handlers = self._handlers.get(event_type)
        if not handlers:
            return
        try:
            handlers.remove(handler)
        except ValueError:
            pass

    async def emit_event(self, event_type: str, body: dict[str, Any]) -> None:
        message = {"type": event_type, "time": int(time.time() * 1000), "body": body}
        for handler in list(self._handlers.get(event_type, [])):
            result = handler(message)
            if inspect.isawaitable(result):
                await result

    def emit_event_sync(self, event_type: str, body: dict[str, Any]) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(self.emit_event(event_type, body))
            return
        loop.create_task(self.emit_event(event_type, body))
