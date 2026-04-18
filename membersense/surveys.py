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
}


def flow_for_key(flow_key: str) -> SurveyFlow:
    key = str(flow_key or "").strip().lower()
    if key not in SURVEY_FLOWS:
        raise ValueError(f"Unknown survey flow: {flow_key}")
    return SURVEY_FLOWS[key]


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
    return {"task_required": False, "priority": "normal", "recommended_action": "Review response."}


def response_summary(flow_key: str, answers: dict[str, Any], classification: dict[str, Any]) -> str:
    flow = flow_for_key(flow_key)
    parts = [f"{flow.label} completed."]
    for question in flow.questions:
        answer = _answer_text(answers, question.key)
        if answer:
            parts.append(f"{question.key}: {answer}")
    action = str((classification or {}).get("recommended_action") or "").strip()
    if action:
        parts.append(f"Recommended action: {action}")
    return "\n".join(parts)
