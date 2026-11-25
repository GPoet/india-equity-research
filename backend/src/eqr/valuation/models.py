"""Result types shared by every valuation lens."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

Number = float | int | str | None


@dataclass(frozen=True)
class LensResult:
    key: str
    name: str
    school: str  # who uses it: "Warren Buffett", "Benjamin Graham", ...
    kind: str  # "value" (per share) | "score" | "screen" | "metric"
    applicable: bool
    value: float | None = None
    verdict: str | None = None
    summary: str = ""
    inputs: dict[str, Number] = field(default_factory=dict)
    reason: str | None = None  # why it could not run

    def to_dict(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}


def not_applicable(key: str, name: str, school: str, kind: str, reason: str) -> LensResult:
    return LensResult(key=key, name=name, school=school, kind=kind, applicable=False, reason=reason)
