"""
Week orchestration helper: run weekstart, midweek, and boost in sequence.
"""
from __future__ import annotations

from datetime import date

from .models import User, WeeklyFocus
from .nudges import send_whatsapp
from . import monday, wednesday, friday, tuesday, saturday, sunday
from .db import SessionLocal
from .reporting import generate_progress_report_html, _reports_root_for_user
from .weekly_plan import ensure_weekly_plan
import os
import shutil


def _ensure_weekly_focus(user: User, week_no: int) -> bool:
    """
    Ensure a WeeklyFocus exists for the requested week number.
    Uses the shared weekly plan helper used by coaching-start, Sunday, and Monday.
    """
    with SessionLocal() as s:
        _wf, kr_ids = ensure_weekly_plan(
            s,
            int(user.id),
            week_no=week_no,
            notes=f"weekflow auto week {week_no}",
            force_refresh_kr_links=True,
        )
        if not kr_ids:
            send_whatsapp(to=user.phone, text="No active KRs found to propose. Please set OKRs first.")
            return False
        s.commit()
        return True


def run_week_flow(user: User, week_no: int = 1) -> None:
    """
    Run the weekly sequence:
    - Monday weekstart (every week)
    - Tuesday micro-check
    - midweek (Wednesday)
    - Thursday educational boost
    - boost (Friday)
    - Saturday keepalive
    - Sunday review
    """
    # Set up per-week outbound log file for review
    reports_root = _reports_root_for_user(user.id)
    os.makedirs(reports_root, exist_ok=True)
    log_path = os.path.join(reports_root, f"week{week_no}_messages.txt")
    try:
        if os.path.exists(log_path):
            os.remove(log_path)  # start fresh for this run
    except Exception:
        pass
    # Touch the log file with a header so it exists even if no outbound messages occur
    try:
        with open(log_path, "w", encoding="utf-8") as f:
            f.write(f"[weekflow] week {week_no} message log start\n")
    except Exception:
        pass
    prev_log = os.environ.get("WEEKFLOW_LOG_FILE")
    os.environ["WEEKFLOW_LOG_FILE"] = log_path
    if not _ensure_weekly_focus(user, week_no):
        if prev_log is not None:
            os.environ["WEEKFLOW_LOG_FILE"] = prev_log
        else:
            os.environ.pop("WEEKFLOW_LOG_FILE", None)
        return

    # Determine anchor date (start of the current weekly focus) for reporting
    anchor_date: date | None = None
    with SessionLocal() as s:
        wf = (
            s.query(WeeklyFocus)
            .filter(WeeklyFocus.user_id == user.id)
            .order_by(WeeklyFocus.starts_on.desc())
            .first()
        )
        if wf and getattr(wf, "starts_on", None):
            try:
                anchor_date = wf.starts_on.date()
            except Exception:
                anchor_date = None
    # Generate and snapshot progress report at week start
    try:
        report_path = generate_progress_report_html(user.id, anchor_date=anchor_date)
        snap_path = os.path.join(reports_root, f"week{week_no}_progress.html")
        shutil.copyfile(report_path, snap_path)
        print(f"[weekflow] saved progress report: {snap_path}")
    except Exception as e:
        print(f"[weekflow] progress report failed: {e}")
    # Monday weekstart (weekly touchpoint) with support state enabled
    try:
        monday.start_weekstart(user, notes=f"weekflow week {week_no}", debug=False, set_state=True, week_no=week_no)
    except Exception as e:
        try:
            print(f"[weekflow] weekstart failed: {e}")
        except Exception:
            pass
    # Tuesday micro-check
    try:
        tuesday.send_tuesday_check(user)
    except Exception:
        pass
    # midweek
    wednesday.send_midweek_check(user)
    # thursday
    try:
        from .thursday import send_thursday_boost
        send_thursday_boost(user, week_no=week_no)
    except Exception:
        pass
    # boost
    friday.send_boost(user, week_no=week_no)
    # saturday keepalive
    try:
        saturday.send_saturday_keepalive(user)
    except Exception:
        pass
    # Sunday review
    try:
        sunday.send_sunday_review(user)
    except Exception as e:
        try:
            send_whatsapp(to=user.phone, text=f"*Sunday* review could not start: {e}")
        except Exception:
            pass

    # Restore previous logging setting
    if prev_log is not None:
        os.environ["WEEKFLOW_LOG_FILE"] = prev_log
    else:
        os.environ.pop("WEEKFLOW_LOG_FILE", None)
