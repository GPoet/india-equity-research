"""File cache for research reports: per company and model, 12 hours, atomic writes."""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any

CACHE_HOURS = 12
SCHEMA_VERSION = 2


class ResearchStore:
    def __init__(self, directory: Path, max_age_hours: float = CACHE_HOURS) -> None:
        self._dir = directory
        self._max_age = max_age_hours * 3600

    def path(self, symbol: str, model: str) -> Path:
        safe = re.sub(r"[^A-Za-z0-9_&-]", "_", f"{symbol}_{model}")
        return self._dir / f"{safe}.json"

    def load(self, symbol: str, model: str) -> dict[str, Any] | None:
        path = self.path(symbol, model)
        if not path.exists() or time.time() - path.stat().st_mtime > self._max_age:
            return None
        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            return None
        return data if data.get("schema_version") == SCHEMA_VERSION else None

    def save(self, symbol: str, model: str, data: dict[str, Any]) -> None:
        path = self.path(symbol, model)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({**data, "schema_version": SCHEMA_VERSION}, indent=1))
        os.replace(tmp, path)
