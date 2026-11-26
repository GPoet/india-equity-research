"""One research run for the hosted site (GitHub Actions). Writes the result as JSON in the
shape the research panel expects: {"status": "done", "data": ...} or {"status": "failed", ...}.

Usage: uv run python scripts/research_job.py SYMBOL --out result.json
Claude runs through the CLI with CLAUDE_CODE_OAUTH_TOKEN (a subscription token, as Owl uses).
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from eqr.app.serialize import clean
from eqr.app.services import LiveServices
from eqr.llm.claude_cli import LlmError


def main() -> int:
    logging.basicConfig(level=logging.WARNING)
    ap = argparse.ArgumentParser()
    ap.add_argument("symbol")
    ap.add_argument("--out", required=True)
    ap.add_argument("--model", default="sonnet")
    args = ap.parse_args()
    try:
        data = LiveServices().run_research(args.symbol.upper(), args.model)
        result = {"status": "done", "data": data}
    except LlmError as exc:
        result = {"status": "failed", "error": str(exc), "kind": exc.kind}
    except Exception as exc:  # noqa: BLE001 - report, never leave the page waiting forever
        result = {"status": "failed", "error": f"Research failed: {type(exc).__name__}", "kind": "internal"}
    Path(args.out).write_text(json.dumps(clean(result)))
    print(result["status"], result.get("error", ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
