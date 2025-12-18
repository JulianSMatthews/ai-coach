"""
Shared helper to log touchpoints (and linked KRs) in a single place.
"""
from __future__ import annotations

from datetime import datetime
from typing import Iterable

from .db import SessionLocal
from .models import Touchpoint, TouchpointKR


def log_touchpoint(
    user_id: int,
    tp_type: str,
    status: str = "sent",
    channel: str | None = "whatsapp",
    meta: dict | None = None,
    kr_ids: Iterable[int] | None = None,
    weekly_focus_id: int | None = None,
    week_no: int | None = None,
    generated_text: str | None = None,
    audio_url: str | None = None,
    scheduled_at=None,
    source_check_in_id: int | None = None,
) -> None:
    """
    Persist a touchpoint and optional KR links. Swallows errors (prints) so calling
    code isn't blocked by logging issues.
    """
    kr_list = list(kr_ids) if kr_ids else []
    with SessionLocal() as s:
        try:
            tp = Touchpoint(
                user_id=user_id,
                type=tp_type,
                weekly_focus_id=weekly_focus_id,
                week_no=week_no,
                status=status,
                channel=channel,
                meta=meta or {},
                generated_text=generated_text,
                audio_url=audio_url,
                source_check_in_id=source_check_in_id,
                sent_at=datetime.utcnow() if status == "sent" else None,
                scheduled_at=scheduled_at or datetime.utcnow(),
            )
            s.add(tp)
            s.flush()
            for idx, kr_id in enumerate(kr_list):
                s.add(
                    TouchpointKR(
                        touchpoint_id=tp.id,
                        kr_id=kr_id,
                        priority_order=idx,
                        role="primary" if idx == 0 else "secondary",
                        ask_text=None,
                    )
                )
            s.commit()
        except Exception as e:
            try:
                s.rollback()
            except Exception:
                pass
            print(f"[touchpoint] log failed for user {user_id}: {e}")
