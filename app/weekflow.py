"""
Week orchestration helper: run kickoff (week 1 only), weekstart, midweek, and boost in sequence.
"""
from __future__ import annotations

from typing import Optional
from datetime import datetime, timedelta

from .models import User, WeeklyFocus, WeeklyFocusKR
from .nudges import send_whatsapp
from . import monday, wednesday, friday, tuesday, sunday
from .kickoff import generate_kickoff_podcast_audio, COACH_NAME
from .db import SessionLocal
from .focus import select_top_krs_for_user
from .reporting import generate_progress_report_html, _reports_root_for_user
import os
import shutil
from datetime import datetime, date


def _send_kickoff_podcast(user: User):
    try:
        audio_url, transcript = generate_kickoff_podcast_audio(user.id)
        if audio_url:
            send_whatsapp(
                to=user.phone,
                text=f"*Kickoff* Hi { (user.first_name or '').strip().title() or 'there' }, {COACH_NAME} here. Here’s your kickoff podcast—give it a listen: {audio_url}",
            )
    except Exception as e:
        send_whatsapp(to=user.phone, text=f"Couldn't generate kickoff briefing: {e}")


def _ensure_weekly_focus(user: User, week_no: int) -> bool:
    """
    Ensure a WeeklyFocus exists for the requested week number.
    - If an active focus exists for the requested window, reuse it.
    - Otherwise create a new one starting from the baseline week plus (week_no-1)*7 days.
    """
    today = datetime.utcnow().date()
    with SessionLocal() as s:
        # Use the earliest existing focus as the baseline so weeks advance consistently
        earliest = (
            s.query(WeeklyFocus)
            .filter(WeeklyFocus.user_id == user.id)
            .order_by(WeeklyFocus.starts_on.asc())
            .first()
        )
        base_start = earliest.starts_on if earliest else None
        if base_start is None:
            # No baseline: anchor to the current week (Monday of this week)
            base_start = today - timedelta(days=today.weekday())
        start = base_start + timedelta(days=7 * (week_no - 1))
        end = start + timedelta(days=6)

        existing = (
            s.query(WeeklyFocus)
            .filter(WeeklyFocus.user_id == user.id, WeeklyFocus.starts_on == start, WeeklyFocus.ends_on == end)
            .first()
        )
        if existing:
            return True

        selected = select_top_krs_for_user(s, user.id, limit=None, week_no=week_no)
        if not selected:
            send_whatsapp(to=user.phone, text="No active KRs found to propose. Please set OKRs first.")
            return False
        kr_ids = [kr_id for kr_id, _ in selected]
        wf = WeeklyFocus(user_id=user.id, starts_on=start, ends_on=end, notes=f"weekflow auto week {week_no}")
        s.add(wf); s.flush()
        for idx, kr_id in enumerate(kr_ids):
            s.add(WeeklyFocusKR(weekly_focus_id=wf.id, kr_id=kr_id, priority_order=idx, role="primary" if idx == 0 else "secondary"))
        s.commit()
        return True


def run_week_flow(user: User, week_no: int = 1) -> None:
    """
    Run the weekly sequence:
    - 12-week programme kickoff podcast (week 1 only)
    - Monday weekstart (every week)
    - Tuesday micro-check
    - midweek (Wednesday)
    - Thursday educational boost
    - boost (Friday)
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
    if week_no == 1:
        _send_kickoff_podcast(user)
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
    # Monday weekstart (weekly touchpoint) without retaining conversational state
    try:
        monday.start_kickoff(user, notes=f"weekflow week {week_no}", debug=False, set_state=False, week_no=week_no)
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
