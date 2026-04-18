from __future__ import annotations

import csv
import io
import secrets
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import desc, func, or_, select
from sqlalchemy.orm import Session

from . import config
from .messaging import normalize_phone, send_sms
from .models import Conversation, ImportBatch, Member, MessageLog, StaffTask
from .surveys import SURVEY_FLOWS, classify_response, flow_for_key, normalize_option_answer, question_options, response_summary


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
    result = send_sms(contact_phone, text)
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
    text = survey_link_invite_text(member, conversation.flow_key, link)
    return send_to_member(session, member, text, conversation)


def _question_text(
    flow_key: str,
    step_index: int,
    *,
    include_intro: bool = False,
    member: Member | None = None,
) -> tuple[str, list[str]]:
    flow = flow_for_key(flow_key)
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
    flow = flow_for_key(flow_key)
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
        message, options = _question_text(flow.key, 0, include_intro=True, member=member)
        send_to_member(session, member, message, conversation, quick_replies=options)
    elif commit:
        session.commit()
    return conversation


def _create_staff_task(session: Session, member: Member, conversation: Conversation, classification: dict[str, Any]) -> None:
    if not bool((classification or {}).get("task_required")):
        return
    flow = flow_for_key(conversation.flow_key)
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
    flow = flow_for_key(conversation.flow_key)
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
        conversation.summary = response_summary(conversation.flow_key, answers, classification)
        conversation.status = "completed"
        conversation.completed_at = datetime.utcnow()
        session.add(conversation)
        _create_staff_task(session, member, conversation, classification)
    else:
        session.add(conversation)
    session.commit()
    return conversation


def continue_conversation(session: Session, member: Member, conversation: Conversation, inbound_text: str) -> Conversation:
    flow = flow_for_key(conversation.flow_key)
    answers = dict(conversation.answers or {})
    step_index = int(conversation.step_index or 0)
    if step_index < len(flow.questions):
        question = flow.questions[step_index]
        answer = normalize_option_answer(question, inbound_text)
        if answer is None:
            message, options = _question_text(conversation.flow_key, step_index)
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
        conversation.summary = response_summary(conversation.flow_key, answers, classification)
        conversation.status = "completed"
        conversation.completed_at = datetime.utcnow()
        session.add(conversation)
        _create_staff_task(session, member, conversation, classification)
        session.flush()
        send_to_member(session, member, flow.completion, conversation)
        return conversation
    session.add(conversation)
    session.flush()
    message, options = _question_text(conversation.flow_key, step_index)
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


def survey_options() -> list[dict[str, str]]:
    return [{"key": key, "label": flow.label} for key, flow in SURVEY_FLOWS.items()]


def mark_task_done(session: Session, task_id: int) -> bool:
    row = session.get(StaffTask, int(task_id))
    if row is None:
        return False
    row.status = "completed"
    row.completed_at = datetime.utcnow()
    session.add(row)
    session.commit()
    return True
