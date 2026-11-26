"""Write a research result to the site's Cloudflare KV and clear its 'running' marker.

Usage: python scripts/kv_put.py SYMBOL result.json
Env: CLOUDFLARE_API_TOKEN, CLOUDFLARE_ACCOUNT_ID, RESEARCH_KV_ID.
"""

from __future__ import annotations

import os
import sys
import urllib.parse
import urllib.request


def call(method: str, key: str, body: bytes | None = None) -> None:
    base = (
        f"https://api.cloudflare.com/client/v4/accounts/{os.environ['CLOUDFLARE_ACCOUNT_ID']}"
        f"/storage/kv/namespaces/{os.environ['RESEARCH_KV_ID']}/values/{urllib.parse.quote(key, safe='')}"
    )
    req = urllib.request.Request(
        base,
        data=body,
        method=method,
        headers={"Authorization": f"Bearer {os.environ['CLOUDFLARE_API_TOKEN']}"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        resp.read()


def main() -> int:
    symbol, path = sys.argv[1], sys.argv[2]
    call("PUT", f"r-{symbol}", open(path, "rb").read())
    try:
        call("DELETE", f"p-{symbol}")
    except Exception as exc:  # noqa: BLE001 - the marker also expires by itself
        print(f"Could not clear the running marker: {exc}")
    print(f"Stored research for {symbol}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
