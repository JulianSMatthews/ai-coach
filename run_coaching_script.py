#!/usr/bin/env python3
"""
Run coaching/touchpoint simulations *without* running an assessment.

Examples
  python run_coaching_script.py --user-id 1 --week 4
  python run_coaching_script.py --user-id 1 --simulate-week-one
  python run_coaching_script.py --user-id 1 --simulate-12-weeks --start-week 5 --sleep 2
"""
from __future__ import annotations

import os
import sys
import time
import argparse

# Ensure project root is on sys.path
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from app.db import SessionLocal
from app.models import User
from app import weekflow, sunday

# Reuse helpers from assessment script
import run_assessment_script as ras


def _get_user(user_id: int) -> User | None:
    with SessionLocal() as s:
        return s.query(User).filter(User.id == user_id).one_or_none()


def _simulate_week(user: User, week_no: int) -> None:
    weekflow.run_week_flow(user, week_no=week_no)
    ras._simulate_monday_support(user, week_no)
    if not sunday.has_active_state(user.id):
        print(f"[simulate] Sunday state missing for week {week_no}, skipping canned answers.")
        return
    responses = ras._build_sunday_responses(user)
    for resp in responses:
        sunday.handle_message(user, resp)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run coaching simulations (touchpoints only).")
    parser.add_argument("--user-id", type=int, required=True, help="Target user id")
    parser.add_argument("--week", type=int, default=None, help="Run a single week number")
    parser.add_argument("--simulate-week-one", action="store_true", help="Run week 1 only")
    parser.add_argument("--simulate-12-weeks", action="store_true", help="Run weeks 1–12")
    parser.add_argument("--start-week", type=int, default=1, help="Start from this week (for 12-week run)")
    parser.add_argument("--sleep", type=float, default=2.0, help="Seconds to sleep between weeks")
    args = parser.parse_args()

    user = _get_user(args.user_id)
    if not user:
        print(f"[error] user not found: {args.user_id}")
        sys.exit(1)

    ras._patch_weekflow_outbound_noop()

    if args.week:
        print(f"[simulate] week {args.week}/1")
        _simulate_week(user, args.week)
        return

    if args.simulate_week_one:
        print("[simulate] week 1/1")
        _simulate_week(user, 1)
        return

    if args.simulate_12_weeks:
        start_week = max(1, min(12, args.start_week))
        for wk in range(start_week, 13):
            print(f"[simulate] week {wk}/12")
            _simulate_week(user, wk)
            if wk < 12:
                time.sleep(args.sleep)
        return

    print("[error] choose --week, --simulate-week-one, or --simulate-12-weeks")
    sys.exit(1)


if __name__ == "__main__":
    main()
