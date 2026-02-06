from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

import httpx


@dataclass
class DmsResult:
    ok: bool
    payload: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class DmsAdapter:
    def __init__(self, base_url: str, timeout_s: float = 5.0, client: Optional[httpx.Client] = None) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_s
        self._client = client

    def read(self, pack_id: str) -> DmsResult:
        try:
            if self._client is not None:
                response = self._client.get(
                    f"{self._base_url}/dms/read",
                    params={"packId": pack_id},
                    timeout=self._timeout
                )
                response.raise_for_status()
                payload = response.json()
            else:
                with httpx.Client(timeout=self._timeout) as client:
                    response = client.get(
                        f"{self._base_url}/dms/read",
                        params={"packId": pack_id}
                    )
                    response.raise_for_status()
                    payload = response.json()
            return DmsResult(True, payload=payload)
        except Exception as exc:
            return DmsResult(False, error=str(exc))
