"""
Shared helper to log touchpoints (and linked KRs) in a single place.
"""
from __future__ import annotations

from datetime import datetime
from typing import Iterable

from .db import SessionLocal
from sqlalchemy import select

from .models import OKRKeyResult, Touchpoint, TouchpointKR


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
) -> int | None:
    """
    Persist a touchpoint and optional KR links. Returns touchpoint id on success.
    Swallows errors (prints) so calling code isn't blocked by logging issues.
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
            if kr_list:
                rows = s.execute(select(OKRKeyResult.id).where(OKRKeyResult.id.in_(kr_list))).all()
                valid_ids = {row[0] for row in rows}
            else:
                valid_ids = set()
            for idx, kr_id in enumerate([kid for kid in kr_list if kid in valid_ids]):
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
            return tp.id
        except Exception as e:
            try:
                s.rollback()
            except Exception:
                pass
            print(f"[touchpoint] log failed for user {user_id}: {e}")
            return None


def update_touchpoint(
    touchpoint_id: int,
    *,
    generated_text: str | None = None,
    audio_url: str | None = None,
    status: str | None = None,
    meta: dict | None = None,
    source_check_in_id: int | None = None,
) -> None:
    """
    Best-effort update for an existing touchpoint (e.g., add closing text or link check-in).
    """
    with SessionLocal() as s:
        try:
            tp = s.query(Touchpoint).get(touchpoint_id)
            if not tp:
                return
            if generated_text:
                tp.generated_text = generated_text
            if audio_url:
                tp.audio_url = audio_url
            if status:
                tp.status = status
                if status == "sent" and tp.sent_at is None:
                    tp.sent_at = datetime.utcnow()
            if source_check_in_id:
                tp.source_check_in_id = source_check_in_id
            if meta:
                tp.meta = {**(tp.meta or {}), **meta}
            s.commit()
        except Exception as e:
            try:
                s.rollback()
            except Exception:
                pass
            print(f"[touchpoint] update failed for id {touchpoint_id}: {e}")
