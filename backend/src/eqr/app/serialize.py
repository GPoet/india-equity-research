"""Make results JSON-safe: dataclasses and pydantic models to dicts, NaN/inf to null,
dates to ISO strings."""

from __future__ import annotations

import dataclasses
import math
from datetime import date, datetime
from typing import Any


def clean(value: Any) -> Any:
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [clean(v) for v in value]
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return clean({f.name: getattr(value, f.name) for f in dataclasses.fields(value)})
    if hasattr(value, "model_dump"):
        return clean(value.model_dump())
    if hasattr(value, "item"):  # numpy scalars
        return clean(value.item())
    return value
