from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import inspect
import time
from copy import deepcopy
from typing import Any, Callable

from app.adapters.ionVision import IVResult


class MockIVAdapter:
    """Deterministic IonVision adapter for frontend/dev mock mode."""

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

    def _build_latest_dataobject(self) -> dict[str, Any]:
        result_id = f"mock-result-{int(time.time())}"
        return {
            "Id": result_id,
            "scanId": self._scan_id or "",
            "scanName": "Mock Scan",
            "FinishTime": self._now_iso(),
            "Date": self._now_iso(),
            "information": deepcopy(self._comments),
            "meta": {"totalResults": 1, "mock": True},
            "results": [
                {
                    "compound": "Ethanol",
                    "gasName": "ethanol",
                    "confidence": 0.92,
                    "ppb": 42.0,
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
        self._scan_id = f"mock-scan-{int(time.time())}"
        self._scan_status = "ongoing"
        self._scan_progress = 0
        self._results_processed_emitted = False

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
        if elapsed < 1.0 and self._scan_status != "stopped":
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

        if self._scan_status != "stopped":
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
        return IVResult(ok=True, payload={"gasName": "ethanol", "confidence": 0.92})

    def get_gas_detection_result(self, id: str) -> IVResult:
        _ = id
        return self.get_latest_gas_detection()

    def get_scan_dataobject(self, id: str) -> IVResult:
        payload = deepcopy(self._latest_payload)
        payload["Id"] = id
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
