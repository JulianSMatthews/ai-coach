from __future__ import annotations

import csv
import hashlib
import io
import os
import re
import secrets
import threading
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import desc, func, or_, select
from sqlalchemy.orm import Session

from . import config
from .messaging import normalize_phone, send_sms
from .models import Conversation, ImportBatch, Member, MessageLog, OkrKeyResult, OkrObjective, StaffTask, SurveyConfig
from .surveys import (
    SURVEY_FLOWS,
    SurveyFlow,
    classify_response,
    flow_config_payload,
    flow_for_key,
    flow_from_config,
    is_outcome_locked_flow,
    normalize_option_answer,
    question_options,
    response_summary,
    response_summary_for_flow,
)


_SURVEY_AVATAR_THREAD_LOCK = threading.Lock()
_SURVEY_AVATAR_THREADS: dict[str, threading.Thread] = {}

Q2_2026_OKR_PRESET: tuple[dict[str, Any], ...] = (
    {
        "number": 1,
        "area": "Club Growth",
        "champions": "Soph & Ben",
        "title": "Grow club revenue to GBP 70,000+ in Q2 to strengthen the club's financial foundation.",
        "description": "Q2 2026 OKR: April to June.",
        "key_results": (
            {"title": "Achieve >=30% prospect-to-member conversion rate monthly", "target": 30, "unit": "%"},
            {"title": "Ensure >=50% of new joiners pay the GBP 30 set-up fee", "target": 50, "unit": "%"},
            {"title": "Generate >=120 qualified marketing leads per month", "target": 120, "unit": "leads/month"},
            {"title": "Sell >=2 annual memberships per month", "target": 2, "unit": "annual memberships/month"},
            {"title": "Capture >=10 referral contact details at point of sale per month", "target": 10, "unit": "referrals/month"},
            {
                "title": "Secure and execute >=1 external marketing partnership by end of Q2",
                "target": 1,
                "unit": "partnership",
            },
        ),
    },
    {
        "number": 2,
        "area": "Onboarding",
        "champions": "Tremaine",
        "title": "Ensure all new members engage with the 6-week onboarding programme to drive early habit formation and retention.",
        "description": "Q2 2026 OKR: April to June.",
        "key_results": (
            {"title": "Achieve >=85% of new members booking their first session within 7 days", "target": 85, "unit": "%"},
            {"title": "Ensure >=50% of new members book at least 3 onboarding sessions", "target": 50, "unit": "%"},
            {"title": "Contact 100% of non-booked members within 72 hours of joining", "target": 100, "unit": "%"},
            {"title": "Run bi-weekly onboarding reviews with documented actions", "target": 6, "unit": "reviews"},
            {"title": "Collect >=3 onboarding success stories/testimonials per month", "target": 3, "unit": "testimonials/month"},
        ),
    },
    {
        "number": 3,
        "area": "Experience",
        "champions": "Soph",
        "title": "Deliver a consistently premium club experience that maximises member satisfaction and retention.",
        "description": "Q2 2026 OKR: April to June.",
        "key_results": (
            {"title": "Maintain rolling NPS >=70, with 100% of reviews responded to within 24 hours", "target": 70, "unit": "NPS"},
            {"title": "Keep month 2 inactivity <10%", "target": 10, "unit": "%", "direction": "decrease"},
            {"title": "Keep month 3 inactivity <15%", "target": 15, "unit": "%", "direction": "decrease"},
            {"title": "Launch and implement a member needs and exit survey, with monthly insight review", "target": 3, "unit": "reviews"},
            {"title": "Complete daily club walk and maintenance log", "target": 100, "unit": "%"},
            {"title": "Review and action suggestions box weekly", "target": 13, "unit": "reviews"},
            {"title": "Achieve 100% completion of FranConnect tasks weekly", "target": 100, "unit": "%"},
            {"title": "Complete deep clean of flooring and bathrooms weekly, logged and signed off", "target": 13, "unit": "cleans"},
        ),
    },
    {
        "number": 4,
        "area": "Team Onboarding",
        "champions": "Soph",
        "title": "Ensure new team members are fully aligned with club standards, driving strong sales performance and member experience.",
        "description": "Q2 2026 OKR: April to June.",
        "key_results": (
            {"title": "Complete full role handover from Rhys to Soph by 22 April", "target": 1, "unit": "handover"},
            {"title": "Tremaine completes 100% of club training plan, sales and coaching, by end of Q2", "target": 100, "unit": "%"},
            {"title": "Tremaine completes AF onboarding programme with Alex Barton within 4 weeks", "target": 1, "unit": "programme"},
            {"title": "Generate >=3 new PT clients via 5-for-GBP 100 offer", "target": 3, "unit": "PT clients"},
            {"title": "Conduct monthly performance review with clear KPIs and development actions", "target": 3, "unit": "reviews"},
        ),
    },
)


def _parse_date(raw: str | None) -> date | None:
    value = str(raw or "").strip()
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except Exception:
            continue
    try:
        return datetime.fromisoformat(value).date()
    except Exception:
        return None


def _row_value(row: dict[str, Any], *keys: str) -> str | None:
    if not row:
        return None
    lookup: dict[str, Any] = {}
    for key, value in row.items():
        raw_key = str(key or "").strip()
        if not raw_key:
            continue
        lookup[raw_key.lower()] = value
        lookup[" ".join(raw_key.lower().replace("_", " ").split())] = value
    for key in keys:
        raw = str(key or "").strip().lower()
        value = lookup.get(raw)
        if value is None:
            value = lookup.get(" ".join(raw.replace("_", " ").split()))
        text = str(value or "").strip()
        if text:
            return text
    return None


def member_name(member: Member | None) -> str:
    if member is None:
        return "Member"
    name = " ".join(part for part in [member.first_name, member.last_name] if part)
    return name.strip() or member.phone_e164 or f"Member {member.id}"


def find_member_by_phone(session: Session, phone: str | None) -> Member | None:
    normalized = normalize_phone(phone)
    if not normalized:
        return None
    direct = session.execute(select(Member).where(Member.phone_e164 == normalized)).scalar_one_or_none()
    if direct is not None:
        return direct
    return (
        session.execute(
            select(Member)
            .where(Member.mobile_raw == normalized)
            .order_by(Member.external_member_id.is_(None), Member.id.asc())
        )
        .scalars()
        .first()
    )


def member_contact_phone(member: Member | None) -> str | None:
    if member is None:
        return None
    direct = normalize_phone(getattr(member, "phone_e164", None))
    if direct:
        return direct
    return normalize_phone(getattr(member, "mobile_raw", None))


def normalize_membership_status(status: str | None, *, default: str = "current") -> str:
    value = " ".join(str(status or "").strip().lower().split())
    if not value:
        value = default
    if value in {"not setup", "not set up", "active"}:
        return "current"
    return value or "current"


def _placeholder_phone(external_member_id: str | None, fallback: str | None = None) -> str:
    external = str(external_member_id or "").strip()
    if external:
        return f"member:{external}"[:32]
    raw = "".join(ch for ch in str(fallback or "") if ch.isalnum()) or str(abs(hash(fallback)) % 100000000)
    return f"member:{raw}"[:32]


def _phone_owner(session: Session, phone_e164: str | None) -> Member | None:
    normalized = normalize_phone(phone_e164)
    if not normalized:
        return None
    return session.execute(select(Member).where(Member.phone_e164 == normalized)).scalar_one_or_none()


def upsert_member(
    session: Session,
    *,
    phone: str | None = None,
    external_member_id: str | None = None,
    first_name: str | None = None,
    last_name: str | None = None,
    email: str | None = None,
    mobile_raw: str | None = None,
    membership_status: str | None = None,
    join_date: str | date | None = None,
    last_visit_date: str | date | None = None,
    expiry_date: str | date | None = None,
    cancellation_date: str | date | None = None,
    source: str | None = None,
    notes: str | None = None,
) -> tuple[Member, bool]:
    normalized = normalize_phone(phone)
    mobile_normalized = normalize_phone(mobile_raw or phone)
    external = str(external_member_id or "").strip() or None
    if not normalized and not external:
        raise ValueError("Member phone or member number is required")
    row = None
    if external:
        row = session.execute(select(Member).where(Member.external_member_id == external)).scalar_one_or_none()
    if row is None and normalized:
        owner = _phone_owner(session, normalized)
        if owner is not None and (not external or not getattr(owner, "external_member_id", None)):
            row = owner
    created = False
    if row is None:
        storage_phone = normalized
        owner = _phone_owner(session, storage_phone) if storage_phone else None
        if owner is not None or not storage_phone:
            storage_phone = _placeholder_phone(external, phone or email)
        row = Member(phone_e164=storage_phone)
        session.add(row)
        created = True
    if external is not None:
        row.external_member_id = external
    if normalized:
        owner = _phone_owner(session, normalized)
        if owner is None or int(owner.id or 0) == int(row.id or 0):
            row.phone_e164 = normalized
        elif not normalize_phone(row.phone_e164):
            row.phone_e164 = _placeholder_phone(external, normalized)
    elif not normalize_phone(row.phone_e164):
        row.phone_e164 = _placeholder_phone(external, email)
    if mobile_raw is not None or phone is not None:
        row.mobile_raw = mobile_normalized
    if first_name is not None:
        row.first_name = str(first_name or "").strip() or None
    if last_name is not None:
        row.last_name = str(last_name or "").strip() or None
    if email is not None:
        row.email = str(email or "").strip() or None
    if membership_status is not None:
        row.membership_status = normalize_membership_status(membership_status)
    if join_date is not None:
        row.join_date = join_date if isinstance(join_date, date) else _parse_date(str(join_date))
    if last_visit_date is not None:
        row.last_visit_date = last_visit_date if isinstance(last_visit_date, date) else _parse_date(str(last_visit_date))
    if expiry_date is not None:
        row.expiry_date = expiry_date if isinstance(expiry_date, date) else _parse_date(str(expiry_date))
    if cancellation_date is not None:
        row.cancellation_date = cancellation_date if isinstance(cancellation_date, date) else _parse_date(str(cancellation_date))
    if source is not None:
        row.source = str(source or "").strip() or None
    if notes is not None:
        row.notes = str(notes or "").strip() or None
    session.add(row)
    session.flush()
    return row, created


def log_message(
    session: Session,
    *,
    member: Member | None,
    conversation: Conversation | None,
    direction: str,
    body: str | None,
    channel: str = "sms",
    provider_sid: str | None = None,
    status: str | None = None,
    raw_payload: dict[str, Any] | None = None,
) -> MessageLog:
    row = MessageLog(
        member_id=int(member.id) if member is not None and member.id else None,
        conversation_id=int(conversation.id) if conversation is not None and conversation.id else None,
        direction=str(direction or "").strip().lower(),
        channel=str(channel or "sms").strip().lower(),
        phone_e164=member_contact_phone(member),
        body=str(body or "").strip() or None,
        provider_sid=str(provider_sid or "").strip() or None,
        status=str(status or "").strip() or None,
        raw_payload=raw_payload or None,
    )
    session.add(row)
    session.flush()
    return row


def send_to_member(
    session: Session,
    member: Member,
    text: str,
    conversation: Conversation | None = None,
    quick_replies: list[str] | None = None,
) -> dict[str, Any]:
    contact_phone = member_contact_phone(member)
    if not contact_phone:
        raise ValueError("Member does not have a mobile number for SMS")
    try:
        result = send_sms(contact_phone, text)
    except Exception as exc:
        log_message(
            session,
            member=member,
            conversation=conversation,
            direction="outbound",
            channel="sms",
            body=text,
            status="failed",
            raw_payload={"error": str(exc), "type": exc.__class__.__name__},
        )
        session.commit()
        raise
    log_message(
        session,
        member=member,
        conversation=conversation,
        direction="outbound",
        channel="sms",
        body=str(result.get("body") or text),
        provider_sid=str(result.get("sid") or "").strip() or None,
        status=str(result.get("status") or "").strip() or None,
    )
    session.commit()
    return result


def update_message_status(
    session: Session, *, provider_sid: str | None, status: str | None, raw_payload: dict[str, Any] | None = None
) -> bool:
    sid = str(provider_sid or "").strip()
    if not sid:
        return False
    row = session.execute(select(MessageLog).where(MessageLog.provider_sid == sid)).scalar_one_or_none()
    if row is None:
        return False
    row.status = str(status or "").strip() or row.status
    if raw_payload:
        row.raw_payload = raw_payload
    session.add(row)
    session.commit()
    return True


def active_conversation_for_member(session: Session, member_id: int) -> Conversation | None:
    return (
        session.execute(
            select(Conversation)
            .where(Conversation.member_id == int(member_id), Conversation.status == "active")
            .order_by(desc(Conversation.id))
        )
        .scalars()
        .first()
    )


def latest_survey_for_member(session: Session, member_id: int, flow_key: str) -> Conversation | None:
    flow = str(flow_key or "").strip()
    if not flow:
        return None
    return (
        session.execute(
            select(Conversation)
            .where(Conversation.member_id == int(member_id), Conversation.flow_key == flow)
            .order_by(desc(Conversation.id))
        )
        .scalars()
        .first()
    )


def _new_app_link_token(session: Session) -> str:
    for _ in range(10):
        token = secrets.token_urlsafe(24)
        exists = session.execute(select(Conversation.id).where(Conversation.app_link_token == token)).first()
        if not exists:
            return token
    raise RuntimeError("Could not create a unique survey link token")


def ensure_app_link_token(session: Session, conversation: Conversation, *, commit: bool = True) -> str:
    token = str(getattr(conversation, "app_link_token", None) or "").strip()
    if token:
        return token
    conversation.app_link_token = _new_app_link_token(session)
    session.add(conversation)
    if commit:
        session.commit()
    else:
        session.flush()
    return str(conversation.app_link_token)


def survey_config_row(session: Session, flow_key: str) -> SurveyConfig | None:
    key = str(flow_key or "").strip().lower()
    if not key:
        return None
    return session.execute(select(SurveyConfig).where(SurveyConfig.flow_key == key)).scalar_one_or_none()


def _survey_config_payload(row: SurveyConfig | None) -> dict[str, Any]:
    if row is None:
        return {}
    return {
        "label": row.label,
        "intro": row.intro,
        "completion": row.completion,
        "questions": row.questions,
        "avatar_script": row.avatar_script,
        "avatar_video_url": row.avatar_video_url,
        "avatar_poster_url": row.avatar_poster_url,
        "avatar_character": row.avatar_character,
        "avatar_style": row.avatar_style,
        "avatar_voice": row.avatar_voice,
        "avatar_status": row.avatar_status,
        "avatar_job_id": row.avatar_job_id,
        "avatar_error": row.avatar_error,
        "avatar_summary_url": row.avatar_summary_url,
    }


def effective_survey_flow(session: Session, flow_key: str) -> SurveyFlow:
    key = str(flow_key or "").strip().lower()
    row = survey_config_row(session, key)
    return flow_from_config(key, _survey_config_payload(row))


def editable_survey_payload(session: Session, flow_key: str) -> dict[str, Any]:
    flow = effective_survey_flow(session, flow_key)
    payload = flow_config_payload(flow)
    row = survey_config_row(session, flow.key)
    if row is not None:
        payload.update(
            {
                "avatar_source": row.avatar_source,
                "avatar_payload": row.avatar_payload,
                "avatar_generated_at": row.avatar_generated_at.isoformat() if row.avatar_generated_at else "",
            }
        )
    return payload


def save_survey_config(
    session: Session,
    flow_key: str,
    *,
    label: str | None = None,
    intro: str | None = None,
    completion: str | None = None,
    questions: list[dict[str, Any]] | None = None,
    avatar_script: str | None = None,
    avatar_video_url: str | None = None,
    avatar_poster_url: str | None = None,
    avatar_character: str | None = None,
    avatar_style: str | None = None,
    avatar_voice: str | None = None,
) -> SurveyConfig:
    base = flow_for_key(flow_key)
    row = survey_config_row(session, base.key)
    if row is None:
        row = SurveyConfig(flow_key=base.key)
        session.add(row)
        session.flush()
    row.label = str(label or "").strip() or base.label
    row.intro = str(intro or "").strip() or base.intro
    row.completion = str(completion or "").strip() or base.completion
    if is_outcome_locked_flow(base.key):
        stored_questions = [
            {
                "key": base_question.key,
                "text": base_question.text,
                "helper": base_question.helper,
                "options": list(base_question.options),
            }
            for base_question in base.questions
        ]
    else:
        by_key = {
            str(item.get("key") or "").strip(): item
            for item in (questions or [])
            if isinstance(item, dict) and str(item.get("key") or "").strip()
        }
        stored_questions = []
        for base_question in base.questions:
            item = by_key.get(base_question.key, {})
            raw_options = item.get("options")
            if isinstance(raw_options, str):
                option_values = [part.strip() for part in raw_options.replace("|", "\n").splitlines()]
            elif isinstance(raw_options, (list, tuple)):
                option_values = [str(part or "").strip() for part in raw_options]
            else:
                option_values = []
            options = [option for option in option_values if option][:3] or list(base_question.options)
            stored_questions.append(
                {
                    "key": base_question.key,
                    "text": str(item.get("text") or "").strip() or base_question.text,
                    "helper": str(item.get("helper") or "").strip() or base_question.helper,
                    "options": options,
                }
            )
    row.questions = stored_questions
    row.avatar_script = str(avatar_script or "").strip() or None
    row.avatar_video_url = str(avatar_video_url or "").strip() or None
    row.avatar_poster_url = str(avatar_poster_url or "").strip() or None
    row.avatar_character = str(avatar_character or "").strip() or None
    row.avatar_style = str(avatar_style or "").strip() or None
    row.avatar_voice = str(avatar_voice or "").strip() or None
    row.updated_at = datetime.utcnow()
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def membersense_media_root() -> Path:
    root = Path(os.getenv("MEMBERSENSE_MEDIA_DIR") or Path.cwd() / "public" / "membersense-media")
    root.mkdir(parents=True, exist_ok=True)
    return root


def _safe_asset_token(value: str | None) -> str:
    token = re.sub(r"[^A-Za-z0-9_-]+", "-", str(value or "").strip()).strip("-_")
    return token[:48] or secrets.token_hex(6)


def _write_survey_avatar_video(flow_key: str, job_id: str | None, video_bytes: bytes) -> str:
    safe_flow = _safe_asset_token(flow_key)
    safe_job = _safe_asset_token(job_id)
    rel_path = Path("survey-avatars") / f"{safe_flow}-{safe_job}.mp4"
    out_path = membersense_media_root() / rel_path
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(bytes(video_bytes or b""))
    return "/membersense-media/" + str(rel_path).replace(os.sep, "/")


def survey_avatar_defaults() -> dict[str, Any]:
    try:
        from app.avatar import azure_avatar_defaults, azure_avatar_enabled, normalize_batch_avatar_choice

        defaults = azure_avatar_defaults()
        character, style = normalize_batch_avatar_choice(
            str(defaults.get("character") or "lisa"),
            str(defaults.get("style") or "graceful-sitting"),
        )
        return {
            "enabled": bool(azure_avatar_enabled()),
            "character": character,
            "style": style,
            "voice": str(defaults.get("voice") or "en-GB-SoniaNeural"),
        }
    except Exception as exc:
        return {
            "enabled": False,
            "character": "lisa",
            "style": "graceful-sitting",
            "voice": "en-GB-SoniaNeural",
            "error": str(exc),
        }


def survey_avatar_runtime_config() -> dict[str, Any]:
    avatar_key = str(os.getenv("AZURE_AVATAR_KEY") or "").strip()
    speech_key = str(os.getenv("AZURE_SPEECH_KEY") or "").strip()
    tts_key = str(os.getenv("AZURE_TTS_KEY") or "").strip()
    resolved_key = avatar_key or speech_key or tts_key
    avatar_region = str(os.getenv("AZURE_AVATAR_REGION") or "").strip()
    speech_region = str(os.getenv("AZURE_SPEECH_REGION") or "").strip()
    tts_region = str(os.getenv("AZURE_TTS_REGION") or "").strip()
    endpoint = str(
        os.getenv("AZURE_AVATAR_ENDPOINT")
        or os.getenv("AZURE_SPEECH_ENDPOINT")
        or os.getenv("AZURE_TTS_ENDPOINT")
        or ""
    ).strip()
    resolved_region = avatar_region or speech_region or tts_region
    if not endpoint and resolved_region:
        endpoint = f"https://{resolved_region}.api.cognitive.microsoft.com"
    endpoint_host = ""
    if endpoint:
        parsed = urlparse(endpoint)
        endpoint_host = parsed.netloc or endpoint
    enabled = str(os.getenv("USE_AZURE_AVATAR") or os.getenv("USE_AZURE_SPEECH") or "").strip().lower()
    return {
        "enabled": enabled in {"1", "true", "yes", "on"},
        "key_configured": bool(resolved_key),
        "key_fingerprint": hashlib.sha256(resolved_key.encode()).hexdigest()[:10] if resolved_key else "",
        "key_source": (
            "AZURE_AVATAR_KEY"
            if avatar_key
            else "AZURE_SPEECH_KEY"
            if speech_key
            else "AZURE_TTS_KEY"
            if tts_key
            else ""
        ),
        "region": resolved_region,
        "region_source": (
            "AZURE_AVATAR_REGION"
            if avatar_region
            else "AZURE_SPEECH_REGION"
            if speech_region
            else "AZURE_TTS_REGION"
            if tts_region
            else ""
        ),
        "endpoint": endpoint_host,
        "endpoint_source": (
            "AZURE_AVATAR_ENDPOINT"
            if os.getenv("AZURE_AVATAR_ENDPOINT")
            else "AZURE_SPEECH_ENDPOINT"
            if os.getenv("AZURE_SPEECH_ENDPOINT")
            else "AZURE_TTS_ENDPOINT"
            if os.getenv("AZURE_TTS_ENDPOINT")
            else "derived_from_region"
        ),
    }


def _survey_avatar_error_from_payload(payload: dict[str, Any], fallback: str = "Azure avatar generation failed.") -> str:
    props = payload.get("properties") if isinstance(payload.get("properties"), dict) else {}
    raw_error = (props or {}).get("error") or payload.get("error") or fallback
    if isinstance(raw_error, dict):
        raw_error = raw_error.get("message") or raw_error.get("code") or raw_error
    return str(raw_error or fallback).strip()[:1000]


def _avatar_error_is_retryable(error: str | None) -> bool:
    value = str(error or "").strip().lower()
    if not value:
        return False
    return "rate-limited with 429" in value or "retry after" in value or "is not supported for avatar character" in value


def _avatar_retry_after_seconds(error: str | None) -> int:
    value = str(error or "")
    match = re.search(r"retry after\s+(\d+)\s+seconds?", value, re.IGNORECASE)
    if not match:
        return 15
    try:
        return max(1, min(int(match.group(1)), 120))
    except Exception:
        return 15


def _save_survey_avatar_payload(session: Session, row: SurveyConfig, payload: dict[str, Any]) -> SurveyConfig:
    status = str(payload.get("status") or "").strip() or "Running"
    status_key = status.lower()
    outputs = payload.get("outputs") if isinstance(payload.get("outputs"), dict) else {}
    result_url = str((outputs or {}).get("result") or "").strip()
    row.avatar_status = status_key
    row.avatar_summary_url = str((outputs or {}).get("summary") or "").strip() or None
    row.avatar_payload = payload
    row.avatar_error = None
    if status_key == "succeeded":
        if not result_url:
            row.avatar_status = "failed"
            row.avatar_error = "Azure avatar completed without a result video URL."
        else:
            try:
                from app.avatar import download_batch_avatar_output

                row.avatar_video_url = _write_survey_avatar_video(
                    row.flow_key,
                    row.avatar_job_id,
                    download_batch_avatar_output(result_url),
                )
                row.avatar_generated_at = datetime.utcnow()
            except Exception as exc:
                row.avatar_status = "failed"
                row.avatar_error = f"Avatar completed but the video could not be downloaded: {exc}"[:1000]
    elif status_key == "failed":
        row.avatar_error = _survey_avatar_error_from_payload(payload)
    elif payload.get("_timed_out"):
        row.avatar_error = "Avatar job is still running after the background wait timeout."
    row.updated_at = datetime.utcnow()
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def _mark_survey_avatar_failed(session: Session, flow_key: str, error: str) -> SurveyConfig | None:
    row = survey_config_row(session, flow_key)
    if row is None:
        return None
    row.avatar_status = "failed"
    row.avatar_error = str(error or "Avatar generation failed.").strip()[:1000]
    row.updated_at = datetime.utcnow()
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def _survey_avatar_script_for_row(session: Session, row: SurveyConfig) -> str:
    flow = effective_survey_flow(session, row.flow_key)
    return str(row.avatar_script or flow.avatar_script or flow.intro or "").strip()


def queue_survey_avatar_generation(session: Session, flow_key: str) -> SurveyConfig:
    try:
        from app.avatar import azure_avatar_enabled
    except Exception as exc:
        raise RuntimeError(f"Azure avatar tools are not available: {exc}") from exc
    if not azure_avatar_enabled():
        raise RuntimeError("Azure avatar generation is not enabled. Set USE_AZURE_AVATAR=1 and the Azure avatar credentials.")
    row = survey_config_row(session, flow_key)
    if row is None:
        base = flow_for_key(flow_key)
        row = save_survey_config(session, base.key, label=base.label, intro=base.intro, completion=base.completion)
    if not _survey_avatar_script_for_row(session, row):
        raise RuntimeError("Avatar script is required.")
    row.avatar_status = "queued"
    row.avatar_job_id = None
    row.avatar_error = None
    row.avatar_source = "azure_batch"
    row.avatar_video_url = None
    row.avatar_summary_url = None
    row.avatar_payload = None
    row.avatar_generated_at = None
    row.updated_at = datetime.utcnow()
    session.add(row)
    session.commit()
    session.refresh(row)
    _start_survey_avatar_thread(row.flow_key, mode="generate")
    return row


def queue_survey_avatar_completion(flow_key: str) -> bool:
    return _start_survey_avatar_thread(flow_key, mode="complete")


def _start_survey_avatar_thread(flow_key: str, *, mode: str) -> bool:
    key = str(flow_key or "").strip().lower()
    if not key:
        return False
    with _SURVEY_AVATAR_THREAD_LOCK:
        existing = _SURVEY_AVATAR_THREADS.get(key)
        if existing is not None and existing.is_alive():
            return False
        thread = threading.Thread(target=_survey_avatar_thread_runner, args=(key, mode), daemon=True)
        _SURVEY_AVATAR_THREADS[key] = thread
        thread.start()
        return True


def _survey_avatar_thread_runner(flow_key: str, mode: str) -> None:
    try:
        if mode == "generate":
            attempts = max(1, int(os.getenv("MEMBERSENSE_AVATAR_CREATE_ATTEMPTS") or "3"))
            last_error: Exception | None = None
            for attempt in range(attempts):
                try:
                    from .db import SessionLocal

                    with SessionLocal() as session:
                        generate_survey_avatar_video(session, flow_key)
                    last_error = None
                    break
                except Exception as exc:
                    last_error = exc
                    if attempt >= attempts - 1 or not _avatar_error_is_retryable(str(exc)):
                        raise
                    time.sleep(_avatar_retry_after_seconds(str(exc)))
            if last_error is not None:
                raise last_error
        complete_survey_avatar_video(flow_key)
    except Exception as exc:
        try:
            from .db import SessionLocal

            with SessionLocal() as session:
                _mark_survey_avatar_failed(session, flow_key, str(exc))
        except Exception:
            pass
    finally:
        with _SURVEY_AVATAR_THREAD_LOCK:
            existing = _SURVEY_AVATAR_THREADS.get(flow_key)
            if existing is threading.current_thread():
                _SURVEY_AVATAR_THREADS.pop(flow_key, None)


def complete_survey_avatar_video(flow_key: str) -> SurveyConfig | None:
    try:
        from app.avatar import wait_for_batch_avatar
    except Exception as exc:
        raise RuntimeError(f"Azure avatar tools are not available: {exc}") from exc
    from .db import SessionLocal

    with SessionLocal() as session:
        row = survey_config_row(session, flow_key)
        if row is None:
            return None
        job_id = str(row.avatar_job_id or "").strip()
        if not job_id:
            return row
        try:
            timeout = int(os.getenv("MEMBERSENSE_AVATAR_BACKGROUND_TIMEOUT_SECONDS") or "600")
        except Exception:
            timeout = 600
        timeout = max(30, timeout)
        payload = wait_for_batch_avatar(job_id, timeout_seconds=timeout)
        return _save_survey_avatar_payload(session, row, payload)


def resume_pending_survey_avatar_jobs() -> int:
    try:
        from app.avatar import azure_avatar_enabled
    except Exception:
        return 0
    if not azure_avatar_enabled():
        return 0
    from .db import SessionLocal

    queued_generation: list[str] = []
    queued_completion: list[str] = []
    with SessionLocal() as session:
        rows = session.execute(select(SurveyConfig)).scalars().all()
        for row in rows:
            flow_key = str(row.flow_key or "").strip().lower()
            job_id = str(row.avatar_job_id or "").strip()
            status = str(row.avatar_status or "").strip().lower()
            video_url = str(row.avatar_video_url or "").strip()
            if not flow_key or video_url or status in {"failed", "succeeded"}:
                if flow_key and not video_url and status == "failed" and _avatar_error_is_retryable(row.avatar_error):
                    row.avatar_status = "queued"
                    row.avatar_error = None
                    row.avatar_job_id = None
                    row.avatar_summary_url = None
                    row.avatar_payload = None
                    row.avatar_generated_at = None
                    row.updated_at = datetime.utcnow()
                    session.add(row)
                    queued_generation.append(flow_key)
                continue
            if job_id:
                queued_completion.append(flow_key)
            elif status in {"queued", "running", "submitting"}:
                queued_generation.append(flow_key)
        session.commit()
    for flow_key in queued_generation:
        _start_survey_avatar_thread(flow_key, mode="generate")
    for flow_key in queued_completion:
        queue_survey_avatar_completion(flow_key)
    return len(queued_generation) + len(queued_completion)


def generate_survey_avatar_video(session: Session, flow_key: str) -> SurveyConfig:
    try:
        from app.avatar import azure_avatar_enabled, create_batch_avatar, normalize_batch_avatar_choice
    except Exception as exc:
        raise RuntimeError(f"Azure avatar tools are not available: {exc}") from exc
    if not azure_avatar_enabled():
        raise RuntimeError("Azure avatar generation is not enabled. Set USE_AZURE_AVATAR=1 and the Azure avatar credentials.")
    row = survey_config_row(session, flow_key)
    if row is None:
        base = flow_for_key(flow_key)
        row = save_survey_config(session, base.key, label=base.label, intro=base.intro, completion=base.completion)
    flow = effective_survey_flow(session, row.flow_key)
    defaults = survey_avatar_defaults()
    script = _survey_avatar_script_for_row(session, row)
    if not script:
        raise RuntimeError("Avatar script is required.")
    character = str(row.avatar_character or defaults.get("character") or "lisa").strip()
    style = str(row.avatar_style or defaults.get("style") or "graceful-sitting").strip()
    character, style = normalize_batch_avatar_choice(character, style)
    voice = str(row.avatar_voice or defaults.get("voice") or "en-GB-SoniaNeural").strip()
    row.avatar_status = "running"
    row.avatar_job_id = None
    row.avatar_error = None
    row.avatar_source = "azure_batch"
    row.avatar_video_url = None
    row.avatar_summary_url = None
    row.avatar_payload = None
    row.avatar_generated_at = None
    row.avatar_character = character
    row.avatar_style = style
    row.updated_at = datetime.utcnow()
    session.add(row)
    session.commit()
    try:
        result = create_batch_avatar(
            script=script,
            title=f"{flow.label} avatar",
            character=character,
            style=style,
            voice=voice,
        )
        status = str(result.get("status") or "").strip() or "Running"
        job_id = str(result.get("id") or "").strip()
        if not job_id:
            raise RuntimeError("Azure avatar generation did not return a job id")
        outputs = result.get("outputs") if isinstance(result.get("outputs"), dict) else {}
        row.avatar_status = status.lower()
        row.avatar_job_id = job_id
        row.avatar_summary_url = str((outputs or {}).get("summary") or "").strip() or None
        row.avatar_error = None
        row.avatar_payload = result
        if status.lower() == "failed":
            row.avatar_error = _survey_avatar_error_from_payload(result)
        session.add(row)
        session.commit()
        session.refresh(row)
        if status.lower() == "succeeded":
            return _save_survey_avatar_payload(session, row, result)
        return row
    except Exception as exc:
        row.avatar_status = "failed"
        row.avatar_error = str(exc)
        row.updated_at = datetime.utcnow()
        session.add(row)
        session.commit()
        session.refresh(row)
        raise


def refresh_survey_avatar_video(session: Session, flow_key: str) -> SurveyConfig:
    try:
        from app.avatar import get_batch_avatar
    except Exception as exc:
        raise RuntimeError(f"Azure avatar tools are not available: {exc}") from exc
    row = survey_config_row(session, flow_key)
    if row is None:
        raise RuntimeError("No avatar job is pending for this survey.")
    if not str(row.avatar_job_id or "").strip():
        status = str(row.avatar_status or "").strip().lower()
        if status in {"queued", "running", "submitting"}:
            _start_survey_avatar_thread(row.flow_key, mode="generate")
            return row
        raise RuntimeError("No avatar job is pending for this survey.")
    payload = get_batch_avatar(str(row.avatar_job_id))
    return _save_survey_avatar_payload(session, row, payload)


def member_first_name(member: Member | None) -> str:
    return str(getattr(member, "first_name", "") or "").strip().split(" ")[0] if member is not None else ""


def survey_intro_for_member(member: Member | None, intro: str) -> str:
    first_name = member_first_name(member)
    text = str(intro or "").strip()
    if not first_name or not text:
        return text
    lowered = text.lower()
    if lowered.startswith("welcome to "):
        return f"Hi {first_name}, {text[0].lower()}{text[1:]}"
    if lowered.startswith("hi, "):
        return f"Hi {first_name}, {text[4:]}"
    if lowered.startswith("it is "):
        return f"Hi {first_name}, {text[0].lower()}{text[1:]}"
    return f"Hi {first_name}, {text[0].lower()}{text[1:]}"


def survey_link_invite_text(member: Member | None, flow_key: str, survey_url: str) -> str:
    flow = flow_for_key(flow_key)
    first_name = member_first_name(member)
    greeting = f"Hi {first_name}," if first_name else "Hi,"
    return (
        f"{greeting} please complete this quick {flow.label.lower()} for {config.GYM_NAME}: "
        f"{str(survey_url or '').strip()}"
    )


def send_survey_link_to_member(
    session: Session,
    member: Member,
    conversation: Conversation,
    survey_url: str,
) -> dict[str, Any]:
    link = str(survey_url or "").strip()
    if not link:
        raise ValueError("Survey link is missing")
    ensure_app_link_token(session, conversation, commit=False)
    flow = effective_survey_flow(session, conversation.flow_key)
    first_name = member_first_name(member)
    greeting = f"Hi {first_name}," if first_name else "Hi,"
    text = f"{greeting} please complete this quick {flow.label.lower()} for {config.GYM_NAME}: {link}"
    return send_to_member(session, member, text, conversation)


def _question_text(
    session: Session,
    flow_key: str,
    step_index: int,
    *,
    include_intro: bool = False,
    member: Member | None = None,
) -> tuple[str, list[str]]:
    flow = effective_survey_flow(session, flow_key)
    question = flow.questions[step_index]
    total = len(flow.questions)
    prefix = f"Question {step_index + 1} of {total}: "
    text = f"{prefix}{question.text}".strip()
    if include_intro:
        text = f"{survey_intro_for_member(member, flow.intro)}\n\n{text}".strip()
    return text, question_options(question)


def inactive_member_candidates(session: Session, *, min_days: int = 14, limit: int = 200) -> list[Member]:
    days = max(int(min_days or 14), 1)
    today = date.today()
    cutoff = today - timedelta(days=days)
    return list(
        session.execute(
            select(Member)
            .where(
                *_current_member_filters(today),
                or_(Member.last_visit_date.is_(None), Member.last_visit_date <= cutoff),
            )
            .order_by(Member.last_visit_date.is_(None), Member.last_visit_date.asc(), Member.id.desc())
            .limit(max(int(limit or 200), 1))
        )
        .scalars()
        .all()
    )


def _range_days(min_days: int | None, max_days: int | None) -> tuple[int, int]:
    low = max(int(min_days or 0), 0)
    high = max(int(max_days if max_days is not None else low), low)
    return low, high


def _current_member_filters(today: date) -> list[Any]:
    excluded_status_terms = ("cancel", "expired", "term", "terminated", "leav", "left")
    filters: list[Any] = [or_(Member.expiry_date.is_(None), Member.expiry_date >= today)]
    filters.extend(
        or_(Member.membership_status.is_(None), ~Member.membership_status.ilike(f"%{term}%"))
        for term in excluded_status_terms
    )
    return filters


def current_member_count(session: Session) -> int:
    return int(
        session.scalar(select(func.count()).select_from(Member).where(*_current_member_filters(date.today()))) or 0
    )


def current_member_rows(session: Session, *, today: date | None = None) -> list[Member]:
    base = today or date.today()
    return list(session.execute(select(Member).where(*_current_member_filters(base))).scalars().all())


def days_since(value: date | None, *, today: date | None = None) -> int | None:
    if value is None:
        return None
    base = today or date.today()
    return (base - value).days


def new_member_candidates(
    session: Session, *, min_days: int = 0, max_days: int = 7, limit: int = 200
) -> list[Member]:
    low, high = _range_days(min_days, max_days)
    today = date.today()
    earliest = today - timedelta(days=high)
    latest = today - timedelta(days=low)
    return list(
        session.execute(
            select(Member)
            .where(
                *_current_member_filters(today),
                Member.join_date.is_not(None),
                Member.join_date >= earliest,
                Member.join_date <= latest,
            )
            .order_by(Member.join_date.desc(), Member.id.desc())
            .limit(max(int(limit or 200), 1))
        )
        .scalars()
        .all()
    )


def last_visit_range_candidates(
    session: Session, *, min_days: int = 14, max_days: int = 21, limit: int = 200
) -> list[Member]:
    low, high = _range_days(min_days, max_days)
    today = date.today()
    earliest = today - timedelta(days=high)
    latest = today - timedelta(days=low)
    return list(
        session.execute(
            select(Member)
            .where(
                *_current_member_filters(today),
                Member.last_visit_date.is_not(None),
                Member.last_visit_date >= earliest,
                Member.last_visit_date <= latest,
            )
            .order_by(Member.last_visit_date.desc(), Member.id.desc())
            .limit(max(int(limit or 200), 1))
        )
        .scalars()
        .all()
    )


def expired_member_candidates(
    session: Session, *, min_days: int = 0, max_days: int = 30, limit: int = 200
) -> list[Member]:
    low, high = _range_days(min_days, max_days)
    today = date.today()
    rows = (
        session.execute(
            select(Member)
            .where(Member.expiry_date.is_not(None))
            .order_by(Member.expiry_date.desc(), Member.id.desc())
            .limit(max(int(limit or 200), 1) * 3)
        )
        .scalars()
        .all()
    )
    return [
        member
        for member in rows
        if (age := days_since(member.expiry_date, today=today)) is not None and low <= age <= high
    ][: max(int(limit or 200), 1)]


def start_conversation(
    session: Session,
    member: Member,
    flow_key: str,
    *,
    send_intro: bool = False,
    commit: bool = True,
) -> Conversation:
    flow = effective_survey_flow(session, flow_key)
    for row in session.execute(
        select(Conversation).where(Conversation.member_id == int(member.id), Conversation.status == "active")
    ).scalars():
        row.status = "superseded"
        session.add(row)
    conversation = Conversation(
        member_id=int(member.id),
        flow_key=flow.key,
        app_link_token=_new_app_link_token(session),
        status="active",
        step_index=0,
        answers={},
    )
    session.add(conversation)
    session.flush()
    if send_intro:
        message, options = _question_text(session, flow.key, 0, include_intro=True, member=member)
        send_to_member(session, member, message, conversation, quick_replies=options)
    elif commit:
        session.commit()
    return conversation


def _create_staff_task(session: Session, member: Member, conversation: Conversation, classification: dict[str, Any]) -> None:
    if not bool((classification or {}).get("task_required")):
        return
    flow = effective_survey_flow(session, conversation.flow_key)
    title = f"{flow.label}: follow up with {member_name(member)}"
    detail = str((classification or {}).get("recommended_action") or conversation.summary or "").strip()
    priority = str((classification or {}).get("priority") or "normal").strip().lower() or "normal"
    session.add(
        StaffTask(
            member_id=int(member.id),
            conversation_id=int(conversation.id),
            task_type=conversation.flow_key,
            title=title,
            detail=detail,
            priority=priority,
            status="open",
        )
    )


def find_conversation_by_app_token(session: Session, token: str | None) -> Conversation | None:
    value = str(token or "").strip()
    if not value:
        return None
    return session.execute(select(Conversation).where(Conversation.app_link_token == value)).scalar_one_or_none()


def continue_app_conversation(session: Session, member: Member, conversation: Conversation, inbound_text: str) -> Conversation:
    if conversation.status != "active":
        return conversation
    flow = effective_survey_flow(session, conversation.flow_key)
    answers = dict(conversation.answers or {})
    step_index = int(conversation.step_index or 0)
    if step_index >= len(flow.questions):
        conversation.status = "completed"
        conversation.completed_at = conversation.completed_at or datetime.utcnow()
        session.add(conversation)
        session.commit()
        return conversation
    question = flow.questions[step_index]
    answer = normalize_option_answer(question, inbound_text)
    if answer is None:
        raise ValueError("Choose one of the available options.")
    answers[question.key] = answer
    step_index += 1
    conversation.answers = answers
    conversation.step_index = step_index
    conversation.updated_at = datetime.utcnow()
    if step_index >= len(flow.questions):
        classification = classify_response(conversation.flow_key, answers)
        conversation.classification = classification
        conversation.summary = response_summary_for_flow(flow, answers, classification)
        conversation.status = "completed"
        conversation.completed_at = datetime.utcnow()
        session.add(conversation)
        _create_staff_task(session, member, conversation, classification)
    else:
        session.add(conversation)
    session.commit()
    return conversation


def continue_conversation(session: Session, member: Member, conversation: Conversation, inbound_text: str) -> Conversation:
    flow = effective_survey_flow(session, conversation.flow_key)
    answers = dict(conversation.answers or {})
    step_index = int(conversation.step_index or 0)
    if step_index < len(flow.questions):
        question = flow.questions[step_index]
        answer = normalize_option_answer(question, inbound_text)
        if answer is None:
            message, options = _question_text(session, conversation.flow_key, step_index)
            send_to_member(
                session,
                member,
                f"Please tap one of the buttons so I can record this correctly.\n\n{message}",
                conversation,
                quick_replies=options,
            )
            return conversation
        answers[question.key] = answer
        step_index += 1
    conversation.answers = answers
    conversation.step_index = step_index
    conversation.updated_at = datetime.utcnow()
    if step_index >= len(flow.questions):
        classification = classify_response(conversation.flow_key, answers)
        conversation.classification = classification
        conversation.summary = response_summary_for_flow(flow, answers, classification)
        conversation.status = "completed"
        conversation.completed_at = datetime.utcnow()
        session.add(conversation)
        _create_staff_task(session, member, conversation, classification)
        session.flush()
        send_to_member(session, member, flow.completion, conversation)
        return conversation
    session.add(conversation)
    session.flush()
    message, options = _question_text(session, conversation.flow_key, step_index)
    send_to_member(session, member, message, conversation, quick_replies=options)
    return conversation


def handle_inbound_sms(session: Session, *, from_phone: str, body: str, raw_payload: dict[str, Any] | None = None) -> dict[str, Any]:
    normalized = normalize_phone(from_phone)
    if not normalized:
        raise ValueError("Inbound SMS message is missing a valid From number")
    member = find_member_by_phone(session, normalized)
    if member is None:
        member, _ = upsert_member(session, phone=normalized, membership_status="unknown", source="sms")
    conversation = active_conversation_for_member(session, int(member.id))
    log_message(
        session,
        member=member,
        conversation=conversation,
        direction="inbound",
        channel="sms",
        body=body,
        provider_sid=str((raw_payload or {}).get("MessageSid") or "").strip() or None,
        status=str((raw_payload or {}).get("SmsStatus") or "").strip() or None,
        raw_payload=raw_payload,
    )
    text = str(body or "").strip()
    lower = text.lower()
    if lower in {"stop", "unsubscribe"}:
        member.notes = ((member.notes or "") + "\nSMS opt-out requested.").strip()
        session.add(member)
        session.commit()
        return {"ok": True, "action": "opt_out"}
    session.commit()
    return {"ok": True, "action": "logged", "conversation_id": int(conversation.id) if conversation else None}


def import_members_csv(
    session: Session,
    *,
    raw_csv: bytes,
    filename: str | None = None,
    source: str = "csv",
    default_status: str = "current",
    force_status: str | None = None,
    max_expired_days: int | None = None,
) -> ImportBatch:
    text = raw_csv.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    batch = ImportBatch(filename=filename, source=source, errors=[])
    session.add(batch)
    session.flush()
    errors: list[dict[str, Any]] = []
    created_count = 0
    updated_count = 0
    skipped_count = 0
    rows_seen = 0
    today = date.today()
    max_age = int(max_expired_days) if max_expired_days is not None else None
    for idx, row in enumerate(reader, start=2):
        rows_seen += 1
        try:
            phone = _row_value(row, "phone", "mobile", "mobile number", "phone_e164", "Phone", "Evening Tel")
            member_number = _row_value(row, "member number", "member_number", "member no", "member id")
            cancellation_value = _row_value(row, "cancellation_date", "Cancellation Date")
            expiry_value = _row_value(row, "expiry_date", "Expiry Date", "Expiry date")
            if force_status and not expiry_value:
                expiry_value = cancellation_value
            if max_age is not None:
                expiry_dt = _parse_date(expiry_value)
                age_days = (today - expiry_dt).days if expiry_dt else None
                if age_days is None or age_days < 0 or age_days >= max_age:
                    skipped_count += 1
                    continue
            _member, created = upsert_member(
                session,
                phone=phone,
                external_member_id=member_number,
                first_name=_row_value(row, "first_name", "First Name", "First name", "name"),
                last_name=_row_value(row, "last_name", "Last Name", "Surname"),
                email=_row_value(row, "email", "Email", "Email address", "Email mail"),
                mobile_raw=phone,
                membership_status=force_status
                or _row_value(row, "membership_status", "status", "Status")
                or default_status,
                join_date=_row_value(row, "join_date", "Join Date", "Joining Date"),
                last_visit_date=_row_value(row, "last_visit_date", "Last Visit", "Last visit"),
                expiry_date=expiry_value,
                cancellation_date=cancellation_value,
                source=source,
            )
            if created:
                created_count += 1
            else:
                updated_count += 1
        except Exception as exc:
            errors.append({"row": idx, "error": str(exc)})
    batch.rows_seen = rows_seen
    batch.rows_created = created_count
    batch.rows_updated = updated_count
    batch.rows_skipped = skipped_count
    batch.errors = errors
    session.add(batch)
    session.commit()
    return batch


def survey_options(session: Session | None = None) -> list[dict[str, str]]:
    if session is None:
        return [{"key": key, "label": flow.label} for key, flow in SURVEY_FLOWS.items()]
    return [{"key": key, "label": effective_survey_flow(session, key).label} for key in SURVEY_FLOWS]


def seed_default_okrs(session: Session) -> int:
    quarter = "2026-Q2"
    existing = int(
        session.scalar(
            select(func.count())
            .select_from(OkrObjective)
            .where(OkrObjective.quarter == quarter)
        )
        or 0
    )
    if existing > 0:
        return 0
    created = 0
    for item in Q2_2026_OKR_PRESET:
        objective = OkrObjective(
            quarter=quarter,
            objective_number=int(item.get("number") or created + 1),
            area=str(item.get("area") or "").strip(),
            title=str(item.get("title") or "").strip(),
            description=str(item.get("description") or "").strip() or None,
            champions=str(item.get("champions") or "").strip() or None,
            status="active",
        )
        session.add(objective)
        session.flush()
        champion_label = str(item.get("champions") or "").strip() or "Team"
        for kr in item.get("key_results") or ():
            if not isinstance(kr, dict):
                continue
            session.add(
                OkrKeyResult(
                    objective_id=int(objective.id),
                    title=str(kr.get("title") or "").strip(),
                    target_value=float(kr.get("target") or 0),
                    actual_value=0.0,
                    unit=str(kr.get("unit") or "").strip() or None,
                    direction=str(kr.get("direction") or "increase").strip().lower() or "increase",
                    allocation_type="team",
                    team_label=champion_label,
                )
            )
        created += 1
    session.commit()
    return created


def mark_task_done(session: Session, task_id: int) -> bool:
    row = session.get(StaffTask, int(task_id))
    if row is None:
        return False
    row.status = "completed"
    row.completed_at = datetime.utcnow()
    session.add(row)
    session.commit()
    return True
