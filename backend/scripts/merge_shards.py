"""Fold the parallel scan jobs' outputs into the shared data (backend/data).

Usage: uv run python scripts/merge_shards.py --expect 8 DIR [DIR ...]
Each DIR is one job's --delta-out folder. Folders marked idle (nothing to scan) are skipped.
A job that failed leaves no folder; with --expect, the scan then stays incomplete and the
next run scans that slice again.
"""

from __future__ import annotations

import sys
from pathlib import Path

from eqr.shards import merge

ROOT = Path(__file__).resolve().parent.parent


def main(args: list[str]) -> int:
    expect = 0
    if args[:1] == ["--expect"]:
        expect, args = int(args[1]), args[2:]
    dirs = [Path(a) for a in args if Path(a).is_dir()]
    missing = max(expect - len(dirs), 0)
    if missing:
        print(f"{missing} of {expect} jobs produced nothing (failed); their slices stay pending")
    active = [d for d in dirs if not (d / "idle").exists()]
    if not active:
        print(f"Nothing new from {len(dirs)} jobs: the latest scan is current")
        return 0
    result = merge(ROOT / "data", active, missing=missing)
    print(
        f"Merged {len(active)} jobs: {result.get('scanned', 0)} of {result.get('total', 0)} companies, "
        f"{'complete' if result.get('complete') else 'not complete yet (next run resumes)'}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
