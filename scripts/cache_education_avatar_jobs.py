#!/usr/bin/env python3
from __future__ import annotations

import argparse
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

from sqlalchemy import select  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.education_plan import refresh_education_lesson_avatar  # noqa: E402
from app.models import EducationLessonVariant  # noqa: E402


def _db_label() -> str:
    raw = os.getenv("DATABASE_URL") or ""
    return raw.split("@")[-1] if "@" in raw else raw


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Cache completed Azure education avatar jobs into education lesson variant video URLs.",
    )
    parser.add_argument("job_ids", nargs="+", help="Azure avatar batch job IDs to refresh")
    args = parser.parse_args()

    print(f"database={_db_label()}")
    exit_code = 0
    with SessionLocal() as session:
        for job_id in args.job_ids:
            normalized_job_id = str(job_id or "").strip()
            if not normalized_job_id:
                continue
            row = (
                session.execute(
                    select(EducationLessonVariant).where(
                        EducationLessonVariant.avatar_job_id == normalized_job_id
                    )
                )
                .scalars()
                .first()
            )
            if row is None:
                print(f"{normalized_job_id}: no matching education_lesson_variants row")
                exit_code = 1
                continue
            result = refresh_education_lesson_avatar(int(row.id))
            avatar = result.get("avatar") if isinstance(result, dict) else {}
            if not isinstance(avatar, dict):
                avatar = {}
            video_url = str(avatar.get("url") or avatar.get("video_url") or "").strip()
            status = str(avatar.get("status") or "").strip()
            error = str(avatar.get("error") or "").strip()
            print(
                f"{normalized_job_id}: variant_id={int(row.id)} status={status or 'unknown'} "
                f"video_url={video_url or '-'} error={error or '-'}"
            )
            if not video_url:
                exit_code = 1
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
