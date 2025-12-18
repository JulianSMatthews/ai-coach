"""
Helpers to record and fetch user check-ins (progress/blockers/commitments) for prompts.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional, List, Dict, Any

from .db import SessionLocal
from .models import CheckIn


def record_checkin(
    user_id: int,
    touchpoint_type: str,
    progress_updates: Optional[List[Dict[str, Any]]] = None,
    blockers: Optional[List[Dict[str, Any]]] = None,
    commitments: Optional[List[Dict[str, Any]]] = None,
    weekly_focus_id: Optional[int] = None,
    week_no: Optional[int] = None,
) -> int:
    """
    Persist a check-in and return its id.
    Each list item can be a small dict (e.g., {"kr_id": 1, "actual": 3, "note": "..."}).
    """
    with SessionLocal() as s:
        ci = CheckIn(
            user_id=user_id,
            touchpoint_type=touchpoint_type,
            progress_updates=progress_updates or [],
            blockers=blockers or [],
            commitments=commitments or [],
        )
        s.add(ci)
        s.flush()
        cid = ci.id
        s.commit()
        return cid


def fetch_recent_checkins(
    user_id: int,
    limit: int = 5,
    weekly_focus_id: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """
    Fetch recent check-ins (newest first) as dicts for prompt context.
    """
    with SessionLocal() as s:
        q = s.query(CheckIn).filter(CheckIn.user_id == user_id)
        if weekly_focus_id:
            # If weekly_focus_id is present, prefer check-ins with matching week (requires join if stored elsewhere).
            pass  # currently no direct column; check-ins are global per user
        q = q.order_by(CheckIn.created_at.desc()).limit(limit)
        out: List[Dict[str, Any]] = []
        for ci in q.all():
            out.append(
                {
                    "id": ci.id,
                    "touchpoint_type": ci.touchpoint_type,
                    "created_at": ci.created_at,
                    "progress_updates": ci.progress_updates or [],
                    "blockers": ci.blockers or [],
                    "commitments": ci.commitments or [],
                }
            )
        return out
