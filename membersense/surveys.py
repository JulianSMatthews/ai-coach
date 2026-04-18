from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .config import GYM_NAME


@dataclass(frozen=True)
class SurveyQuestion:
    key: str
    text: str
    helper: str = ""
    options: tuple[str, ...] = ()


@dataclass(frozen=True)
class SurveyFlow:
    key: str
    label: str
    intro: str
    questions: tuple[SurveyQuestion, ...]
    completion: str
    avatar_script: str = ""
    avatar_video_url: str = ""
    avatar_poster_url: str = ""
    avatar_character: str = ""
    avatar_style: str = ""
    avatar_voice: str = ""
    avatar_status: str = ""
    avatar_job_id: str = ""
    avatar_error: str = ""
    avatar_summary_url: str = ""


SURVEY_FLOWS: dict[str, SurveyFlow] = {
    "new_member": SurveyFlow(
        key="new_member",
        label="New member support survey",
        intro=(
            f"Welcome to {GYM_NAME}. I just want to ask a few quick questions so the gym team can help you get started properly."
        ),
        questions=(
            SurveyQuestion("goal", "What is your main goal from joining the gym?", options=("Lose weight", "Build strength", "Get fitter")),
            SurveyQuestion("experience", "How experienced do you feel with gym training?", options=("New", "Some experience", "Confident")),
            SurveyQuestion("confidence", "How confident do you feel walking in and training on your own?", options=("Low", "Medium", "High")),
            SurveyQuestion("barrier", "What is most likely to get in the way of you training regularly?", options=("Time", "Confidence", "Motivation")),
            SurveyQuestion("support", "Would you like help from the team to get started?", options=("Yes", "Maybe", "No")),
        ),
        completion="Thanks. The gym team has your answers and will follow up if support would help.",
    ),
    "inactive": SurveyFlow(
        key="inactive",
        label="Inactive member check-in",
        intro=(
            f"Hi, it is the {GYM_NAME} team checking in. We noticed you have not trained recently and wanted to understand what is getting in the way."
        ),
        questions=(
            SurveyQuestion("reason", "What has been the main reason you have not been training recently?", options=("Time", "Motivation", "Injury or pain")),
            SurveyQuestion("intent", "Do you want to get back into a routine at the gym?", options=("Yes", "Not sure", "No")),
            SurveyQuestion("support", "What would make it easier to come back?", options=("Simple plan", "Trainer check-in", "Class")),
        ),
        completion="Thanks for replying. The team will use this to help make the next step easier.",
    ),
    "exit": SurveyFlow(
        key="exit",
        label="Exit survey",
        intro=f"It is the {GYM_NAME} team. Sorry to see you leave. Could we ask a few quick questions so we can understand what happened?",
        questions=(
            SurveyQuestion("reason", "What is the main reason you are leaving?", options=("Cost", "Not using it", "Moving away")),
            SurveyQuestion("preventable", "Was there anything the gym could have done differently?", options=("Yes", "Not sure", "No")),
            SurveyQuestion("future", "Would you consider coming back in the future?", options=("Yes", "Maybe", "No")),
        ),
        completion="Thank you. Your feedback helps the gym improve.",
    ),
    "visit": SurveyFlow(
        key="visit",
        label="Visit follow-up survey",
        intro=(
            f"Thanks for visiting {GYM_NAME}. Could we ask a few quick questions about today's visit so the team can support your next session?"
        ),
        questions=(
            SurveyQuestion("experience", "How did your visit feel today?", options=("Good", "Okay", "Difficult")),
            SurveyQuestion("support", "Would support from the team help before your next visit?", options=("Yes", "Maybe", "No")),
            SurveyQuestion("next_step", "What would help most for your next session?", options=("Training plan", "Technique help", "Class or booking")),
        ),
        completion="Thanks. The team has your feedback and will follow up if support would help.",
    ),
}


def flow_for_key(flow_key: str) -> SurveyFlow:
    key = str(flow_key or "").strip().lower()
    if key not in SURVEY_FLOWS:
        raise ValueError(f"Unknown survey flow: {flow_key}")
    return SURVEY_FLOWS[key]


def _clean_text(value: object) -> str:
    return str(value or "").strip()


def _question_options_from_payload(raw: object, fallback: tuple[str, ...]) -> tuple[str, ...]:
    if isinstance(raw, str):
        values = [line.strip() for line in raw.replace("|", "\n").splitlines()]
    elif isinstance(raw, (list, tuple)):
        values = [str(item or "").strip() for item in raw]
    else:
        values = []
    cleaned = tuple(value for value in values if value)[:3]
    return cleaned or fallback


def flow_from_config(flow_key: str, payload: dict[str, Any] | None) -> SurveyFlow:
    base = flow_for_key(flow_key)
    data = payload if isinstance(payload, dict) else {}
    question_payloads = data.get("questions") if isinstance(data.get("questions"), list) else []
    by_key = {
        _clean_text(item.get("key")): item
        for item in question_payloads
        if isinstance(item, dict) and _clean_text(item.get("key"))
    }
    questions = []
    for question in base.questions:
        item = by_key.get(question.key, {})
        questions.append(
            SurveyQuestion(
                key=question.key,
                text=_clean_text(item.get("text")) or question.text,
                helper=_clean_text(item.get("helper")) or question.helper,
                options=_question_options_from_payload(item.get("options"), question.options),
            )
        )
    return SurveyFlow(
        key=base.key,
        label=_clean_text(data.get("label")) or base.label,
        intro=_clean_text(data.get("intro")) or base.intro,
        questions=tuple(questions),
        completion=_clean_text(data.get("completion")) or base.completion,
        avatar_script=_clean_text(data.get("avatar_script")),
        avatar_video_url=_clean_text(data.get("avatar_video_url")),
        avatar_poster_url=_clean_text(data.get("avatar_poster_url")),
        avatar_character=_clean_text(data.get("avatar_character")),
        avatar_style=_clean_text(data.get("avatar_style")),
        avatar_voice=_clean_text(data.get("avatar_voice")),
        avatar_status=_clean_text(data.get("avatar_status")),
        avatar_job_id=_clean_text(data.get("avatar_job_id")),
        avatar_error=_clean_text(data.get("avatar_error")),
        avatar_summary_url=_clean_text(data.get("avatar_summary_url")),
    )


def flow_config_payload(flow: SurveyFlow) -> dict[str, Any]:
    return {
        "key": flow.key,
        "label": flow.label,
        "intro": flow.intro,
        "completion": flow.completion,
        "questions": [
            {
                "key": question.key,
                "text": question.text,
                "helper": question.helper,
                "options": list(question.options),
            }
            for question in flow.questions
        ],
        "avatar_script": flow.avatar_script,
        "avatar_video_url": flow.avatar_video_url,
        "avatar_poster_url": flow.avatar_poster_url,
        "avatar_character": flow.avatar_character,
        "avatar_style": flow.avatar_style,
        "avatar_voice": flow.avatar_voice,
        "avatar_status": flow.avatar_status,
        "avatar_job_id": flow.avatar_job_id,
        "avatar_error": flow.avatar_error,
        "avatar_summary_url": flow.avatar_summary_url,
    }


def question_options(question: SurveyQuestion | None) -> list[str]:
    if question is None:
        return []
    return [str(option).strip() for option in question.options if str(option or "").strip()][:3]


def _option_key(value: str) -> str:
    return " ".join(str(value or "").strip().lower().replace("-", " ").split())


def normalize_option_answer(question: SurveyQuestion, inbound_text: str) -> str | None:
    options = question_options(question)
    if not options:
        return str(inbound_text or "").strip()
    raw = str(inbound_text or "").strip()
    if not raw:
        return None
    raw_key = _option_key(raw)
    for idx, option in enumerate(options, start=1):
        if raw_key in {_option_key(option), str(idx), chr(96 + idx)}:
            return option
    return None


def _answer_text(answers: dict[str, Any], key: str) -> str:
    return str((answers or {}).get(key) or "").strip()


def _yesish(text: str) -> bool:
    value = str(text or "").strip().lower()
    return value in {"y", "yes", "yeah", "yep", "sure"} or value.startswith("yes")


def _maybeish(text: str) -> bool:
    value = str(text or "").strip().lower()
    return value in {"maybe", "not sure", "unsure", "possibly"} or "not sure" in value


def _contains_any(text: str, needles: tuple[str, ...]) -> bool:
    value = str(text or "").strip().lower()
    return any(needle in value for needle in needles)


def _confidence_score(text: str) -> int | None:
    label = str(text or "").strip().lower()
    if label in {"low", "not confident"}:
        return 1
    if label in {"medium", "somewhat", "ok", "okay"}:
        return 3
    if label in {"high", "confident", "very confident"}:
        return 5
    for token in str(text or "").replace("/", " ").split():
        try:
            value = int(float(token))
        except Exception:
            continue
        if 1 <= value <= 5:
            return value
    return None


def classify_response(flow_key: str, answers: dict[str, Any]) -> dict[str, Any]:
    flow = flow_for_key(flow_key)
    if flow.key == "new_member":
        confidence = _confidence_score(_answer_text(answers, "confidence"))
        barrier = _answer_text(answers, "barrier")
        support = _answer_text(answers, "support")
        experience = _answer_text(answers, "experience")
        high_markers = (
            confidence is not None and confidence <= 2
        ) or _yesish(support) or _contains_any(
            f"{barrier} {experience}",
            ("confidence", "nervous", "anxious", "injury", "pain", "not sure", "no idea", "new"),
        )
        medium_markers = _maybeish(support) or (confidence is not None and confidence == 3)
        level = "high" if high_markers else ("medium" if medium_markers else "low")
        action = (
            "Book an induction or trainer check-in."
            if level == "high"
            else "Send a simple starter plan or class recommendation."
            if level == "medium"
            else "Send welcome message and leave open for questions."
        )
        return {
            "support_need": level,
            "priority": "high" if level == "high" else "normal",
            "recommended_action": action,
            "task_required": level in {"high", "medium"},
        }
    if flow.key == "inactive":
        reason = _answer_text(answers, "reason")
        intent = _answer_text(answers, "intent")
        support = _answer_text(answers, "support")
        risk_high = _contains_any(reason, ("cancel", "leaving", "too expensive", "cost", "injury", "pain", "not worth"))
        wants_back = _yesish(intent) or _maybeish(intent) or bool(support)
        return {
            "reactivation_opportunity": "high" if wants_back and not risk_high else ("medium" if wants_back else "low"),
            "priority": "high" if risk_high else ("normal" if wants_back else "low"),
            "recommended_action": (
                "Call or message with a concrete reset option."
                if wants_back
                else "Record reason and avoid repeated nudges unless they re-engage."
            ),
            "task_required": wants_back or risk_high,
        }
    if flow.key == "exit":
        reason = _answer_text(answers, "reason")
        preventable = _answer_text(answers, "preventable")
        future = _answer_text(answers, "future")
        save = _yesish(preventable) or _maybeish(preventable) or _yesish(future) or _maybeish(future)
        urgent = _contains_any(reason, ("staff", "dirty", "equipment", "rude", "complaint", "price", "cost", "value"))
        return {
            "save_opportunity": "yes" if save else "no",
            "priority": "high" if urgent or save else "normal",
            "recommended_action": (
                "Review quickly and consider a save/win-back call."
                if save
                else "Record feedback for trend reporting."
            ),
            "task_required": save or urgent,
        }
    if flow.key == "visit":
        experience = _answer_text(answers, "experience")
        support = _answer_text(answers, "support")
        next_step = _answer_text(answers, "next_step")
        needs_support = _yesish(support) or _maybeish(support) or _contains_any(
            f"{experience} {next_step}",
            ("difficult", "hard", "pain", "injury", "help", "plan", "technique", "class"),
        )
        priority = "high" if _contains_any(experience, ("difficult", "hard", "pain", "injury")) else "normal"
        return {
            "visit_experience": experience or "not recorded",
            "priority": priority if needs_support else "low",
            "recommended_action": (
                "Follow up with a clear next-session option."
                if needs_support
                else "Record positive visit feedback."
            ),
            "task_required": needs_support,
        }
    return {"task_required": False, "priority": "normal", "recommended_action": "Review response."}


def response_summary(flow_key: str, answers: dict[str, Any], classification: dict[str, Any]) -> str:
    flow = flow_for_key(flow_key)
    return response_summary_for_flow(flow, answers, classification)


def response_summary_for_flow(flow: SurveyFlow, answers: dict[str, Any], classification: dict[str, Any]) -> str:
    parts = [f"{flow.label} completed."]
    for question in flow.questions:
        answer = _answer_text(answers, question.key)
        if answer:
            parts.append(f"{question.text}: {answer}")
    action = str((classification or {}).get("recommended_action") or "").strip()
    if action:
        parts.append(f"Recommended action: {action}")
    return "\n".join(parts)
