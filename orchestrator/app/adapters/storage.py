from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Optional

from app.domain.models import ResultSummary


class StorageAdapter:
    def __init__(self, base_dir: str = "data") -> None:
        self._base_dir = Path(base_dir)
        self._results_dir = self._base_dir / "results"
        self._results_dir.mkdir(parents=True, exist_ok=True)

    def save_result(self, result: ResultSummary) -> None:
        path = self._results_dir / f"{result.id}.json"
        with path.open("w", encoding="utf-8") as handle:
            json.dump(asdict(result), handle, default=str, indent=2)

    def latest_result(self) -> Optional[ResultSummary]:
        items = sorted(self._results_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not items:
            return None
        data = json.loads(items[0].read_text(encoding="utf-8"))
        return ResultSummary(
            id=data["id"],
            pack_id=data["pack_id"],
            started_at=data["started_at"],
            finished_at=data.get("finished_at"),
            decision=data["decision"],
            dms_ppb=data.get("dms_ppb"),
            dms_compound=data.get("dms_compound"),
            image_path=data.get("image_path"),
        )
