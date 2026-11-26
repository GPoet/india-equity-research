"""Store a secret in the Cloudflare Pages project's settings without it touching chat or shell
history: the value is read at a hidden prompt.

Usage: python3 backend/scripts/set_pages_secret.py GH_TOKEN
Uses the Cloudflare token in ~/.cloudflare-token (or CLOUDFLARE_API_TOKEN).
"""

from __future__ import annotations

import getpass
import json
import os
import sys
import urllib.request
from pathlib import Path

ACCOUNT = "fd61b4383616a55b4c4b37e724fecd01"
PROJECT = "equity-desk"


def main() -> int:
    name = sys.argv[1] if len(sys.argv) > 1 else ""
    if not name.isidentifier():
        print("Usage: set_pages_secret.py NAME")
        return 2
    token = os.environ.get("CLOUDFLARE_API_TOKEN") or Path.home().joinpath(".cloudflare-token").read_text().strip()
    value = os.environ.get("SECRET_VALUE") or getpass.getpass(f"{name} (input hidden): ").strip()
    if not value:
        print("Nothing entered; unchanged.")
        return 1
    env = {name: {"type": "secret_text", "value": value}}
    body = json.dumps({"deployment_configs": {"production": {"env_vars": env}, "preview": {"env_vars": env}}}).encode()
    req = urllib.request.Request(
        f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT}/pages/projects/{PROJECT}",
        data=body, method="PATCH",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        ok = json.load(resp).get("success")
    print(f"{name} {'saved' if ok else 'NOT saved'}. It applies from the next deploy.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
