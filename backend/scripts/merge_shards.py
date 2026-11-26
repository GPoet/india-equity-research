"""Fold the parallel scan jobs' outputs into the shared data (backend/data).

Usage: uv run python scripts/merge_shards.py DIR [DIR ...]
Each DIR is one job's --delta-out folder. Folders marked idle (nothing to scan) are skipped.
"""

from __future__ import annotations

import sys
from pathlib import Path

from eqr.shards import merge

ROOT = Path(__file__).resolve().parent.parent


def main(args: list[str]) -> int:
    dirs = [Path(a) for a in args if Path(a).is_dir()]
    active = [d for d in dirs if not (d / "idle").exists()]
    if not active:
        print(f"Nothing new from {len(dirs)} jobs: the latest scan is current")
        return 0
    result = merge(ROOT / "data", active)
    print(
        f"Merged {len(active)} jobs: {result.get('scanned', 0)} of {result.get('total', 0)} companies, "
        f"{'complete' if result.get('complete') else 'not complete yet (next run resumes)'}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
