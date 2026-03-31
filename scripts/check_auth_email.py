#!/usr/bin/env python3
"""
Auth email diagnostics.

Examples:
  python scripts/check_auth_email.py
  python scripts/check_auth_email.py --probe token
  python scripts/check_auth_email.py --probe smtp_login
  python scripts/check_auth_email.py --json
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

try:
    from dotenv import load_dotenv  # type: ignore
except Exception:
    load_dotenv = None  # type: ignore

ROOT_DIR = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.auth_email_diag import format_auth_email_diagnostic_report, run_auth_email_diagnostics


def main() -> int:
    parser = argparse.ArgumentParser(description="Diagnose auth email delivery configuration.")
    parser.add_argument(
        "--probe",
        choices=["auto", "token", "sendmail", "smtp_login"],
        default="auto",
        help="Run the transport-appropriate auth probe. Graph uses token/sendmail; SMTP uses smtp_login.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the diagnostic payload as JSON.",
    )
    args = parser.parse_args()

    if load_dotenv is not None:
        load_dotenv(override=False)

    result = run_auth_email_diagnostics(probe=args.probe)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        for line in format_auth_email_diagnostic_report(result):
            print(f"[auth-email-check] {line}")

    if result.get("ok"):
        return 0
    if result.get("config", {}).get("missing"):
        return 2
    return 1


if __name__ == "__main__":
    sys.exit(main())
