#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv  # type: ignore
except Exception:  # pragma: no cover
    load_dotenv = None  # type: ignore

if load_dotenv is not None:
    load_dotenv(ROOT / ".env", override=True)

from app.education_plan import (  # noqa: E402
    generate_all_education_programme_avatar_videos,
    refresh_all_education_programme_avatar_videos,
)


def _db_label() -> str:
    raw = os.getenv("DATABASE_URL") or ""
    return raw.split("@")[-1] if "@" in raw else raw


def _print_summary(result: dict) -> None:
    counts = result.get("counts") if isinstance(result.get("counts"), dict) else {}
    print(f"database={_db_label()}")
    print(f"scope={result.get('scope') or '-'}")
    print(f"programme_count={int(result.get('programme_count') or 0)}")
    print(
        "counts="
        + ", ".join(f"{key}={value}" for key, value in counts.items())
    )
    for programme in result.get("programmes") or []:
        if not isinstance(programme, dict):
            continue
        programme_counts = programme.get("counts") if isinstance(programme.get("counts"), dict) else {}
        programme_name = str(programme.get("programme_name") or programme.get("programme_id") or "-").strip()
        count_text = ", ".join(f"{key}={value}" for key, value in programme_counts.items())
        print(f"{programme_name}: ok={bool(programme.get('ok'))} {count_text}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate or refresh education avatar videos across all education programmes.",
    )
    parser.add_argument(
        "mode",
        choices=("generate", "refresh"),
        help="generate creates missing videos one at a time; refresh caches completed jobs.",
    )
    parser.add_argument(
        "--include-inactive",
        action="store_true",
        help="Include inactive education programmes. The default is active programmes only.",
    )
    parser.add_argument(
        "--regenerate",
        action="store_true",
        help="Generate mode only: start new jobs even when videos already exist.",
    )
    parser.add_argument(
        "--start-only",
        action="store_true",
        help="Generate mode only: start Azure jobs without waiting for each one to complete.",
    )
    parser.add_argument(
        "--max-new-jobs",
        type=int,
        default=None,
        help="Generate mode only: maximum new videos/jobs to process in this run.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the full result as JSON instead of a compact summary.",
    )
    args = parser.parse_args()

    if args.mode == "generate":
        result = generate_all_education_programme_avatar_videos(
            regenerate=bool(args.regenerate),
            active_only=not bool(args.include_inactive),
            max_new_jobs=args.max_new_jobs,
            wait_for_completion=not bool(args.start_only),
        )
    else:
        if args.regenerate:
            parser.error("--regenerate can only be used with generate")
        if args.start_only:
            parser.error("--start-only can only be used with generate")
        if args.max_new_jobs is not None:
            parser.error("--max-new-jobs can only be used with generate")
        result = refresh_all_education_programme_avatar_videos(
            active_only=not bool(args.include_inactive),
        )

    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        _print_summary(result)
    return 0 if bool(result.get("ok")) else 1


if __name__ == "__main__":
    raise SystemExit(main())
