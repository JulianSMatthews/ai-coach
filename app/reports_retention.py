from __future__ import annotations

import os
import re
from datetime import datetime, timedelta
from typing import Any

from .reports_paths import resolve_reports_dir

_WEEKLY_AUDIO_RE = re.compile(
    r"^(monday_week\d+|thursday(?:_week\d+)?|friday(?:_week\d+)?|kickoff(?:_week\d+)?)\.mp3$",
    re.IGNORECASE,
)
_ASSESSMENT_AUDIO_RE = re.compile(
    r"^assessment_(\d+)_(score|okr|coaching)\.mp3$",
    re.IGNORECASE,
)
_USER_DIR_RE = re.compile(r"^\d+$")


def _env_int(name: str, default: int) -> int:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except Exception:
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = (os.getenv(name) or "").strip().lower()
    if not raw:
        return default
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return default


def _is_user_dir(name: str) -> bool:
    return bool(_USER_DIR_RE.match(str(name or "").strip()))


def _delete_file(path: str, *, dry_run: bool) -> int:
    size = 0
    try:
        size = int(os.path.getsize(path))
    except Exception:
        size = 0
    if not dry_run:
        try:
            os.remove(path)
        except FileNotFoundError:
            return 0
    return size


def _cleanup_weekly_audio(
    reports_dir: str,
    *,
    cutoff_dt: datetime,
    dry_run: bool,
) -> dict[str, int]:
    scanned = 0
    matched = 0
    removed = 0
    bytes_reclaimed = 0

    cutoff_ts = cutoff_dt.timestamp()
    for entry in os.scandir(reports_dir):
        if not entry.is_dir() or not _is_user_dir(entry.name):
            continue
        user_dir = entry.path
        for fname in os.listdir(user_dir):
            scanned += 1
            if not _WEEKLY_AUDIO_RE.match(fname):
                continue
            matched += 1
            full_path = os.path.join(user_dir, fname)
            try:
                st = os.stat(full_path)
            except FileNotFoundError:
                continue
            except Exception:
                continue
            if st.st_mtime >= cutoff_ts:
                continue
            bytes_reclaimed += _delete_file(full_path, dry_run=dry_run)
            removed += 1

    return {
        "weekly_files_scanned": scanned,
        "weekly_files_matched": matched,
        "weekly_files_removed": removed,
        "weekly_bytes_reclaimed": bytes_reclaimed,
    }


def _cleanup_assessment_audio(
    reports_dir: str,
    *,
    keep_runs: int,
    dry_run: bool,
) -> dict[str, int]:
    scanned = 0
    matched = 0
    removed = 0
    bytes_reclaimed = 0

    safe_keep_runs = max(0, int(keep_runs))
    for entry in os.scandir(reports_dir):
        if not entry.is_dir() or not _is_user_dir(entry.name):
            continue
        user_dir = entry.path
        files_by_run: dict[int, list[str]] = {}
        for fname in os.listdir(user_dir):
            scanned += 1
            m = _ASSESSMENT_AUDIO_RE.match(fname)
            if not m:
                continue
            matched += 1
            run_id = int(m.group(1))
            files_by_run.setdefault(run_id, []).append(os.path.join(user_dir, fname))
        if not files_by_run:
            continue
        keep_ids = set(sorted(files_by_run.keys(), reverse=True)[:safe_keep_runs])
        for run_id, paths in files_by_run.items():
            if run_id in keep_ids:
                continue
            for full_path in paths:
                bytes_reclaimed += _delete_file(full_path, dry_run=dry_run)
                removed += 1

    return {
        "assessment_files_scanned": scanned,
        "assessment_files_matched": matched,
        "assessment_files_removed": removed,
        "assessment_bytes_reclaimed": bytes_reclaimed,
    }


def run_reports_retention(
    *,
    reports_dir: str | None = None,
    weekly_retention_days: int = 84,
    keep_assessment_runs: int = 2,
    dry_run: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    root = str(reports_dir or resolve_reports_dir()).strip()
    anchor = now or datetime.utcnow()
    if not root:
        return {"ok": False, "error": "reports_dir_empty"}
    if not os.path.isdir(root):
        return {"ok": False, "error": "reports_dir_missing", "reports_dir": root}

    days = max(1, int(weekly_retention_days))
    keep_runs = max(0, int(keep_assessment_runs))
    cutoff_dt = anchor - timedelta(days=days)

    weekly = _cleanup_weekly_audio(root, cutoff_dt=cutoff_dt, dry_run=dry_run)
    assessments = _cleanup_assessment_audio(root, keep_runs=keep_runs, dry_run=dry_run)

    reclaimed = int(weekly["weekly_bytes_reclaimed"]) + int(assessments["assessment_bytes_reclaimed"])
    removed = int(weekly["weekly_files_removed"]) + int(assessments["assessment_files_removed"])
    return {
        "ok": True,
        "dry_run": bool(dry_run),
        "reports_dir": root,
        "weekly_retention_days": days,
        "keep_assessment_runs": keep_runs,
        "cutoff_utc": cutoff_dt.isoformat(),
        "files_removed": removed,
        "bytes_reclaimed": reclaimed,
        "mb_reclaimed": round(reclaimed / (1024 * 1024), 3),
        "weekly": weekly,
        "assessment": assessments,
    }


def run_reports_retention_from_env(*, dry_run: bool = False) -> dict[str, Any]:
    enabled = _env_bool("REPORTS_RETENTION_ENABLED", True)
    if not enabled:
        return {"ok": True, "skipped": True, "reason": "REPORTS_RETENTION_ENABLED=0"}
    weekly_days = _env_int("REPORTS_WEEKLY_RETENTION_DAYS", 84)
    keep_runs = _env_int("REPORTS_ASSESSMENT_KEEP_RUNS", 2)
    return run_reports_retention(
        weekly_retention_days=weekly_days,
        keep_assessment_runs=keep_runs,
        dry_run=dry_run,
    )

