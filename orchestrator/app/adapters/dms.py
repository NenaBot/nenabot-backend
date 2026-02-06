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
    def __init__(self, base_url: str, timeout_s: float = 5.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_s

    def read(self, pack_id: str) -> DmsResult:
        try:
            response = httpx.get(f"{self._base_url}/dms/read", params={"packId": pack_id}, timeout=self._timeout)
            response.raise_for_status()
            return DmsResult(True, payload=response.json())
        except Exception as exc:
            return DmsResult(False, error=str(exc))
