"""Sandbox connectivity spike (setup verification, not the project).

Run AFTER creating sandbox account + API keys + .env:
  python scripts/sandbox_spike.py
Exits non-zero with a plain-words diagnosis if anything is missing.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv

load_dotenv()

from app.services.airwallex_client import AirwallexClient  # noqa: E402


def main() -> int:
    try:
        c = AirwallexClient()
        token = c.login()
    except Exception as e:
        print(f"LOGIN FAILED: {e}")
        print("Fix: sandbox.airwallex.com signup (business name 'New Business Sandbox'), "
              "Account > Developer > API keys, copy to .env")
        return 1
    print(f"login ok (token {len(token)} chars, 30-min life)")
    try:
        accts = c.global_accounts()
    except Exception as e:
        print(f"LIST ACCOUNTS FAILED: {e}")
        return 1
    items = accts.get("items", accts if isinstance(accts, list) else [])
    print(f"global accounts: {len(items)} (empty list = connected, just unfunded)")
    try:
        print(f"balances: {str(c.balances())[:200]}")
    except Exception as e:
        print(f"balances note: {e}")
    if not items:
        print("NEXT: create a USD Global Account + simulate a 25000 deposit (see docs/SETUP.md)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
