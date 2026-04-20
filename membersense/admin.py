from __future__ import annotations

from datetime import date, timedelta
from html import escape
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import desc, func, or_, select
from sqlalchemy.orm import Session

from . import config
from .auth import (
    active_staff_count,
    authenticate_staff,
    clear_staff_cookie,
    create_staff_user,
    safe_next_path,
    set_staff_cookie,
    staff_count,
    staff_from_request,
)
from .db import SessionLocal
from .models import Conversation, Member, MessageLog, StaffTask, StaffUser
from .surveys import SURVEY_FLOWS, flow_for_key, is_outcome_locked_flow, question_options
from .services import (
    active_conversation_for_member,
    continue_app_conversation,
    current_member_rows,
    days_since,
    editable_survey_payload,
    effective_survey_flow,
    ensure_app_link_token,
    expired_member_candidates,
    find_conversation_by_app_token,
    import_members_csv,
    last_visit_range_candidates,
    latest_survey_for_member,
    mark_task_done,
    member_first_name,
    member_contact_phone,
    member_name,
    new_member_candidates,
    queue_survey_avatar_completion,
    queue_survey_avatar_generation,
    refresh_survey_avatar_video,
    save_survey_config,
    send_survey_link_to_member,
    start_conversation,
    survey_avatar_defaults,
    survey_avatar_runtime_config,
    survey_intro_for_member,
    survey_options,
    upsert_member,
)


router = APIRouter()


def get_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def require_admin(request: Request) -> None:
    if config.ADMIN_TOKEN:
        supplied = request.query_params.get("token") or request.headers.get("x-admin-token")
        if supplied == config.ADMIN_TOKEN:
            return
    with SessionLocal() as session:
        if staff_count(session) <= 0:
            raise HTTPException(status_code=303, headers={"Location": "/admin/setup"})
        if staff_from_request(request, session) is not None:
            return
    next_path = safe_next_path(str(request.url.path) + (f"?{request.url.query}" if request.url.query else ""))
    raise HTTPException(status_code=303, headers={"Location": f"/admin/login?{urlencode({'next': next_path})}"})


def _current_staff(request: Request) -> StaffUser | None:
    with SessionLocal() as session:
        return staff_from_request(request, session)


def _legacy_token_allowed(request: Request) -> bool:
    if not config.ADMIN_TOKEN:
        return False
    supplied = request.query_params.get("token") or request.headers.get("x-admin-token")
    return supplied == config.ADMIN_TOKEN


def _href(request: Request, path: str) -> str:
    token = request.query_params.get("token") or ""
    if config.ADMIN_TOKEN and token:
        separator = "&" if "?" in path else "?"
        return f"{path}{separator}{urlencode({'token': token})}"
    return path


def _post_action(request: Request, path: str) -> str:
    return _href(request, path)


def _esc(value: object) -> str:
    return escape(str(value if value is not None else ""))


def _date(value: date | None) -> str:
    return value.strftime("%d/%m/%y") if value else ""


def _member_mobile(member: Member | None) -> str:
    return member_contact_phone(member) or ""


def _mobile_label(member: Member | None) -> str:
    return _member_mobile(member) or "No mobile"


def _member_status_label(member: Member | None) -> str:
    value = " ".join(str(getattr(member, "membership_status", "") or "").strip().lower().split())
    if value in {"not setup", "not set up", "active", "current"}:
        return "Current"
    if value == "account onhold":
        return "Account On Hold"
    return value.replace("_", " ").title() if value else "Current"


def _redirect(request: Request, path: str) -> RedirectResponse:
    return RedirectResponse(_href(request, path), status_code=303)


def _sms_error_text(error: object) -> str:
    return str(error or "").strip() or error.__class__.__name__


def _sms_error_path(error: object) -> str:
    message = _sms_error_text(error)
    return "/admin/sms-diagnostics" + (f"?{urlencode({'error': message})}" if message else "")


def _token_input(request: Request) -> str:
    token = request.query_params.get("token")
    return f'<input type="hidden" name="token" value="{_esc(token)}">' if token else ""


def _layout(request: Request, title: str, body: str) -> HTMLResponse:
    current_staff = _current_staff(request)
    nav = "".join(
        f'<a href="{_href(request, path)}">{label}</a>'
        for path, label in [
            ("/admin", "Dashboard"),
            ("/admin/members", "Members"),
            ("/admin/inactive", "Member lists"),
            ("/admin/reports/visits", "Visit report"),
            ("/admin/sms-diagnostics", "SMS"),
            ("/admin/tasks", "Tasks"),
            ("/admin/surveys", "Surveys"),
            ("/admin/survey-config", "Survey setup"),
            ("/admin/import", "Import"),
            ("/admin/staff", "Staff"),
        ]
    )
    auth_link = '<a href="/admin/logout">Logout</a>' if current_staff is not None else ""
    staff_label = (
        f'<span class="muted">Signed in as {_esc(getattr(current_staff, "name", "") or getattr(current_staff, "email", ""))}</span>'
        if current_staff is not None
        else ""
    )
    account_nav = f'<div class="account-nav">{staff_label}{auth_link}</div>' if staff_label or auth_link else ""
    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{_esc(title)} - {config.APP_NAME}</title>
  <style>
    :root {{
      --ink: #171717;
      --muted: #5f6368;
      --line: #d8ded9;
      --paper: #f7f8f5;
      --surface: #ffffff;
      --accent: #6d28d9;
      --accent-2: #4c1d95;
      --danger: #a33b2b;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      color: var(--ink);
      background: var(--paper);
      line-height: 1.45;
    }}
    header {{
      background: var(--surface);
      border-bottom: 1px solid var(--line);
      padding: 18px 24px 14px;
    }}
    header h1 {{ margin: 0 0 10px; font-size: 24px; }}
    nav {{ display: flex; flex-wrap: wrap; gap: 8px 16px; }}
    nav a {{ color: var(--accent); font-weight: 700; text-decoration: none; }}
    .account-nav {{ display: flex; flex-wrap: wrap; gap: 8px 14px; margin-top: 10px; align-items: center; }}
    .account-nav a {{ color: var(--accent-2); font-weight: 800; text-decoration: none; }}
    main {{ max-width: 1180px; margin: 0 auto; padding: 24px; }}
    section {{
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 8px;
      margin-bottom: 18px;
      padding: 18px;
    }}
    h2 {{ margin: 0 0 14px; font-size: 20px; }}
    h3 {{ margin: 16px 0 8px; font-size: 16px; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 12px; }}
    .metric {{ border-left: 4px solid var(--accent); padding: 10px 12px; background: #f9fbfa; }}
    .metric strong {{ display: block; font-size: 24px; }}
    .muted {{ color: var(--muted); }}
    table {{ border-collapse: collapse; width: 100%; background: var(--surface); }}
    th, td {{ border-bottom: 1px solid var(--line); padding: 10px 8px; text-align: left; vertical-align: top; }}
    th {{ font-size: 12px; text-transform: uppercase; color: var(--muted); letter-spacing: 0; }}
    input, select, textarea {{
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 9px 10px;
      font: inherit;
      background: #fff;
    }}
    textarea {{ min-height: 82px; }}
    label {{ display: block; margin-bottom: 10px; font-weight: 700; }}
    label span {{ display: block; margin-bottom: 4px; color: var(--muted); font-size: 13px; font-weight: 600; }}
    button, .button {{
      display: inline-block;
      border: 0;
      border-radius: 6px;
      padding: 9px 12px;
      background: var(--accent);
      color: #fff;
      font: inherit;
      font-weight: 800;
      text-decoration: none;
      cursor: pointer;
      white-space: nowrap;
    }}
    .button.secondary, button.secondary {{ background: var(--accent-2); }}
    .button.danger, button.danger {{ background: var(--danger); }}
    .inline {{ display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }}
    .inline > * {{ width: auto; }}
    .stack {{ display: grid; gap: 10px; }}
    .tabs {{ display: flex; flex-wrap: wrap; gap: 8px; margin-top: 14px; }}
    .tab {{
      display: inline-block;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 9px 12px;
      color: var(--accent);
      background: #fff;
      font-weight: 800;
      text-decoration: none;
    }}
    .tab.active {{ background: var(--accent); border-color: var(--accent); color: #fff; }}
    .pill {{
      display: inline-block;
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 2px 8px;
      color: var(--muted);
      font-size: 13px;
      background: #fff;
    }}
    .priority-high {{ color: var(--danger); font-weight: 800; }}
    .error {{
      display: inline-block;
      border: 1px solid #f0b4aa;
      border-radius: 6px;
      background: #fff1ef;
      color: var(--danger);
      padding: 6px 10px;
      font-weight: 800;
    }}
    .bar-chart {{ display: grid; gap: 12px; margin-top: 14px; }}
    .bar-row {{
      display: grid;
      grid-template-columns: minmax(150px, 230px) 1fr minmax(80px, auto);
      gap: 12px;
      align-items: center;
    }}
    .bar-label {{ font-weight: 800; }}
    .bar-track {{
      min-height: 34px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #f3f5f2;
      overflow: hidden;
    }}
    .bar-fill {{
      height: 100%;
      min-width: 2px;
      background: var(--accent);
      color: #fff;
      display: flex;
      align-items: center;
      justify-content: flex-end;
      padding-right: 10px;
      font-weight: 800;
      white-space: nowrap;
    }}
    .bar-fill.warning {{ background: var(--danger); }}
    .bar-value {{ font-weight: 800; text-align: right; }}
    pre {{ white-space: pre-wrap; background: #f3f5f2; padding: 12px; border-radius: 6px; overflow-x: auto; }}
    @media (max-width: 720px) {{
      main {{ padding: 16px; }}
      .bar-row {{ grid-template-columns: 1fr; gap: 6px; }}
      .bar-value {{ text-align: left; }}
      table, thead, tbody, tr, th, td {{ display: block; }}
      th {{ display: none; }}
      td {{ border-bottom: 0; padding: 6px 0; }}
      tr {{ border-bottom: 1px solid var(--line); padding: 10px 0; }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>{config.APP_NAME}</h1>
    <nav>{nav}</nav>
    {account_nav}
  </header>
  <main>{body}</main>
  <script>
    document.addEventListener("click", async function (event) {{
      var target = event.target;
      var button = target && target.closest ? target.closest("[data-copy-value]") : null;
      if (!button) return;
      event.preventDefault();
      var value = button.getAttribute("data-copy-value") || "";
      var original = button.getAttribute("data-copy-label") || button.textContent || "Copy";
      try {{
        if (!navigator.clipboard) throw new Error("Clipboard unavailable");
        await navigator.clipboard.writeText(value);
      }} catch (error) {{
        var source = button.parentElement ? button.parentElement.querySelector("[data-copy-source]") : null;
        if (source && source.select) {{
          source.select();
          document.execCommand("copy");
        }}
      }}
      button.textContent = "Copied";
      window.setTimeout(function () {{ button.textContent = original; }}, 1800);
    }});
  </script>
</body>
</html>"""
    return HTMLResponse(html)


def _survey_select(selected: str = "new_member", session: Session | None = None) -> str:
    options = []
    for option in survey_options(session):
        choice = _esc(option["key"])
        label = _esc(option["label"])
        is_selected = " selected" if option["key"] == selected else ""
        options.append(f'<option value="{choice}"{is_selected}>{label}</option>')
    return '<select name="flow_key">' + "".join(options) + "</select>"


def _start_survey_form(
    request: Request,
    member_id: int,
    default_flow: str = "new_member",
    session: Session | None = None,
) -> str:
    return f"""
<form method="post" action="{_post_action(request, f'/admin/members/{member_id}/start')}" class="inline">
  {_survey_select(default_flow, session)}
  <button type="submit">Send SMS link</button>
</form>"""


def _app_link_form(
    request: Request,
    member: Member,
    default_flow: str = "new_member",
    session: Session | None = None,
) -> str:
    email_note = (
        f'<span class="muted">Can send by email to {_esc(member.email)}</span>'
        if str(getattr(member, "email", "") or "").strip()
        else '<span class="muted">Create a link to share manually</span>'
    )
    return f"""
<form method="post" action="{_post_action(request, f'/admin/members/{int(member.id)}/app-link')}" class="inline">
  {_survey_select(default_flow, session)}
  <button type="submit" class="secondary">Create app link</button>
  {email_note}
</form>"""


def _survey_action(
    request: Request,
    member: Member,
    default_flow: str = "new_member",
    session: Session | None = None,
) -> str:
    actions = []
    if member_contact_phone(member):
        actions.append(_start_survey_form(request, int(member.id), default_flow, session))
    else:
        actions.append('<span class="muted">No mobile for SMS</span>')
    actions.append(_app_link_form(request, member, default_flow, session))
    return '<div class="stack">' + "".join(actions) + "</div>"


def _visit_survey_form(request: Request, member: Member) -> str:
    if member_contact_phone(member):
        button_text = "Confirm visit and send visit survey"
        helper = '<span class="muted">Records today as the last visit and sends the member an SMS survey link.</span>'
    else:
        button_text = "Confirm visit and create visit link"
        helper = '<span class="muted">Records today as the last visit and creates a browser survey link.</span>'
    return f"""
<form method="post" action="{_post_action(request, f'/admin/members/{int(member.id)}/visit-survey')}" class="inline">
  <button type="submit">{_esc(button_text)}</button>
  {helper}
</form>"""


def _coerce_range(min_days: int, max_days: int) -> tuple[int, int]:
    low = max(int(min_days or 0), 0)
    high = max(int(max_days or low), low)
    return low, high


def _filter_choice(value: str, allowed: set[str], default: str = "any") -> str:
    selected = str(value or default).strip().lower().replace("-", "_")
    return selected if selected in allowed else default


def _filter_select(name: str, selected: str, options: list[tuple[str, str]]) -> str:
    items = []
    for value, label in options:
        active = " selected" if value == selected else ""
        items.append(f'<option value="{_esc(value)}"{active}>{_esc(label)}</option>')
    return f'<select name="{_esc(name)}">' + "".join(items) + "</select>"


def _member_has_email(member: Member) -> bool:
    return bool(str(getattr(member, "email", "") or "").strip())


def _member_matches_list_filters(
    session: Session,
    member: Member,
    *,
    flow_key: str,
    mobile_filter: str = "any",
    email_filter: str = "any",
    sent_filter: str = "any",
) -> bool:
    has_mobile = bool(member_contact_phone(member))
    has_email = _member_has_email(member)
    latest = latest_survey_for_member(session, int(member.id), flow_key)
    latest_status = str(getattr(latest, "status", "") or "").strip().lower() if latest is not None else ""
    was_sent = latest is not None and latest_status != "send_failed"
    if mobile_filter == "present" and not has_mobile:
        return False
    if mobile_filter == "missing" and has_mobile:
        return False
    if email_filter == "present" and not has_email:
        return False
    if email_filter == "missing" and has_email:
        return False
    if sent_filter == "not_sent" and was_sent:
        return False
    if sent_filter == "sent" and not was_sent:
        return False
    return True


def _apply_list_filters(
    session: Session,
    members: list[Member],
    *,
    flow_key: str,
    mobile_filter: str = "any",
    email_filter: str = "any",
    sent_filter: str = "any",
) -> list[Member]:
    return [
        member
        for member in members
        if _member_matches_list_filters(
            session,
            member,
            flow_key=flow_key,
            mobile_filter=mobile_filter,
            email_filter=email_filter,
            sent_filter=sent_filter,
        )
    ]


def _filter_fetch_limit(limit: int) -> int:
    return max(min(int(limit or 200) * 5, 2500), int(limit or 200), 1)


def _list_filter_fields(mobile_filter: str, email_filter: str, sent_filter: str) -> str:
    return f"""
    <label><span>Mobile</span>{_filter_select('mobile_filter', mobile_filter, [('any', 'Any'), ('present', 'Mobile present'), ('missing', 'No mobile')])}</label>
    <label><span>Email</span>{_filter_select('email_filter', email_filter, [('any', 'Any'), ('present', 'Email present'), ('missing', 'No email')])}</label>
    <label><span>Survey</span>{_filter_select('sent_filter', sent_filter, [('any', 'Any'), ('not_sent', 'Not sent'), ('sent', 'Sent')])}</label>
"""


def _hidden_list_filters(mobile_filter: str, email_filter: str, sent_filter: str) -> str:
    return f"""
      <input type="hidden" name="mobile_filter" value="{_esc(mobile_filter)}">
      <input type="hidden" name="email_filter" value="{_esc(email_filter)}">
      <input type="hidden" name="sent_filter" value="{_esc(sent_filter)}">
"""


def _segment_table(
    request: Request,
    session: Session,
    members: list[Member],
    *,
    date_attr: str,
    empty_text: str,
    default_flow: str,
) -> str:
    table = []
    for member in members:
        flow_survey = latest_survey_for_member(session, int(member.id), default_flow)
        active = active_conversation_for_member(session, int(member.id))
        flow_status = str(getattr(flow_survey, "status", "") or "").strip().lower() if flow_survey is not None else ""
        if flow_survey is not None and flow_status == "send_failed":
            action = _survey_action(request, member, default_flow, session)
        elif flow_survey is not None:
            action = f'<a class="button secondary" href="{_href(request, f"/admin/surveys/{flow_survey.id}")}">Open survey</a>'
        elif active is not None:
            action = '<span class="muted">Survey already active</span>'
        else:
            action = _survey_action(request, member, default_flow, session)
        member_url = _href(request, f"/admin/members/{member.id}")
        raw_date = getattr(member, date_attr, None)
        age = days_since(raw_date)
        age_text = f"{age} days" if age is not None else ""
        survey_status = _segment_survey_status(request, flow_survey)
        table.append(
            "<tr>"
            f"<td><a href=\"{member_url}\">{_esc(member_name(member))}</a><br><span class=\"muted\">{_esc(_mobile_label(member))}</span></td>"
            f"<td><span class=\"pill\">{_esc(_member_status_label(member))}</span></td>"
            f"<td>{_esc(_date(raw_date)) or 'Not recorded'}</td>"
            f"<td>{_esc(age_text)}</td>"
            f"<td>{survey_status}</td>"
            f"<td>{action}</td>"
            "</tr>"
        )
    return "".join(table) or f'<tr><td colspan="6">{_esc(empty_text)}</td></tr>'


def _segment_survey_status(request: Request, conversation: Conversation | None) -> str:
    if conversation is None:
        return '<span class="pill">Not sent</span>'
    sent = _datetime(conversation.created_at)
    status = str(conversation.status or "").strip().lower()
    if status == "send_failed":
        return (
            f'<a href="{_href(request, "/admin/sms-diagnostics")}"><span class="error">Send failed</span></a>'
            f'<br><span class="muted">Attempted {sent}. Review SMS diagnostics.</span>'
        )
    if status == "completed":
        response_status = "Member completed the survey"
    elif status == "active":
        response_status = "Awaiting response"
    elif status:
        response_status = f"Survey status: {status}"
    else:
        response_status = "Survey sent"
    return (
        f'<a href="{_href(request, f"/admin/surveys/{conversation.id}")}"><span class="pill">Completed</span></a>'
        f'<br><span class="muted">Sent {sent}. {response_status}.</span>'
    )


def _send_segment(
    request: Request,
    session: Session,
    members: list[Member],
    flow_key: str,
    *,
    limit: int,
) -> tuple[int, int, str]:
    sent = 0
    failed = 0
    first_error = ""
    max_to_send = max(min(int(limit or 0), 500), 1)
    for member in members:
        if sent >= max_to_send:
            break
        latest = latest_survey_for_member(session, int(member.id), flow_key)
        if latest is not None and str(latest.status or "").strip().lower() != "send_failed":
            continue
        if not member_contact_phone(member):
            continue
        if active_conversation_for_member(session, int(member.id)):
            continue
        try:
            _start_and_send_survey_link(request, session, member, flow_key)
        except Exception as exc:
            failed += 1
            if not first_error:
                first_error = _sms_error_text(exc)
            break
        sent += 1
    return sent, failed, first_error


def _datetime(value) -> str:
    return value.strftime("%d/%m/%y %H:%M") if value else ""


def _public_base_url(request: Request) -> str:
    configured = str(getattr(config, "PUBLIC_BASE_URL", "") or "").strip()
    if configured:
        return configured.rstrip("/")
    return str(request.base_url).rstrip("/")


def _app_survey_url(request: Request, conversation: Conversation) -> str:
    token = str(getattr(conversation, "app_link_token", "") or "").strip()
    return f"{_public_base_url(request)}/s/{token}" if token else ""


def _start_and_send_survey_link(
    request: Request,
    session: Session,
    member: Member,
    flow_key: str,
) -> Conversation:
    conversation = start_conversation(session, member, flow_key, send_intro=False, commit=False)
    try:
        send_survey_link_to_member(session, member, conversation, _app_survey_url(request, conversation))
    except Exception:
        conversation.status = "send_failed"
        session.add(conversation)
        session.commit()
        raise
    return conversation


def _survey_mailto(member: Member | None, link: str, label: str) -> str:
    email = str(getattr(member, "email", "") or "").strip()
    if not email or not link:
        return ""
    subject = f"{config.GYM_NAME}: {label}"
    body = (
        f"Hi {member_name(member)},\n\n"
        f"Please complete this quick {label.lower()} when you have a moment:\n\n"
        f"{link}\n\n"
        f"Thank you,\n{config.GYM_NAME}"
    )
    return "mailto:" + email + "?" + urlencode({"subject": subject, "body": body})


def _survey_flow(conversation: Conversation, session: Session | None = None):
    try:
        if session is not None:
            return effective_survey_flow(session, conversation.flow_key)
        return flow_for_key(conversation.flow_key)
    except Exception:
        return None


def _survey_label(conversation: Conversation, session: Session | None = None) -> str:
    flow = _survey_flow(conversation, session)
    return flow.label if flow else str(conversation.flow_key or "Survey")


def _survey_progress(conversation: Conversation, session: Session | None = None) -> str:
    answers = dict(conversation.answers or {})
    flow = _survey_flow(conversation, session)
    if flow:
        answered = sum(1 for question in flow.questions if str(answers.get(question.key) or "").strip())
        return f"{answered}/{len(flow.questions)}"
    if answers:
        return f"{len(answers)} answered"
    return "0 answered"


def _survey_outcome(conversation: Conversation) -> str:
    classification = dict(conversation.classification or {})
    for key in ("recommended_action", "support_need", "reactivation_opportunity", "save_opportunity", "priority"):
        value = str(classification.get(key) or "").strip()
        if value:
            return value
    return conversation.summary or ""


def _survey_answer_rows(conversation: Conversation, session: Session | None = None) -> str:
    answers = dict(conversation.answers or {})
    flow = _survey_flow(conversation, session)
    used_keys: set[str] = set()
    rows = []
    if flow:
        for index, question in enumerate(flow.questions, start=1):
            used_keys.add(question.key)
            answer = str(answers.get(question.key) or "").strip()
            answer_html = _esc(answer) if answer else '<span class="muted">Not answered yet</span>'
            rows.append(
                "<tr>"
                f"<td>{index}</td>"
                f"<td>{_esc(question.text)}</td>"
                f"<td>{answer_html}</td>"
                "</tr>"
            )
    for key, value in answers.items():
        if key in used_keys:
            continue
        rows.append(
            "<tr>"
            f"<td>{len(rows) + 1}</td>"
            f"<td>{_esc(key)}</td>"
            f"<td>{_esc(value)}</td>"
            "</tr>"
        )
    return "".join(rows) or '<tr><td colspan="3">No answers recorded yet.</td></tr>'


def _classification_rows(classification: dict | None) -> str:
    rows = []
    for key, value in dict(classification or {}).items():
        rows.append(
            "<tr>"
            f"<td>{_esc(str(key).replace('_', ' ').title())}</td>"
            f"<td>{_esc(value)}</td>"
            "</tr>"
        )
    return "".join(rows) or '<tr><td colspan="2">No classification yet.</td></tr>'


def _survey_avatar_html(flow) -> str:
    video_url = str(getattr(flow, "avatar_video_url", "") or "").strip()
    if not video_url:
        return ""
    poster_url = str(getattr(flow, "avatar_poster_url", "") or "").strip()
    poster_attr = f' poster="{_esc(poster_url)}"' if poster_url else ""
    return f"""
<div class="avatar-video">
  <video src="{_esc(video_url)}"{poster_attr} controls playsinline preload="metadata"></video>
</div>"""


def _public_survey_layout(title: str, body: str) -> HTMLResponse:
    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{_esc(title)} - {config.APP_NAME}</title>
  <style>
    :root {{
      --background: #ffffff;
      --surface: #fffaf3;
      --surface-soft: #fbf7f0;
      --border: #e7e1d6;
      --text: #1e1b16;
      --muted: #6b6257;
      --accent: #6d28d9;
      --accent-soft: #f1e8ff;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      min-height: 100vh;
      background: var(--background);
      color: var(--text);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      line-height: 1.5;
    }}
    main {{
      min-height: 100vh;
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 24px;
    }}
    .shell {{
      width: min(760px, 100%);
      border: 1px solid var(--border);
      border-radius: 8px;
      background: var(--surface);
      padding: 28px;
      box-shadow: 0 30px 80px -60px rgba(30, 27, 22, 0.45);
    }}
    .eyebrow {{
      margin: 0 0 10px;
      color: var(--muted);
      font-size: 12px;
      font-weight: 800;
      letter-spacing: 0.18em;
      text-transform: uppercase;
    }}
    h1 {{ margin: 0; font-size: clamp(26px, 4vw, 38px); line-height: 1.08; }}
    p {{ margin: 12px 0 0; }}
    .muted {{ color: var(--muted); }}
    .progress {{
      margin: 20px 0;
      height: 8px;
      overflow: hidden;
      border-radius: 999px;
      background: #eadfce;
    }}
    .progress span {{
      display: block;
      height: 100%;
      background: var(--accent);
      border-radius: 999px;
    }}
    .avatar-video {{
      margin: 18px 0;
      overflow: hidden;
      border-radius: 8px;
      border: 1px solid var(--border);
      background: #111;
    }}
    .avatar-video video {{
      display: block;
      width: 100%;
      max-height: 420px;
      object-fit: cover;
    }}
    form {{ display: grid; gap: 12px; margin-top: 22px; }}
    label.option {{
      display: flex;
      gap: 10px;
      align-items: center;
      border: 1px solid var(--border);
      border-radius: 8px;
      background: #fff;
      padding: 14px 16px;
      font-weight: 800;
      cursor: pointer;
    }}
    label.option:focus-within {{ border-color: var(--accent); box-shadow: 0 0 0 3px var(--accent-soft); }}
    input[type="radio"] {{ accent-color: var(--accent); }}
    button {{
      border: 0;
      border-radius: 8px;
      background: var(--accent);
      color: white;
      padding: 13px 16px;
      font: inherit;
      font-weight: 900;
      cursor: pointer;
    }}
    .error {{
      margin-top: 16px;
      border: 1px solid #f0b4aa;
      border-radius: 8px;
      background: #fff1ef;
      color: #8f261c;
      padding: 12px;
      font-weight: 800;
    }}
    @media (max-width: 640px) {{
      main {{ align-items: flex-start; padding: 14px; }}
      .shell {{ padding: 20px; }}
    }}
  </style>
</head>
<body>
  <main><section class="shell">{body}</section></main>
</body>
</html>"""
    return HTMLResponse(html)


def _public_survey_response(
    conversation: Conversation,
    member: Member | None,
    session: Session,
    error: str = "",
    *,
    show_intro: bool = False,
) -> HTMLResponse:
    flow = _survey_flow(conversation, session)
    if flow is None:
        raise HTTPException(status_code=404, detail="Survey not found")
    answers = dict(conversation.answers or {})
    total = len(flow.questions)
    step_index = max(min(int(conversation.step_index or 0), total), 0)
    answered = sum(1 for question in flow.questions if str(answers.get(question.key) or "").strip())
    if conversation.status == "completed" or step_index >= total:
        body = f"""
<p class="eyebrow">{_esc(config.GYM_NAME)}</p>
<h1>Thanks, {_esc(member_name(member))}</h1>
<p class="muted">{_esc(flow.completion)}</p>
<div class="progress"><span style="width: 100%"></span></div>
<p>Your answers have been recorded.</p>"""
        return _public_survey_layout("Survey complete", body)
    if show_intro and step_index == 0 and not answers:
        intro = str(flow.intro or "").strip()
        first_name = member_first_name(member)
        greeting = f"Hi {first_name}" if first_name else f"Welcome to {config.GYM_NAME}"
        gym_welcome = f"Welcome to {config.GYM_NAME}."
        if first_name and intro.lower().startswith(gym_welcome.lower()):
            greeting = f"Hi {first_name}, welcome to {config.GYM_NAME}"
            intro = intro[len(gym_welcome) :].strip()
        elif first_name and intro.lower().startswith("hi, "):
            intro = intro[4:].strip()
            if intro:
                intro = f"{intro[0].upper()}{intro[1:]}"
        if not intro:
            intro = survey_intro_for_member(member, flow.intro)
        body = f"""
<p class="eyebrow">{_esc(config.GYM_NAME)}</p>
<h1>{_esc(greeting)}</h1>
{_survey_avatar_html(flow)}
<p class="muted">{_esc(intro)}</p>
<div class="progress"><span style="width: 0%"></span></div>
<form method="get">
  <input type="hidden" name="start" value="1">
  <button type="submit">Start survey</button>
</form>"""
        return _public_survey_layout(flow.label, body)
    question = flow.questions[step_index]
    pct = round((answered / max(total, 1)) * 100)
    option_inputs = []
    for option in question_options(question):
        option_inputs.append(
            f"""
<label class="option">
  <input type="radio" name="answer" value="{_esc(option)}" required>
  <span>{_esc(option)}</span>
</label>"""
        )
    error_html = f'<div class="error">{_esc(error)}</div>' if error else ""
    body = f"""
<p class="eyebrow">{_esc(config.GYM_NAME)} · Question {step_index + 1} of {total}</p>
<h1>{_esc(question.text)}</h1>
<div class="progress"><span style="width: {pct}%"></span></div>
{error_html}
<form method="post">
  {''.join(option_inputs)}
  <button type="submit">Continue</button>
</form>"""
    return _public_survey_layout(flow.label, body)


@router.get("/s/{token}", response_class=HTMLResponse)
def public_survey(token: str, start: str = "", session: Session = Depends(get_session)):
    conversation = find_conversation_by_app_token(session, token)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Survey not found")
    member = session.get(Member, conversation.member_id)
    return _public_survey_response(conversation, member, session, show_intro=not str(start or "").strip())


@router.post("/s/{token}", response_class=HTMLResponse)
def public_survey_submit(
    token: str,
    answer: str = Form(""),
    session: Session = Depends(get_session),
):
    conversation = find_conversation_by_app_token(session, token)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Survey not found")
    member = session.get(Member, conversation.member_id)
    if member is None:
        raise HTTPException(status_code=404, detail="Member not found")
    try:
        continue_app_conversation(session, member, conversation, answer)
    except ValueError as exc:
        return _public_survey_response(conversation, member, session, str(exc))
    session.refresh(conversation)
    return _public_survey_response(conversation, member, session)


def _auth_layout(title: str, body: str) -> HTMLResponse:
    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{_esc(title)} - {config.APP_NAME}</title>
  <style>
    :root {{
      --ink: #171717;
      --muted: #5f6368;
      --line: #d8ded9;
      --paper: #f7f8f5;
      --surface: #ffffff;
      --accent: #6d28d9;
      --accent-2: #4c1d95;
      --danger: #a33b2b;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      min-height: 100vh;
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 20px;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      color: var(--ink);
      background: var(--paper);
    }}
    main {{
      width: min(460px, 100%);
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 24px;
    }}
    h1 {{ margin: 0 0 8px; font-size: 25px; }}
    p {{ margin: 0 0 16px; }}
    .muted {{ color: var(--muted); }}
    .error {{ border: 1px solid #f0b4aa; background: #fff1ef; color: var(--danger); border-radius: 8px; padding: 10px; font-weight: 800; }}
    form {{ display: grid; gap: 12px; margin-top: 18px; }}
    label {{ display: grid; gap: 4px; font-weight: 800; }}
    label span {{ color: var(--muted); font-size: 13px; }}
    input, select {{
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 10px;
      font: inherit;
    }}
    button {{
      border: 0;
      border-radius: 6px;
      padding: 10px 12px;
      background: var(--accent);
      color: #fff;
      font: inherit;
      font-weight: 900;
      cursor: pointer;
    }}
  </style>
</head>
<body>
  <main>{body}</main>
</body>
</html>"""
    return HTMLResponse(html)


def _login_form(*, next_path: str = "/admin", error: str = "") -> HTMLResponse:
    error_html = f'<p class="error">{_esc(error)}</p>' if error else ""
    body = f"""
<h1>MemberSense Login</h1>
<p class="muted">Sign in with your staff account.</p>
{error_html}
<form method="post" action="/admin/login">
  <input type="hidden" name="next" value="{_esc(next_path)}">
  <label><span>Username or email</span><input name="email" autocomplete="username" required></label>
  <label><span>Password</span><input name="password" type="password" autocomplete="current-password" required></label>
  <button type="submit">Sign in</button>
</form>"""
    return _auth_layout("Login", body)


def _setup_form(request: Request, *, error: str = "") -> HTMLResponse:
    error_html = f'<p class="error">{_esc(error)}</p>' if error else ""
    body = f"""
<h1>Set Up Staff Login</h1>
<p class="muted">Create the first MemberSense staff account. This account can add other staff users.</p>
{error_html}
<form method="post" action="{_post_action(request, '/admin/setup')}">
  <label><span>Name</span><input name="name" autocomplete="name" required></label>
  <label><span>Username</span><input name="username" autocomplete="username"></label>
  <label><span>Email</span><input name="email" type="email" autocomplete="username" required></label>
  <label><span>Password</span><input name="password" type="password" autocomplete="new-password" minlength="8" required></label>
  <button type="submit">Create staff account</button>
</form>"""
    return _auth_layout("Staff Setup", body)


@router.get("/admin/setup", response_class=HTMLResponse)
def staff_setup(request: Request, session: Session = Depends(get_session)):
    if staff_count(session) > 0:
        return RedirectResponse("/admin/login", status_code=303)
    if config.ADMIN_TOKEN and not _legacy_token_allowed(request):
        return _auth_layout(
            "Staff Setup",
            """
<h1>Set Up Staff Login</h1>
<p class="error">First staff setup requires the admin token.</p>
<p class="muted">Open this page with <strong>?token=your-admin-token</strong> to create the owner account.</p>""",
        )
    return _setup_form(request)


@router.post("/admin/setup", response_class=HTMLResponse)
def staff_setup_save(
    request: Request,
    name: str = Form(...),
    username: str = Form(""),
    email: str = Form(...),
    password: str = Form(...),
    session: Session = Depends(get_session),
):
    if staff_count(session) > 0:
        return RedirectResponse("/admin/login", status_code=303)
    if config.ADMIN_TOKEN and not _legacy_token_allowed(request):
        return _setup_form(request, error="First staff setup requires the admin token.")
    try:
        staff = create_staff_user(
            session,
            username=username or None,
            email=email,
            name=name,
            password=password,
            role="owner",
            is_active=True,
        )
        session.commit()
        session.refresh(staff)
    except ValueError as exc:
        session.rollback()
        return _setup_form(request, error=str(exc))
    response = RedirectResponse("/admin", status_code=303)
    set_staff_cookie(response, staff)
    return response


@router.get("/admin/login", response_class=HTMLResponse)
def login(request: Request, next: str = "/admin", session: Session = Depends(get_session)):
    next_path = safe_next_path(next)
    if staff_count(session) <= 0:
        return RedirectResponse("/admin/setup", status_code=303)
    if staff_from_request(request, session) is not None:
        return RedirectResponse(next_path, status_code=303)
    return _login_form(next_path=next_path)


@router.post("/admin/login", response_class=HTMLResponse)
def login_save(
    next: str = Form("/admin"),
    email: str = Form(...),
    password: str = Form(...),
    session: Session = Depends(get_session),
):
    next_path = safe_next_path(next)
    if staff_count(session) <= 0:
        return RedirectResponse("/admin/setup", status_code=303)
    staff = authenticate_staff(session, login=email, password=password)
    if staff is None:
        session.rollback()
        return _login_form(next_path=next_path, error="Email or password is incorrect.")
    session.commit()
    session.refresh(staff)
    response = RedirectResponse(next_path, status_code=303)
    set_staff_cookie(response, staff)
    return response


@router.get("/admin/logout")
def logout():
    response = RedirectResponse("/admin/login", status_code=303)
    clear_staff_cookie(response)
    return response


@router.get("/admin", response_class=HTMLResponse)
def dashboard(request: Request, session: Session = Depends(get_session), _: None = Depends(require_admin)):
    today = date.today()
    current_members = current_member_rows(session, today=today)
    current_count = len(current_members)
    active_cutoff = today - timedelta(days=21)
    active_21_count = sum(
        1 for member in current_members if member.last_visit_date is not None and member.last_visit_date >= active_cutoff
    )
    inactive_21_count = sum(
        1 for member in current_members if member.last_visit_date is None or member.last_visit_date < active_cutoff
    )
    expired_cutoff = today - timedelta(days=30)
    expired_30_count = (
        session.scalar(
            select(func.count())
            .select_from(Member)
            .where(
                Member.expiry_date.is_not(None),
                Member.expiry_date >= expired_cutoff,
                Member.expiry_date <= today,
            )
        )
        or 0
    )
    open_tasks = session.scalar(select(func.count()).select_from(StaffTask).where(StaffTask.status == "open")) or 0
    body = f"""
<section>
  <h2>Dashboard</h2>
  <div class="grid">
    <div class="metric"><strong>{current_count}</strong><span>Current members</span></div>
    <div class="metric"><strong>{active_21_count}</strong><span>Active members, visited in last 21 days</span></div>
    <div class="metric"><strong>{inactive_21_count}</strong><span>Inactive over 21 days</span></div>
    <div class="metric"><strong>{expired_30_count}</strong><span>Expired members in last 30 days</span></div>
    <div class="metric"><strong>{open_tasks}</strong><span>Open staff tasks</span></div>
  </div>
</section>"""
    return _layout(request, "Dashboard", body)


def _configured(value: object) -> str:
    return "Configured" if str(value or "").strip() else "Not configured"


def _sms_status_hint(status: str | None, raw_payload: object | None) -> str:
    value = str(status or "").strip().lower()
    raw = raw_payload if isinstance(raw_payload, dict) else {}
    error = str(raw.get("error") or raw.get("ErrorMessage") or raw.get("ErrorCode") or "").strip()
    if value == "dry_run":
        return "Dry run is on, so no SMS was sent to Twilio."
    if value == "failed":
        return f"Send failed before or during Twilio request. {error}".strip()
    if value == "undelivered":
        return f"Twilio/carrier did not deliver the message. {error}".strip()
    if value == "delivered":
        return "Delivered according to Twilio status callback."
    if value in {"accepted", "queued", "sending", "sent"}:
        return "Twilio accepted the message. Wait for delivered or undelivered status callback."
    if not value:
        return "No status recorded yet."
    return "Review Twilio message logs for this status."


@router.get("/admin/sms-diagnostics", response_class=HTMLResponse)
def sms_diagnostics(
    request: Request,
    error: str = "",
    session: Session = Depends(get_session),
    _: None = Depends(require_admin),
):
    issues = []
    if config.DRY_RUN_MESSAGES:
        issues.append("MEMBERSENSE_DRY_RUN is on, so SMS messages are only printed in logs and are not sent.")
    if not config.TWILIO_ACCOUNT_SID or not config.TWILIO_AUTH_TOKEN:
        issues.append("Twilio Account SID or Auth Token is missing.")
    if not config.TWILIO_FROM and not config.TWILIO_MESSAGING_SERVICE_SID:
        issues.append("No SMS sender is configured. Set MEMBERSENSE_TWILIO_FROM or MEMBERSENSE_TWILIO_MESSAGING_SERVICE_SID.")
    if str(config.TWILIO_FROM or "").lower().startswith("whatsapp:"):
        issues.append("MEMBERSENSE_TWILIO_FROM still has a whatsapp: prefix. Use an SMS number like +447447196400.")
    if not config.PUBLIC_BASE_URL:
        issues.append("MEMBERSENSE_PUBLIC_BASE_URL or RENDER_EXTERNAL_URL is missing, so survey links/status callbacks may use the request host.")

    config_rows = [
        ("Dry run", "On" if config.DRY_RUN_MESSAGES else "Off"),
        ("Twilio Account SID", _configured(config.TWILIO_ACCOUNT_SID)),
        ("Twilio Auth Token", _configured(config.TWILIO_AUTH_TOKEN)),
        ("SMS from number", str(config.TWILIO_FROM or "").strip() or "Not configured"),
        ("Messaging Service SID", _configured(config.TWILIO_MESSAGING_SERVICE_SID)),
        ("Public base URL", str(config.PUBLIC_BASE_URL or "").strip() or "Using request host"),
        (
            "Status callback",
            f"{config.TWILIO_STATUS_CALLBACK_BASE.rstrip('/')}/webhooks/twilio-status"
            if config.TWILIO_STATUS_CALLBACK_BASE
            else "Not configured",
        ),
        ("Inbound webhook", f"{_public_base_url(request)}/webhooks/twilio"),
    ]
    config_html = "".join(f"<tr><td>{_esc(label)}</td><td>{_esc(value)}</td></tr>" for label, value in config_rows)

    outbound = (
        session.execute(
            select(MessageLog)
            .where(MessageLog.channel == "sms", MessageLog.direction == "outbound")
            .order_by(desc(MessageLog.id))
            .limit(50)
        )
        .scalars()
        .all()
    )
    outbound_rows = []
    for message in outbound:
        member = session.get(Member, int(message.member_id)) if message.member_id else None
        raw = message.raw_payload if isinstance(message.raw_payload, dict) else {}
        error_text = str(raw.get("error") or raw.get("ErrorMessage") or raw.get("ErrorCode") or "").strip()
        hint = _sms_status_hint(message.status, raw)
        outbound_rows.append(
            "<tr>"
            f"<td>{_esc(_datetime(message.created_at))}</td>"
            f"<td>{_esc(member_name(member) if member else 'No member')}</td>"
            f"<td>{_esc(message.phone_e164 or '')}</td>"
            f"<td><span class=\"pill\">{_esc(message.status or 'unknown')}</span></td>"
            f"<td>{_esc(message.provider_sid or '')}</td>"
            f"<td>{_esc((message.body or '')[:160])}</td>"
            f"<td>{_esc(error_text or hint)}</td>"
            "</tr>"
        )

    inbound = (
        session.execute(
            select(MessageLog)
            .where(MessageLog.channel == "sms", MessageLog.direction == "inbound")
            .order_by(desc(MessageLog.id))
            .limit(20)
        )
        .scalars()
        .all()
    )
    inbound_rows = []
    for message in inbound:
        member = session.get(Member, int(message.member_id)) if message.member_id else None
        inbound_rows.append(
            "<tr>"
            f"<td>{_esc(_datetime(message.created_at))}</td>"
            f"<td>{_esc(member_name(member) if member else 'No member')}</td>"
            f"<td>{_esc(message.phone_e164 or '')}</td>"
            f"<td>{_esc((message.body or '')[:180])}</td>"
            "</tr>"
        )

    issue_html = (
        "<ul>" + "".join(f"<li>{_esc(issue)}</li>" for issue in issues) + "</ul>"
        if issues
        else '<p><span class="pill">No obvious configuration issues found.</span></p>'
    )
    error_html = f'<p class="error">{_esc(error)}</p>' if str(error or "").strip() else ""
    body = f"""
<section>
  <h2>SMS Diagnostics</h2>
  <p class="muted">Use this page when a member has not received a survey link. It shows the live SMS configuration and recent Twilio statuses.</p>
  {error_html}
  {issue_html}
</section>
<section>
  <h2>Configuration</h2>
  <table>
    <thead><tr><th>Setting</th><th>Status</th></tr></thead>
    <tbody>{config_html}</tbody>
  </table>
</section>
<section>
  <h2>Recent Outbound SMS</h2>
  <table>
    <thead><tr><th>Sent</th><th>Member</th><th>To</th><th>Status</th><th>Twilio SID</th><th>Message</th><th>Diagnosis</th></tr></thead>
    <tbody>{''.join(outbound_rows) or '<tr><td colspan="7">No outbound SMS has been logged yet.</td></tr>'}</tbody>
  </table>
</section>
<section>
  <h2>Recent Inbound SMS</h2>
  <table>
    <thead><tr><th>Received</th><th>Member</th><th>From</th><th>Message</th></tr></thead>
    <tbody>{''.join(inbound_rows) or '<tr><td colspan="4">No inbound SMS has been logged yet.</td></tr>'}</tbody>
  </table>
</section>"""
    return _layout(request, "SMS Diagnostics", body)


@router.get("/admin/staff", response_class=HTMLResponse)
def staff_admin(
    request: Request,
    created: int | None = None,
    updated: int | None = None,
    error: str = "",
    session: Session = Depends(get_session),
    _: None = Depends(require_admin),
):
    rows = session.execute(select(StaffUser).order_by(StaffUser.is_active.desc(), StaffUser.name.asc())).scalars().all()
    notice_parts = []
    if created is not None:
        notice_parts.append("Staff account created.")
    if updated is not None:
        notice_parts.append("Staff account updated.")
    if error:
        notice_parts.append(str(error))
    notice_class = "error" if error else "pill"
    notice_html = f'<p><span class="{notice_class}">{_esc(" ".join(notice_parts))}</span></p>' if notice_parts else ""
    table_rows = []
    active_total = active_staff_count(session)
    for row in rows:
        status = "Active" if bool(row.is_active) else "Inactive"
        toggle_label = "Deactivate" if bool(row.is_active) else "Activate"
        disable_toggle = bool(row.is_active) and active_total <= 1
        toggle = (
            '<span class="muted">Last active staff account</span>'
            if disable_toggle
            else f"""
<form method="post" action="{_post_action(request, f'/admin/staff/{int(row.id)}/toggle')}" class="inline">
  <button type="submit" class="secondary">{toggle_label}</button>
</form>"""
        )
        table_rows.append(
            "<tr>"
            f"<td>{_esc(row.name)}<br><span class=\"muted\">{_esc(row.username or '')}</span><br><span class=\"muted\">{_esc(row.email)}</span></td>"
            f"<td><span class=\"pill\">{_esc(row.role)}</span></td>"
            f"<td>{_esc(status)}</td>"
            f"<td>{_esc(_datetime(row.last_login_at)) or 'Not yet'}</td>"
            f"<td>{_esc(_datetime(row.created_at))}</td>"
            f"<td>{toggle}</td>"
            "</tr>"
        )
    body = f"""
<section>
  <h2>Staff Setup</h2>
  <p class="muted">Create staff logins for MemberSense admin access. Passwords are stored as salted hashes.</p>
  {notice_html}
  <form method="post" action="{_post_action(request, '/admin/staff')}" class="stack">
    <div class="grid">
      <label><span>Name</span><input name="name" required></label>
      <label><span>Username</span><input name="username"></label>
      <label><span>Email</span><input name="email" type="email" required></label>
      <label><span>Password</span><input name="password" type="password" minlength="8" required></label>
      <label><span>Role</span><select name="role">
        <option value="staff">Staff</option>
        <option value="admin">Admin</option>
        <option value="owner">Owner</option>
      </select></label>
    </div>
    <button type="submit">Add staff</button>
  </form>
</section>
<section>
  <h2>Staff Accounts</h2>
  <table>
    <thead><tr><th>Staff</th><th>Role</th><th>Status</th><th>Last login</th><th>Created</th><th>Action</th></tr></thead>
    <tbody>{''.join(table_rows) or '<tr><td colspan="6">No staff accounts yet.</td></tr>'}</tbody>
  </table>
</section>"""
    return _layout(request, "Staff Setup", body)


@router.post("/admin/staff")
def staff_create(
    request: Request,
    name: str = Form(...),
    username: str = Form(""),
    email: str = Form(...),
    password: str = Form(...),
    role: str = Form("staff"),
    session: Session = Depends(get_session),
    _: None = Depends(require_admin),
):
    try:
        create_staff_user(
            session,
            username=username or None,
            email=email,
            name=name,
            password=password,
            role=role,
            is_active=True,
        )
        session.commit()
    except ValueError as exc:
        session.rollback()
        return _redirect(request, f"/admin/staff?{urlencode({'error': str(exc)})}")
    return _redirect(request, "/admin/staff?created=1")


@router.post("/admin/staff/{staff_id}/toggle")
def staff_toggle(
    request: Request,
    staff_id: int,
    session: Session = Depends(get_session),
    _: None = Depends(require_admin),
):
    row = session.get(StaffUser, int(staff_id))
    if row is None:
        raise HTTPException(status_code=404, detail="Staff account not found")
    if bool(row.is_active) and active_staff_count(session) <= 1:
        return _redirect(request, f"/admin/staff?{urlencode({'error': 'Keep at least one active staff account.'})}")
    row.is_active = not bool(row.is_active)
    session.add(row)
    session.commit()
    return _redirect(request, "/admin/staff?updated=1")


@router.get("/admin/reports/visits", response_class=HTMLResponse)
def visit_report(request: Request, session: Session = Depends(get_session), _: None = Depends(require_admin)):
    today = date.today()
    members = current_member_rows(session, today=today)
    total = len(members)

    rows: list[dict[str, object]] = []
    for days in (21, 60, 90, 120):
        cutoff = today - timedelta(days=days)
        count = sum(1 for member in members if member.last_visit_date and member.last_visit_date > cutoff)
        rows.append(
            {
                "label": f"Visited in last {days} days",
                "count": count,
                "cutoff": cutoff,
                "warning": False,
            }
        )

    inactive_cutoff = today - timedelta(days=120)
    inactive_count = sum(
        1 for member in members if member.last_visit_date is None or member.last_visit_date <= inactive_cutoff
    )
    no_visit_count = sum(1 for member in members if member.last_visit_date is None)
    rows.append(
        {
            "label": "Not visited for 120+ days",
            "count": inactive_count,
            "cutoff": inactive_cutoff,
            "warning": True,
        }
    )

    max_count = max([int(row["count"]) for row in rows] + [1])
    chart_rows = []
    for row in rows:
        count = int(row["count"])
        percent_of_total = (count / total * 100.0) if total else 0.0
        width = max(2, round(count / max_count * 100.0)) if count else 0
        warning_class = " warning" if bool(row["warning"]) else ""
        chart_rows.append(
            "<div class=\"bar-row\">"
            f"<div class=\"bar-label\">{_esc(row['label'])}</div>"
            "<div class=\"bar-track\">"
            f"<div class=\"bar-fill{warning_class}\" style=\"width: {width}%\">{count}</div>"
            "</div>"
            f"<div class=\"bar-value\">{percent_of_total:.1f}%</div>"
            "</div>"
        )

    table_rows = []
    for row in rows:
        count = int(row["count"])
        percent_of_total = (count / total * 100.0) if total else 0.0
        table_rows.append(
            "<tr>"
            f"<td>{_esc(row['label'])}</td>"
            f"<td>{count}</td>"
            f"<td>{percent_of_total:.1f}%</td>"
            f"<td>{_esc(_date(row['cutoff']))}</td>"
            "</tr>"
        )

    body = f"""
<section>
  <div class="inline" style="justify-content: space-between;">
    <h2>Visit Report</h2>
    <a class="button secondary" href="{_href(request, '/admin/members')}">View members</a>
  </div>
  <p class="muted">Based on {total} current members only. Ex-members are excluded. Report date: {_date(today)}.</p>
  <div class="bar-chart">
    {''.join(chart_rows)}
  </div>
</section>
<section>
  <h2>Counts</h2>
  <table>
    <thead><tr><th>Measure</th><th>Members</th><th>Share</th><th>Cut-off date</th></tr></thead>
    <tbody>{''.join(table_rows)}</tbody>
  </table>
  <p class="muted">The visit windows are cumulative and exclude the cut-off date. The 120+ days group includes members whose last visit is on or before the cut-off date, plus members with no recorded last visit. No recorded last visit: {no_visit_count}.</p>
</section>"""
    return _layout(request, "Visit Report", body)


@router.get("/admin/members", response_class=HTMLResponse)
def members(
    request: Request,
    q: str = "",
    session: Session = Depends(get_session),
    _: None = Depends(require_admin),
):
    search = str(q or "").strip()
    rows: list[Member] = []
    if search:
        query = select(Member)
        pattern = f"%{search}%"
        query = query.where(
            or_(
                Member.first_name.ilike(pattern),
                Member.last_name.ilike(pattern),
                Member.email.ilike(pattern),
                Member.phone_e164.ilike(pattern),
                Member.mobile_raw.ilike(pattern),
                Member.external_member_id.ilike(pattern),
                Member.membership_status.ilike(pattern),
            )
        )
        rows = session.execute(query.order_by(desc(Member.id)).limit(500)).scalars().all()
    total = session.scalar(select(func.count()).select_from(Member)) or 0
    table = []
    for member in rows:
        active = active_conversation_for_member(session, int(member.id))
        active_text = f'<span class="pill">{_esc(active.flow_key)}</span>' if active else ""
        member_url = _href(request, f"/admin/members/{member.id}")
        table.append(
            "<tr>"
            f"<td><a href=\"{member_url}\">{_esc(member_name(member))}</a><br><span class=\"muted\">{_esc(_mobile_label(member))}</span></td>"
            f"<td>{_esc(member.email or '')}</td>"
            f"<td><span class=\"pill\">{_esc(_member_status_label(member))}</span></td>"
            f"<td>{_esc(_date(member.join_date))}</td>"
            f"<td>{_esc(_date(member.last_visit_date))}</td>"
            f"<td>{_esc(_date(member.expiry_date))}</td>"
            f"<td>{active_text}</td>"
            "</tr>"
        )
    token_input = (
        '<input type="hidden" name="token" value="' + _esc(request.query_params.get("token")) + '">'
        if request.query_params.get("token")
        else ""
    )
    clear_link = f'<a class="button secondary" href="{_href(request, "/admin/members")}">Clear</a>' if search else ""
    result_text = (
        f'{len(rows)} shown for "{_esc(search)}". {total} members in MemberSense.'
        if search
        else f"Search by name, email, mobile, member number, or status. {total} members in MemberSense."
    )
    empty_text = "No members matched your search." if search else "Enter a search above to look up members."
    create_token_input = _token_input(request)
    body = f"""
<section>
  <div class="inline" style="justify-content: space-between;">
    <h2>Members</h2>
    <a class="button secondary" href="{_href(request, '/admin/import')}">Import CSV</a>
  </div>
  <form method="get" action="/admin/members" class="inline" style="margin-bottom: 12px;">
    {token_input}
    <label><span>Look up member</span><input name="q" value="{_esc(search)}" placeholder="Name, email, mobile, or status"></label>
    <button type="submit">Search</button>
    {clear_link}
  </form>
  <p class="muted">{result_text}</p>
  <table>
    <thead>
      <tr><th>Member</th><th>Email</th><th>Status</th><th>Joined</th><th>Last visit</th><th>Expiry</th><th>Active survey</th></tr>
    </thead>
    <tbody>{''.join(table) or f'<tr><td colspan="7">{_esc(empty_text)}</td></tr>'}</tbody>
  </table>
</section>
<section>
  <h2>Create New Member</h2>
  <p class="muted">Create a member manually when they are not found in search. Enter either a member number or a mobile number.</p>
  <form method="post" action="{_post_action(request, '/admin/members')}" class="stack">
    {create_token_input}
    <div class="grid">
      <label><span>First name</span><input name="first_name" autocomplete="given-name"></label>
      <label><span>Surname</span><input name="last_name" autocomplete="family-name"></label>
      <label><span>Email</span><input name="email" type="email" autocomplete="email"></label>
      <label><span>Mobile</span><input name="phone" autocomplete="tel"></label>
      <label><span>Member number</span><input name="external_member_id"></label>
      <label><span>Status</span><select name="membership_status"><option value="current">Current</option><option value="expired">Expired</option><option value="account onhold">Account On Hold</option></select></label>
      <label><span>Joining date</span><input name="join_date" type="date"></label>
      <label><span>Last visit</span><input name="last_visit_date" type="date"></label>
      <label><span>Expiry date</span><input name="expiry_date" type="date"></label>
    </div>
    <button type="submit">Create member</button>
  </form>
</section>"""
    return _layout(request, "Members", body)


@router.get("/admin/members/{member_id}", response_class=HTMLResponse)
def member_detail(
    request: Request,
    member_id: int,
    visit_survey_sent: int | None = None,
    visit_recorded: int | None = None,
    session: Session = Depends(get_session),
    _: None = Depends(require_admin),
):
    member = session.get(Member, int(member_id))
    if member is None:
        raise HTTPException(status_code=404, detail="Member not found")
    conversations = (
        session.execute(
            select(Conversation)
            .where(Conversation.member_id == int(member.id))
            .order_by(desc(Conversation.id))
            .limit(20)
        )
        .scalars()
        .all()
    )
    tasks = (
        session.execute(
            select(StaffTask)
            .where(StaffTask.member_id == int(member.id))
            .order_by(desc(StaffTask.id))
            .limit(20)
        )
        .scalars()
        .all()
    )
    conversation_rows = []
    for row in conversations:
        conversation_rows.append(
            "<tr>"
            f"<td><a href=\"{_href(request, f'/admin/surveys/{row.id}')}\">{_esc(_survey_label(row, session))}</a></td>"
            f"<td><span class=\"pill\">{_esc(row.status)}</span></td>"
            f"<td>{_esc(_survey_progress(row, session))}</td>"
            f"<td>{_esc(_datetime(row.created_at))}</td>"
            f"<td><a class=\"button secondary\" href=\"{_href(request, f'/admin/surveys/{row.id}')}\">Open survey</a></td>"
            "</tr>"
        )
    task_rows = []
    for row in tasks:
        priority_class = "priority-high" if row.priority == "high" else ""
        task_rows.append(
            "<tr>"
            f"<td class=\"{priority_class}\">{_esc(row.priority)}</td>"
            f"<td>{_esc(row.title)}<br><span class=\"muted\">{_esc(row.detail or '')}</span></td>"
            f"<td><span class=\"pill\">{_esc(row.status)}</span></td>"
            "</tr>"
        )
    notice_parts = []
    if visit_survey_sent is not None:
        notice_parts.append("Visit recorded and visit survey link sent.")
    if visit_recorded is not None:
        notice_parts.append("Visit recorded.")
    notice_html = f'<p><span class="pill">{_esc(" ".join(notice_parts))}</span></p>' if notice_parts else ""
    body = f"""
<section>
  <div class="inline" style="justify-content: space-between;">
    <h2>{_esc(member_name(member))}</h2>
    <a class="button secondary" href="{_href(request, '/admin/members')}">Back to members</a>
  </div>
  {notice_html}
  <div class="grid">
    <div><strong>Member number</strong><br>{_esc(member.external_member_id or '')}</div>
    <div><strong>Mobile</strong><br>{_esc(_mobile_label(member))}</div>
    <div><strong>Email</strong><br>{_esc(member.email or '')}</div>
    <div><strong>Status</strong><br><span class="pill">{_esc(_member_status_label(member))}</span></div>
    <div><strong>Joined</strong><br>{_esc(_date(member.join_date))}</div>
    <div><strong>Last visit</strong><br>{_esc(_date(member.last_visit_date))}</div>
    <div><strong>Expiry</strong><br>{_esc(_date(member.expiry_date))}</div>
    <div><strong>Source</strong><br>{_esc(member.source or '')}</div>
  </div>
  <h3>Visit Survey</h3>
  {_visit_survey_form(request, member)}
  <h3>Send Survey</h3>
  {_survey_action(request, member, session=session)}
</section>
<section>
  <h2>Surveys</h2>
  <table>
    <thead><tr><th>Survey</th><th>Status</th><th>Answers</th><th>Started</th><th>Action</th></tr></thead>
    <tbody>{''.join(conversation_rows) or '<tr><td colspan="5">No surveys yet.</td></tr>'}</tbody>
  </table>
</section>
<section>
  <h2>Tasks</h2>
  <table>
    <thead><tr><th>Priority</th><th>Task</th><th>Status</th></tr></thead>
    <tbody>{''.join(task_rows) or '<tr><td colspan="3">No tasks yet.</td></tr>'}</tbody>
  </table>
</section>"""
    return _layout(request, member_name(member), body)


@router.post("/admin/members")
def create_member(
    request: Request,
    phone: str = Form(""),
    external_member_id: str = Form(""),
    first_name: str = Form(""),
    last_name: str = Form(""),
    email: str = Form(""),
    membership_status: str = Form("current"),
    join_date: str = Form(""),
    last_visit_date: str = Form(""),
    expiry_date: str = Form(""),
    session: Session = Depends(get_session),
    _: None = Depends(require_admin),
):
    if not str(phone or "").strip() and not str(external_member_id or "").strip():
        raise HTTPException(status_code=400, detail="Enter a member number or mobile number")
    member, _created = upsert_member(
        session,
        phone=phone or None,
        external_member_id=external_member_id or None,
        first_name=first_name,
        last_name=last_name,
        email=email,
        mobile_raw=phone or None,
        membership_status=membership_status,
        join_date=join_date or None,
        last_visit_date=last_visit_date or None,
        expiry_date=expiry_date or None,
        source="admin",
    )
    session.commit()
    return _redirect(request, f"/admin/members/{member.id}")


@router.post("/admin/members/{member_id}/start")
def start_member_survey(
    request: Request,
    member_id: int,
    flow_key: str = Form(...),
    session: Session = Depends(get_session),
    _: None = Depends(require_admin),
):
    member = session.get(Member, int(member_id))
    if member is None:
        raise HTTPException(status_code=404, detail="Member not found")
    if not member_contact_phone(member):
        raise HTTPException(status_code=400, detail="Member does not have a mobile number for SMS")
    try:
        _start_and_send_survey_link(request, session, member, flow_key)
    except Exception as exc:
        return _redirect(request, _sms_error_path(exc))
    return _redirect(request, "/admin/members")


@router.post("/admin/members/{member_id}/visit-survey")
def confirm_visit_and_send_survey(
    request: Request,
    member_id: int,
    session: Session = Depends(get_session),
    _: None = Depends(require_admin),
):
    member = session.get(Member, int(member_id))
    if member is None:
        raise HTTPException(status_code=404, detail="Member not found")
    member.last_visit_date = date.today()
    session.add(member)
    session.commit()
    if not member_contact_phone(member):
        conversation = start_conversation(session, member, "visit", send_intro=False)
        ensure_app_link_token(session, conversation)
        return _redirect(request, f"/admin/surveys/{conversation.id}?link_created=1&visit_recorded=1")
    try:
        _start_and_send_survey_link(request, session, member, "visit")
    except Exception as exc:
        return _redirect(request, _sms_error_path(exc))
    return _redirect(request, f"/admin/members/{member.id}?visit_survey_sent=1")


@router.post("/admin/members/{member_id}/app-link")
def create_member_app_link(
    request: Request,
    member_id: int,
    flow_key: str = Form(...),
    session: Session = Depends(get_session),
    _: None = Depends(require_admin),
):
    member = session.get(Member, int(member_id))
    if member is None:
        raise HTTPException(status_code=404, detail="Member not found")
    conversation = start_conversation(session, member, flow_key, send_intro=False)
    ensure_app_link_token(session, conversation)
    return _redirect(request, f"/admin/surveys/{conversation.id}?link_created=1")


@router.get("/admin/inactive", response_class=HTMLResponse)
def inactive(
    request: Request,
    tab: str = "new",
    mobile_filter: str = "any",
    email_filter: str = "any",
    sent_filter: str = "any",
    new_min_days: int = 0,
    new_max_days: int = 7,
    new_limit: int = 200,
    visit_min_days: int = 14,
    visit_max_days: int = 21,
    visit_limit: int = 200,
    expired_min_days: int = 0,
    expired_max_days: int = 30,
    expired_limit: int = 200,
    sent_new: int | None = None,
    sent_inactive: int | None = None,
    sent_expired: int | None = None,
    failed_new: int | None = None,
    failed_inactive: int | None = None,
    failed_expired: int | None = None,
    error: str = "",
    session: Session = Depends(get_session),
    _: None = Depends(require_admin),
):
    new_min_days, new_max_days = _coerce_range(new_min_days, new_max_days)
    visit_min_days, visit_max_days = _coerce_range(visit_min_days, visit_max_days)
    expired_min_days, expired_max_days = _coerce_range(expired_min_days, expired_max_days)
    mobile_filter = _filter_choice(mobile_filter, {"any", "present", "missing"})
    email_filter = _filter_choice(email_filter, {"any", "present", "missing"})
    sent_filter = _filter_choice(sent_filter, {"any", "not_sent", "sent"})
    new_limit = max(min(int(new_limit or 200), 500), 1)
    visit_limit = max(min(int(visit_limit or 200), 500), 1)
    expired_limit = max(min(int(expired_limit or 200), 500), 1)

    tab_key = str(tab or "new").strip().lower().replace("-", "_")
    selected_tab = {
        "new": "new",
        "new_member": "new",
        "new_members": "new",
        "inactive": "inactive",
        "not_training": "inactive",
        "expired": "expired",
        "expired_members": "expired",
        "exit": "expired",
    }.get(tab_key, "new")

    new_rows: list[Member] = []
    visit_rows: list[Member] = []
    expired_rows: list[Member] = []
    if selected_tab == "new":
        new_rows = _apply_list_filters(
            session,
            new_member_candidates(session, min_days=new_min_days, max_days=new_max_days, limit=_filter_fetch_limit(new_limit)),
            flow_key="new_member",
            mobile_filter=mobile_filter,
            email_filter=email_filter,
            sent_filter=sent_filter,
        )[:new_limit]
    elif selected_tab == "inactive":
        visit_rows = _apply_list_filters(
            session,
            last_visit_range_candidates(
                session,
                min_days=visit_min_days,
                max_days=visit_max_days,
                limit=_filter_fetch_limit(visit_limit),
            ),
            flow_key="inactive",
            mobile_filter=mobile_filter,
            email_filter=email_filter,
            sent_filter=sent_filter,
        )[:visit_limit]
    elif selected_tab == "expired":
        expired_rows = _apply_list_filters(
            session,
            expired_member_candidates(
                session,
                min_days=expired_min_days,
                max_days=expired_max_days,
                limit=_filter_fetch_limit(expired_limit),
            ),
            flow_key="exit",
            mobile_filter=mobile_filter,
            email_filter=email_filter,
            sent_filter=sent_filter,
        )[:expired_limit]

    token_input = _token_input(request)
    notices = []
    if sent_new is not None:
        notices.append(f"New member surveys sent: {int(sent_new)}.")
    if sent_inactive is not None:
        notices.append(f"Inactive surveys sent: {int(sent_inactive)}.")
    if sent_expired is not None:
        notices.append(f"Exit surveys sent: {int(sent_expired)}.")
    if failed_new is not None:
        notices.append(f"New member survey failures: {int(failed_new)}.")
    if failed_inactive is not None:
        notices.append(f"Inactive survey failures: {int(failed_inactive)}.")
    if failed_expired is not None:
        notices.append(f"Exit survey failures: {int(failed_expired)}.")
    if error:
        notices.append(f"SMS error: {error}")
    notice_class = "error" if any(value is not None for value in [failed_new, failed_inactive, failed_expired]) or error else ""
    notice_attr = f' class="{notice_class}"' if notice_class else ""
    notice_html = (
        f'<section><h2>Batch Result</h2><p{notice_attr}>{" ".join(_esc(notice) for notice in notices)}</p></section>'
        if notices
        else ""
    )

    base_params = {
        "new_min_days": new_min_days,
        "new_max_days": new_max_days,
        "new_limit": new_limit,
        "visit_min_days": visit_min_days,
        "visit_max_days": visit_max_days,
        "visit_limit": visit_limit,
        "expired_min_days": expired_min_days,
        "expired_max_days": expired_max_days,
        "expired_limit": expired_limit,
        "mobile_filter": mobile_filter,
        "email_filter": email_filter,
        "sent_filter": sent_filter,
    }
    tabs = []
    for key, label in (("new", "New Members"), ("inactive", "Not Training"), ("expired", "Expired Members")):
        params = dict(base_params)
        params["tab"] = key
        active = " active" if key == selected_tab else ""
        tabs.append(f'<a class="tab{active}" href="{_href(request, "/admin/inactive?" + urlencode(params))}">{label}</a>')
    tabs_html = '<div class="tabs">' + "".join(tabs) + "</div>"

    if selected_tab == "new":
        filter_fields = _list_filter_fields(mobile_filter, email_filter, sent_filter)
        hidden_filters = _hidden_list_filters(mobile_filter, email_filter, sent_filter)
        active_section = f"""
<section>
  <div class="inline" style="justify-content: space-between;">
    <h2>New Members</h2>
    <form method="post" action="{_post_action(request, '/admin/segments/new/send')}" class="inline">
      <input type="hidden" name="min_days" value="{new_min_days}">
      <input type="hidden" name="max_days" value="{new_max_days}">
      {hidden_filters}
      <label><span>Maximum to send</span><input name="limit" type="number" value="{len(new_rows) or 1}" min="1" max="500"></label>
      <button type="submit" class="secondary">Send new member surveys</button>
    </form>
  </div>
  <form method="get" action="/admin/inactive" class="inline">
    {token_input}
    <input type="hidden" name="tab" value="new">
    <label><span>Member for at least</span><input name="new_min_days" type="number" value="{new_min_days}" min="0"> days</label>
    <label><span>Member for no more than</span><input name="new_max_days" type="number" value="{new_max_days}" min="0"> days</label>
    <label><span>Show up to</span><input name="new_limit" type="number" value="{new_limit}" min="1" max="500"></label>
    {filter_fields}
    <input type="hidden" name="visit_min_days" value="{visit_min_days}">
    <input type="hidden" name="visit_max_days" value="{visit_max_days}">
    <input type="hidden" name="visit_limit" value="{visit_limit}">
    <input type="hidden" name="expired_min_days" value="{expired_min_days}">
    <input type="hidden" name="expired_max_days" value="{expired_max_days}">
    <input type="hidden" name="expired_limit" value="{expired_limit}">
    <button type="submit">Refresh</button>
  </form>
  <table>
    <thead><tr><th>Member</th><th>Status</th><th>Joined</th><th>Age</th><th>Survey</th><th>Action</th></tr></thead>
    <tbody>{_segment_table(request, session, new_rows, date_attr='join_date', empty_text='No new member candidates found.', default_flow='new_member')}</tbody>
  </table>
</section>"""
    elif selected_tab == "inactive":
        filter_fields = _list_filter_fields(mobile_filter, email_filter, sent_filter)
        hidden_filters = _hidden_list_filters(mobile_filter, email_filter, sent_filter)
        active_section = f"""
<section>
  <div class="inline" style="justify-content: space-between;">
    <h2>Not Training</h2>
    <form method="post" action="{_post_action(request, '/admin/segments/inactive/send')}" class="inline">
      <input type="hidden" name="min_days" value="{visit_min_days}">
      <input type="hidden" name="max_days" value="{visit_max_days}">
      {hidden_filters}
      <label><span>Maximum to send</span><input name="limit" type="number" value="{len(visit_rows) or 1}" min="1" max="500"></label>
      <button type="submit" class="secondary">Send inactive surveys</button>
    </form>
  </div>
  <form method="get" action="/admin/inactive" class="inline">
    {token_input}
    <input type="hidden" name="tab" value="inactive">
    <input type="hidden" name="new_min_days" value="{new_min_days}">
    <input type="hidden" name="new_max_days" value="{new_max_days}">
    <input type="hidden" name="new_limit" value="{new_limit}">
    <label><span>Last trained at least</span><input name="visit_min_days" type="number" value="{visit_min_days}" min="0"> days ago</label>
    <label><span>Last trained no more than</span><input name="visit_max_days" type="number" value="{visit_max_days}" min="0"> days ago</label>
    <label><span>Show up to</span><input name="visit_limit" type="number" value="{visit_limit}" min="1" max="500"></label>
    {filter_fields}
    <input type="hidden" name="expired_min_days" value="{expired_min_days}">
    <input type="hidden" name="expired_max_days" value="{expired_max_days}">
    <input type="hidden" name="expired_limit" value="{expired_limit}">
    <button type="submit">Refresh</button>
  </form>
  <p class="muted">Use this for ranges like 14 to 21 days since last visit, so the team can target members at the right moment.</p>
  <table>
    <thead><tr><th>Member</th><th>Status</th><th>Last visit</th><th>Age</th><th>Survey</th><th>Action</th></tr></thead>
    <tbody>{_segment_table(request, session, visit_rows, date_attr='last_visit_date', empty_text='No not-training candidates found.', default_flow='inactive')}</tbody>
  </table>
</section>"""
    else:
        filter_fields = _list_filter_fields(mobile_filter, email_filter, sent_filter)
        hidden_filters = _hidden_list_filters(mobile_filter, email_filter, sent_filter)
        active_section = f"""
<section>
  <div class="inline" style="justify-content: space-between;">
    <h2>Expired Members</h2>
    <form method="post" action="{_post_action(request, '/admin/segments/expired/send')}" class="inline">
      <input type="hidden" name="min_days" value="{expired_min_days}">
      <input type="hidden" name="max_days" value="{expired_max_days}">
      {hidden_filters}
      <label><span>Maximum to send</span><input name="limit" type="number" value="{len(expired_rows) or 1}" min="1" max="500"></label>
      <button type="submit" class="secondary">Send exit surveys</button>
    </form>
  </div>
  <form method="get" action="/admin/inactive" class="inline">
    {token_input}
    <input type="hidden" name="tab" value="expired">
    <input type="hidden" name="new_min_days" value="{new_min_days}">
    <input type="hidden" name="new_max_days" value="{new_max_days}">
    <input type="hidden" name="new_limit" value="{new_limit}">
    <input type="hidden" name="visit_min_days" value="{visit_min_days}">
    <input type="hidden" name="visit_max_days" value="{visit_max_days}">
    <input type="hidden" name="visit_limit" value="{visit_limit}">
    <label><span>Expired at least</span><input name="expired_min_days" type="number" value="{expired_min_days}" min="0"> days ago</label>
    <label><span>Expired no more than</span><input name="expired_max_days" type="number" value="{expired_max_days}" min="0"> days ago</label>
    <label><span>Show up to</span><input name="expired_limit" type="number" value="{expired_limit}" min="1" max="500"></label>
    {filter_fields}
    <button type="submit">Refresh</button>
  </form>
  <table>
    <thead><tr><th>Member</th><th>Status</th><th>Expiry</th><th>Age</th><th>Survey</th><th>Action</th></tr></thead>
    <tbody>{_segment_table(request, session, expired_rows, date_attr='expiry_date', empty_text='No expired member candidates found.', default_flow='exit')}</tbody>
  </table>
</section>"""

    body = f"""
<section>
  <h2>Member Lists</h2>
  <p class="muted">Create practical SMS survey-link batches from join date, last visit date, or membership expiry date. Members stay visible after a survey is sent and show as completed for that survey. Batch sends skip members with no mobile, members already marked completed for that survey, and members who already have an active survey.</p>
  {tabs_html}
</section>
{notice_html}
{active_section}"""
    return _layout(request, "Member Lists", body)


@router.post("/admin/segments/new/send")
def send_new_member_surveys(
    request: Request,
    min_days: int = Form(0),
    max_days: int = Form(7),
    limit: int = Form(25),
    mobile_filter: str = Form("any"),
    email_filter: str = Form("any"),
    sent_filter: str = Form("any"),
    session: Session = Depends(get_session),
    _: None = Depends(require_admin),
):
    min_days, max_days = _coerce_range(min_days, max_days)
    mobile_filter = _filter_choice(mobile_filter, {"any", "present", "missing"})
    email_filter = _filter_choice(email_filter, {"any", "present", "missing"})
    sent_filter = _filter_choice(sent_filter, {"any", "not_sent", "sent"})
    requested = max(min(int(limit or 25), 500), 1)
    candidate_limit = max(min(requested * 3, 1500), requested)
    members = _apply_list_filters(
        session,
        new_member_candidates(session, min_days=min_days, max_days=max_days, limit=candidate_limit),
        flow_key="new_member",
        mobile_filter=mobile_filter,
        email_filter=email_filter,
        sent_filter=sent_filter,
    )
    sent, failed, error = _send_segment(request, session, members, "new_member", limit=requested)
    params = {
        "tab": "new",
        "new_min_days": min_days,
        "new_max_days": max_days,
        "mobile_filter": mobile_filter,
        "email_filter": email_filter,
        "sent_filter": sent_filter,
        "sent_new": sent,
    }
    if failed:
        params["failed_new"] = failed
    if error:
        params["error"] = error
    return _redirect(
        request,
        "/admin/inactive?" + urlencode(params),
    )


@router.post("/admin/segments/inactive/send")
def send_inactive_surveys(
    request: Request,
    min_days: int = Form(14),
    max_days: int = Form(21),
    limit: int = Form(25),
    mobile_filter: str = Form("any"),
    email_filter: str = Form("any"),
    sent_filter: str = Form("any"),
    session: Session = Depends(get_session),
    _: None = Depends(require_admin),
):
    min_days, max_days = _coerce_range(min_days, max_days)
    mobile_filter = _filter_choice(mobile_filter, {"any", "present", "missing"})
    email_filter = _filter_choice(email_filter, {"any", "present", "missing"})
    sent_filter = _filter_choice(sent_filter, {"any", "not_sent", "sent"})
    requested = max(min(int(limit or 25), 500), 1)
    candidate_limit = max(min(requested * 3, 1500), requested)
    members = _apply_list_filters(
        session,
        last_visit_range_candidates(session, min_days=min_days, max_days=max_days, limit=candidate_limit),
        flow_key="inactive",
        mobile_filter=mobile_filter,
        email_filter=email_filter,
        sent_filter=sent_filter,
    )
    sent, failed, error = _send_segment(request, session, members, "inactive", limit=requested)
    params = {
        "tab": "inactive",
        "visit_min_days": min_days,
        "visit_max_days": max_days,
        "mobile_filter": mobile_filter,
        "email_filter": email_filter,
        "sent_filter": sent_filter,
        "sent_inactive": sent,
    }
    if failed:
        params["failed_inactive"] = failed
    if error:
        params["error"] = error
    return _redirect(
        request,
        "/admin/inactive?" + urlencode(params),
    )


@router.post("/admin/segments/expired/send")
def send_expired_surveys(
    request: Request,
    min_days: int = Form(0),
    max_days: int = Form(30),
    limit: int = Form(25),
    mobile_filter: str = Form("any"),
    email_filter: str = Form("any"),
    sent_filter: str = Form("any"),
    session: Session = Depends(get_session),
    _: None = Depends(require_admin),
):
    min_days, max_days = _coerce_range(min_days, max_days)
    mobile_filter = _filter_choice(mobile_filter, {"any", "present", "missing"})
    email_filter = _filter_choice(email_filter, {"any", "present", "missing"})
    sent_filter = _filter_choice(sent_filter, {"any", "not_sent", "sent"})
    requested = max(min(int(limit or 25), 500), 1)
    candidate_limit = max(min(requested * 3, 1500), requested)
    members = _apply_list_filters(
        session,
        expired_member_candidates(session, min_days=min_days, max_days=max_days, limit=candidate_limit),
        flow_key="exit",
        mobile_filter=mobile_filter,
        email_filter=email_filter,
        sent_filter=sent_filter,
    )
    sent, failed, error = _send_segment(request, session, members, "exit", limit=requested)
    params = {
        "tab": "expired",
        "expired_min_days": min_days,
        "expired_max_days": max_days,
        "mobile_filter": mobile_filter,
        "email_filter": email_filter,
        "sent_filter": sent_filter,
        "sent_expired": sent,
    }
    if failed:
        params["failed_expired"] = failed
    if error:
        params["error"] = error
    return _redirect(
        request,
        "/admin/inactive?" + urlencode(params),
    )


@router.get("/admin/import", response_class=HTMLResponse)
def import_form(request: Request, _: None = Depends(require_admin)):
    body = f"""
<section>
  <h2>Import Members</h2>
  <p class="muted">CSV columns accepted: phone, mobile, mobile number, phone_e164, first_name, first name, surname, email, email address, status, joining date, last visit, expiry date, cancellation date.</p>
  <form method="post" action="{_post_action(request, '/admin/import')}" enctype="multipart/form-data" class="stack">
    <label><span>CSV file</span><input name="file" type="file" accept=".csv,text/csv" required></label>
    <button type="submit">Import</button>
  </form>
</section>
<section>
  <h2>Import Expired Members</h2>
  <p class="muted">Use this for a cancellation or expired-member export. Only members whose expiry date is less than 60 days ago are imported. Older, future, or missing expiry dates are skipped.</p>
  <form method="post" action="{_post_action(request, '/admin/import/expired')}" enctype="multipart/form-data" class="stack">
    <label><span>Expired members CSV file</span><input name="file" type="file" accept=".csv,text/csv" required></label>
    <button type="submit" class="secondary">Import expired members</button>
  </form>
</section>"""
    return _layout(request, "Import", body)


def _import_complete(request: Request, batch, title: str = "Import Complete") -> HTMLResponse:
    errors = "".join(f"<li>Row {_esc(err.get('row'))}: {_esc(err.get('error'))}</li>" for err in (batch.errors or []))
    body = f"""
<section>
  <h2>{_esc(title)}</h2>
  <div class="grid">
    <div class="metric"><strong>{batch.rows_seen}</strong><span>Rows seen</span></div>
    <div class="metric"><strong>{batch.rows_created}</strong><span>Created</span></div>
    <div class="metric"><strong>{batch.rows_updated}</strong><span>Updated</span></div>
    <div class="metric"><strong>{getattr(batch, 'rows_skipped', 0)}</strong><span>Skipped</span></div>
    <div class="metric"><strong>{len(batch.errors or [])}</strong><span>Errors</span></div>
  </div>
  {'<h3>Errors</h3><ul>' + errors + '</ul>' if errors else ''}
  <p class="inline">
    <a class="button" href="{_href(request, '/admin/members')}">View members</a>
    <a class="button secondary" href="{_href(request, '/admin/inactive')}">View member lists</a>
  </p>
</section>"""
    return _layout(request, title, body)


@router.post("/admin/import", response_class=HTMLResponse)
async def import_upload(
    request: Request,
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
    _: None = Depends(require_admin),
):
    raw = await file.read()
    batch = import_members_csv(session, raw_csv=raw, filename=file.filename, source="csv")
    return _import_complete(request, batch)


@router.post("/admin/import/expired", response_class=HTMLResponse)
async def import_expired_upload(
    request: Request,
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
    _: None = Depends(require_admin),
):
    raw = await file.read()
    batch = import_members_csv(
        session,
        raw_csv=raw,
        filename=file.filename,
        source="expired_csv",
        default_status="expired",
        force_status="expired",
        max_expired_days=60,
    )
    return _import_complete(request, batch, "Expired Member Import Complete")


@router.get("/admin/tasks", response_class=HTMLResponse)
def tasks(request: Request, session: Session = Depends(get_session), _: None = Depends(require_admin)):
    rows = (
        session.execute(select(StaffTask).where(StaffTask.status == "open").order_by(desc(StaffTask.id)).limit(200))
        .scalars()
        .all()
    )
    table = []
    for task in rows:
        member = session.get(Member, task.member_id)
        priority_class = "priority-high" if task.priority == "high" else ""
        conversation = (
            f'<a href="{_href(request, f"/admin/surveys/{task.conversation_id}")}">Survey</a>'
            if task.conversation_id
            else ""
        )
        table.append(
            "<tr>"
            f"<td class=\"{priority_class}\">{_esc(task.priority)}</td>"
            f"<td>{_esc(task.title)}<br><span class=\"muted\">{_esc(task.detail or '')}</span></td>"
            f"<td>{_esc(member_name(member))}</td>"
            f"<td>{conversation}</td>"
            f"<td><form method=\"post\" action=\"{_post_action(request, f'/admin/tasks/{task.id}/done')}\"><button type=\"submit\">Done</button></form></td>"
            "</tr>"
        )
    body = f"""
<section>
  <h2>Open Tasks</h2>
  <table>
    <thead><tr><th>Priority</th><th>Task</th><th>Member</th><th>Source</th><th>Action</th></tr></thead>
    <tbody>{''.join(table) or '<tr><td colspan="5">No open tasks.</td></tr>'}</tbody>
  </table>
</section>"""
    return _layout(request, "Tasks", body)


@router.post("/admin/tasks/{task_id}/done")
def complete_task(
    request: Request,
    task_id: int,
    session: Session = Depends(get_session),
    _: None = Depends(require_admin),
):
    mark_task_done(session, task_id)
    return _redirect(request, "/admin/tasks")


def _survey_config_notice(saved: int | None, generated: int | None, refreshed: int | None, error: str) -> str:
    parts = []
    if saved is not None:
        parts.append("Survey setup saved.")
    if generated is not None:
        parts.append(
            "Avatar generation queued. It will continue in the background; "
            "refresh this page after a few minutes to see the completed video."
        )
    if refreshed is not None:
        parts.append("Avatar status refreshed.")
    if error:
        parts.append(str(error))
    if not parts:
        return ""
    notice_class = "error" if error else "pill"
    return f'<p><span class="{notice_class}">{_esc(" ".join(parts))}</span></p>'


def _survey_config_questions_from_form(form, flow_key: str) -> list[dict[str, str]]:
    flow = flow_for_key(flow_key)
    if is_outcome_locked_flow(flow.key):
        return [
            {
                "key": question.key,
                "text": question.text,
                "helper": question.helper,
                "options": "\n".join(question.options),
            }
            for question in flow.questions
        ]
    questions = []
    for question in flow.questions:
        questions.append(
            {
                "key": question.key,
                "text": str(form.get(f"question_text_{question.key}") or "").strip(),
                "helper": str(form.get(f"question_helper_{question.key}") or "").strip(),
                "options": str(form.get(f"question_options_{question.key}") or "").strip(),
            }
        )
    return questions


def _survey_config_path(flow_key: str, **params: object) -> str:
    query = {key: value for key, value in params.items() if value is not None and str(value) != ""}
    suffix = f"?{urlencode(query)}" if query else ""
    return f"/admin/survey-config/{flow_key}{suffix}"


@router.get("/admin/survey-config", response_class=HTMLResponse)
def survey_config_index(
    request: Request,
    session: Session = Depends(get_session),
    _: None = Depends(require_admin),
):
    rows = []
    for key in SURVEY_FLOWS:
        flow = effective_survey_flow(session, key)
        avatar_state = str(flow.avatar_status or "").strip()
        if flow.avatar_video_url:
            avatar_state = avatar_state or "video ready"
        else:
            avatar_state = avatar_state or "not configured"
        rows.append(
            "<tr>"
            f"<td>{_esc(flow.label)}<br><span class=\"muted\">{_esc(key)}</span></td>"
            f"<td>{len(flow.questions)}</td>"
            f"<td><span class=\"pill\">{_esc(avatar_state)}</span></td>"
            f"<td><a class=\"button secondary\" href=\"{_href(request, f'/admin/survey-config/{key}')}\">Configure</a></td>"
            "</tr>"
        )
    body = f"""
<section>
  <h2>Survey Setup</h2>
  <p class="muted">Edit survey text, intro and completion messages where configurable. Outcome-driving question sets are locked when classification depends on exact answer meanings. Avatar videos use the same Azure avatar defaults as HealthSense when generation is enabled.</p>
  <table>
    <thead><tr><th>Survey</th><th>Questions</th><th>Avatar</th><th>Action</th></tr></thead>
    <tbody>{''.join(rows)}</tbody>
  </table>
</section>"""
    return _layout(request, "Survey Setup", body)


@router.get("/admin/survey-config/{flow_key}", response_class=HTMLResponse)
def survey_config_edit(
    request: Request,
    flow_key: str,
    saved: int | None = None,
    generated: int | None = None,
    refreshed: int | None = None,
    error: str = "",
    session: Session = Depends(get_session),
    _: None = Depends(require_admin),
):
    if str(flow_key or "").strip().lower() not in SURVEY_FLOWS:
        raise HTTPException(status_code=404, detail="Survey setup not found")
    payload = editable_survey_payload(session, flow_key)
    flow = effective_survey_flow(session, flow_key)
    defaults = survey_avatar_defaults()
    avatar_runtime = survey_avatar_runtime_config()
    notice_html = _survey_config_notice(saved, generated, refreshed, error)
    question_fields = []
    questions_locked = is_outcome_locked_flow(flow.key)
    for index, question in enumerate(flow.questions, start=1):
        options_text = "\n".join(question.options)
        readonly_attr = " readonly" if questions_locked else ""
        helper_html = f'<p class="muted">{_esc(question.helper)}</p>' if question.helper else ""
        question_fields.append(
            f"""
<div class="stack" style="border-top: 1px solid var(--line); padding-top: 12px;">
  <h3>Question {index}</h3>
  <p class="muted">Key: {_esc(question.key)}</p>
  {helper_html}
  <label><span>Question text</span><textarea name="question_text_{_esc(question.key)}"{readonly_attr}>{_esc(question.text)}</textarea></label>
  <label><span>Answer options, one per line</span><textarea name="question_options_{_esc(question.key)}"{readonly_attr}>{_esc(options_text)}</textarea></label>
</div>"""
        )
    question_lock_notice = (
        '<p class="muted"><strong>These questions and answer options are fixed because the new-member outcome classifier depends on their exact meanings.</strong></p>'
        if questions_locked
        else ""
    )
    video_url = str(payload.get("avatar_video_url") or "").strip()
    video_html = (
        f'<p><a class="button secondary" href="{_esc(video_url)}" target="_blank" rel="noreferrer">Open avatar video</a></p>'
        if video_url
        else '<p class="muted">No avatar video URL saved yet.</p>'
    )
    status_lines = [
        ("Generation enabled", "Yes" if defaults.get("enabled") else "No"),
        ("Azure avatar key", "Configured" if avatar_runtime.get("key_configured") else "Not configured"),
        ("Azure key fingerprint", avatar_runtime.get("key_fingerprint") or ""),
        ("Azure key source", avatar_runtime.get("key_source") or ""),
        ("Azure region", avatar_runtime.get("region") or "Not configured"),
        ("Azure region source", avatar_runtime.get("region_source") or ""),
        ("Azure endpoint", avatar_runtime.get("endpoint") or ""),
        ("Default character", defaults.get("character") or "lisa"),
        ("Default style", defaults.get("style") or "graceful-sitting"),
        ("Default voice", defaults.get("voice") or "en-GB-SoniaNeural"),
        ("Avatar status", payload.get("avatar_status") or "Not generated"),
        ("Avatar job", payload.get("avatar_job_id") or ""),
        ("Generated", payload.get("avatar_generated_at") or ""),
    ]
    if payload.get("avatar_error"):
        status_lines.append(("Avatar error", payload.get("avatar_error")))
    avatar_status_rows = "".join(
        f"<tr><td>{_esc(label)}</td><td>{_esc(value)}</td></tr>" for label, value in status_lines
    )
    token_input = _token_input(request)
    body = f"""
<section>
  <div class="inline" style="justify-content: space-between;">
    <h2>{_esc(flow.label)}</h2>
    <a class="button secondary" href="{_href(request, '/admin/survey-config')}">Back to survey setup</a>
  </div>
  {notice_html}
  <form method="post" action="{_post_action(request, f'/admin/survey-config/{flow.key}')}" class="stack">
    {token_input}
    <label><span>Survey name</span><input name="label" value="{_esc(flow.label)}"></label>
    <p class="muted">The survey name is shown to staff in MemberSense. Members see the intro message and questions below.</p>
    <label><span>Intro message</span><textarea name="intro">{_esc(flow.intro)}</textarea></label>
    <label><span>Completion message</span><textarea name="completion">{_esc(flow.completion)}</textarea></label>
    <h3>Questions And Answers</h3>
    {question_lock_notice}
    {''.join(question_fields)}
    <h3>Avatar Video</h3>
    <p class="muted">Provide a script for the avatar. The generator uses the same HealthSense defaults unless you override character, style, or voice below. You can also paste an existing video URL.</p>
    {video_html}
    <label><span>Avatar script</span><textarea name="avatar_script">{_esc(payload.get('avatar_script') or flow.intro)}</textarea></label>
    <label><span>Avatar video URL</span><input name="avatar_video_url" value="{_esc(video_url)}" placeholder="https://... or /membersense-media/..."></label>
    <label><span>Poster image URL</span><input name="avatar_poster_url" value="{_esc(payload.get('avatar_poster_url') or '')}"></label>
    <div class="grid">
      <label><span>Character</span><input name="avatar_character" value="{_esc(payload.get('avatar_character') or defaults.get('character') or 'lisa')}"></label>
      <label><span>Style</span><input name="avatar_style" value="{_esc(payload.get('avatar_style') or defaults.get('style') or 'graceful-sitting')}"></label>
      <label><span>Voice</span><input name="avatar_voice" value="{_esc(payload.get('avatar_voice') or defaults.get('voice') or 'en-GB-SoniaNeural')}"></label>
    </div>
    <div class="inline">
      <button type="submit" name="action" value="save">Save survey setup</button>
      <button type="submit" name="action" value="generate" class="secondary">Save and start avatar generation</button>
      <button type="submit" name="action" value="refresh" class="secondary">Refresh avatar job</button>
    </div>
  </form>
</section>
<section>
  <h2>Avatar Settings</h2>
  <table>
    <thead><tr><th>Setting</th><th>Value</th></tr></thead>
    <tbody>{avatar_status_rows}</tbody>
  </table>
</section>"""
    return _layout(request, f"Configure {flow.label}", body)


@router.post("/admin/survey-config/{flow_key}")
async def survey_config_update(
    request: Request,
    flow_key: str,
    session: Session = Depends(get_session),
    _: None = Depends(require_admin),
):
    if str(flow_key or "").strip().lower() not in SURVEY_FLOWS:
        raise HTTPException(status_code=404, detail="Survey setup not found")
    form = await request.form()
    action = str(form.get("action") or "save").strip().lower()
    try:
        save_survey_config(
            session,
            flow_key,
            label=str(form.get("label") or ""),
            intro=str(form.get("intro") or ""),
            completion=str(form.get("completion") or ""),
            questions=_survey_config_questions_from_form(form, flow_key),
            avatar_script=str(form.get("avatar_script") or ""),
            avatar_video_url=str(form.get("avatar_video_url") or ""),
            avatar_poster_url=str(form.get("avatar_poster_url") or ""),
            avatar_character=str(form.get("avatar_character") or ""),
            avatar_style=str(form.get("avatar_style") or ""),
            avatar_voice=str(form.get("avatar_voice") or ""),
        )
        if action == "generate":
            queue_survey_avatar_generation(session, flow_key)
            return _redirect(request, _survey_config_path(flow_key, generated=1, saved=1))
        if action == "refresh":
            refreshed_row = refresh_survey_avatar_video(session, flow_key)
            status = str(getattr(refreshed_row, "avatar_status", "") or "").strip().lower()
            has_video = bool(str(getattr(refreshed_row, "avatar_video_url", "") or "").strip())
            if status not in {"failed", "succeeded"} and not has_video:
                queue_survey_avatar_completion(flow_key)
            return _redirect(request, _survey_config_path(flow_key, refreshed=1, saved=1))
        return _redirect(request, _survey_config_path(flow_key, saved=1))
    except Exception as exc:
        return _redirect(request, _survey_config_path(flow_key, error=str(exc)))


@router.get("/admin/conversations/{conversation_id}", response_class=HTMLResponse)
@router.get("/admin/surveys/{conversation_id}", response_class=HTMLResponse)
def conversation_detail(
    request: Request,
    conversation_id: int,
    link_created: int | None = None,
    visit_recorded: int | None = None,
    session: Session = Depends(get_session),
    _: None = Depends(require_admin),
):
    row = session.get(Conversation, int(conversation_id))
    if row is None:
        raise HTTPException(status_code=404, detail="Survey not found")
    member = session.get(Member, row.member_id)
    tasks = (
        session.execute(
            select(StaffTask).where(StaffTask.conversation_id == int(row.id)).order_by(desc(StaffTask.id)).limit(20)
        )
        .scalars()
        .all()
    )
    task_rows = []
    for task in tasks:
        priority_class = "priority-high" if task.priority == "high" else ""
        task_rows.append(
            "<tr>"
            f"<td class=\"{priority_class}\">{_esc(task.priority)}</td>"
            f"<td>{_esc(task.title)}<br><span class=\"muted\">{_esc(task.detail or '')}</span></td>"
            f"<td><span class=\"pill\">{_esc(task.status)}</span></td>"
            "</tr>"
        )
    app_link = _app_survey_url(request, row)
    mailto = _survey_mailto(member, app_link, _survey_label(row, session))
    link_notice_parts = []
    if visit_recorded is not None:
        link_notice_parts.append("Visit recorded.")
    if link_created is not None:
        link_notice_parts.append("App link created.")
    link_notice = f'<p><strong>{_esc(" ".join(link_notice_parts))}</strong></p>' if link_notice_parts else ""
    if app_link:
        email_action = (
            f'<a class="button secondary" href="{_esc(mailto)}">Email link to member</a>'
            if mailto
            else '<span class="muted">No email recorded for this member.</span>'
        )
        app_link_html = f"""
<section>
  <h2>In-App Link</h2>
  {link_notice}
  <p class="muted">Use this when a member should complete the survey in the browser.</p>
  <div class="inline">
    <input value="{_esc(app_link)}" readonly onclick="this.select()" data-copy-source>
    <button type="button" class="secondary" data-copy-value="{_esc(app_link)}" data-copy-label="Copy link">Copy link</button>
    <a class="button" href="{_esc(app_link)}" target="_blank" rel="noreferrer">Open app survey</a>
    {email_action}
  </div>
</section>"""
    else:
        app_link_html = f"""
<section>
  <h2>In-App Link</h2>
  <form method="post" action="{_post_action(request, f'/admin/surveys/{row.id}/app-link')}" class="inline">
    <button type="submit" class="secondary">Create app link</button>
  </form>
</section>"""
    body = f"""
<section>
  <div class="inline" style="justify-content: space-between;">
    <h2>{_esc(_survey_label(row, session))}</h2>
    <a class="button secondary" href="{_href(request, '/admin/surveys')}">Back to surveys</a>
  </div>
  <div class="grid">
    <div><strong>Member</strong><br><a href="{_href(request, f'/admin/members/{row.member_id}')}">{_esc(member_name(member))}</a></div>
    <div><strong>Status</strong><br><span class="pill">{_esc(row.status)}</span></div>
    <div><strong>Answers</strong><br>{_esc(_survey_progress(row, session))}</div>
    <div><strong>Started</strong><br>{_esc(_datetime(row.created_at))}</div>
    <div><strong>Updated</strong><br>{_esc(_datetime(row.updated_at))}</div>
    <div><strong>Completed</strong><br>{_esc(_datetime(row.completed_at))}</div>
  </div>
</section>
{app_link_html}
<section>
  <h2>Questions And Answers</h2>
  <table>
    <thead><tr><th>No.</th><th>Question</th><th>Answer</th></tr></thead>
    <tbody>{_survey_answer_rows(row, session)}</tbody>
  </table>
</section>
<section>
  <h3>Summary</h3>
  <pre>{_esc(row.summary or 'No summary yet.')}</pre>
  <h3>Classification</h3>
  <table>
    <thead><tr><th>Field</th><th>Value</th></tr></thead>
    <tbody>{_classification_rows(row.classification)}</tbody>
  </table>
</section>
<section>
  <h2>Tasks</h2>
  <table>
    <thead><tr><th>Priority</th><th>Task</th><th>Status</th></tr></thead>
    <tbody>{''.join(task_rows) or '<tr><td colspan="3">No tasks for this survey.</td></tr>'}</tbody>
  </table>
</section>"""
    return _layout(request, f"Survey {row.id}", body)


@router.post("/admin/surveys/{conversation_id}/app-link")
def create_existing_survey_app_link(
    request: Request,
    conversation_id: int,
    session: Session = Depends(get_session),
    _: None = Depends(require_admin),
):
    row = session.get(Conversation, int(conversation_id))
    if row is None:
        raise HTTPException(status_code=404, detail="Survey not found")
    ensure_app_link_token(session, row)
    return _redirect(request, f"/admin/surveys/{row.id}?link_created=1")


@router.get("/admin/messages", response_class=HTMLResponse)
@router.get("/admin/surveys", response_class=HTMLResponse)
def surveys(
    request: Request,
    status: str = "",
    flow_key: str = "",
    session: Session = Depends(get_session),
    _: None = Depends(require_admin),
):
    query = select(Conversation)
    selected_status = str(status or "").strip().lower()
    selected_flow = str(flow_key or "").strip()
    if selected_status in {"active", "completed", "superseded"}:
        query = query.where(Conversation.status == selected_status)
    if selected_flow:
        query = query.where(Conversation.flow_key == selected_flow)
    rows = session.execute(query.order_by(desc(Conversation.id)).limit(200)).scalars().all()
    table = []
    for row in rows:
        member = session.get(Member, row.member_id)
        table.append(
            "<tr>"
            f"<td>{_esc(_datetime(row.created_at))}</td>"
            f"<td><a href=\"{_href(request, f'/admin/members/{row.member_id}')}\">{_esc(member_name(member))}</a></td>"
            f"<td>{_esc(_survey_label(row, session))}</td>"
            f"<td><span class=\"pill\">{_esc(row.status)}</span></td>"
            f"<td>{_esc(_survey_progress(row, session))}</td>"
            f"<td>{_esc(_survey_outcome(row))}</td>"
            f"<td><a class=\"button secondary\" href=\"{_href(request, f'/admin/surveys/{row.id}')}\">Open survey</a></td>"
            "</tr>"
        )
    token_input = _token_input(request)
    status_options = "".join(
        f'<option value="{value}"{" selected" if selected_status == value else ""}>{label}</option>'
        for value, label in [("", "All statuses"), ("active", "Active"), ("completed", "Completed"), ("superseded", "Superseded")]
    )
    flow_options = ['<option value="">All surveys</option>']
    for option in survey_options(session):
        value = _esc(option["key"])
        selected = " selected" if selected_flow == option["key"] else ""
        flow_options.append(f'<option value="{value}"{selected}>{_esc(option["label"])}</option>')
    body = f"""
<section>
  <div class="inline" style="justify-content: space-between;">
    <h2>Recent Surveys</h2>
    <a class="button secondary" href="{_href(request, '/admin/survey-config')}">Configure surveys</a>
  </div>
  <form method="get" action="/admin/surveys" class="inline" style="margin-bottom: 12px;">
    {token_input}
    <label><span>Status</span><select name="status">{status_options}</select></label>
    <label><span>Survey type</span><select name="flow_key">{''.join(flow_options)}</select></label>
    <button type="submit">Filter</button>
  </form>
  <table>
    <thead><tr><th>Started</th><th>Member</th><th>Survey</th><th>Status</th><th>Answers</th><th>Outcome</th><th>Action</th></tr></thead>
    <tbody>{''.join(table) or '<tr><td colspan="7">No surveys found.</td></tr>'}</tbody>
  </table>
</section>"""
    return _layout(request, "Recent Surveys", body)
