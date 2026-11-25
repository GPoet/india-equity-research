"""Local settings from backend/.env (git-ignored). Only named keys are read."""

from __future__ import annotations

import os
from collections.abc import Iterable
from pathlib import Path

ENV_PATH = Path(__file__).resolve().parents[2] / ".env"


def load_env(path: Path = ENV_PATH, keys: Iterable[str] = ()) -> dict[str, str]:
    wanted = set(keys)
    out: dict[str, str] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k, v = k.strip(), v.strip().strip('"').strip("'")
            if k in wanted and v:
                out[k] = v
    for k in wanted:  # real environment variables win over the file
        if os.environ.get(k):
            out[k] = os.environ[k]
    return out
