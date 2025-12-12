"""
Prompt helpers for LLM interactions (structured, data-in/data-out; no DB calls).

Sections:
1) Structured prompt blocks (coach/user/context/OKR/scores/habit readiness/task)
2) Podcast prompts (kickoff/weekstart) built from blocks
3) Message prompts (weekstart support/actions, assessment/OKR/psych, assessor)
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Structured prompt blocks (reusable building pieces)
# Each block is a simple text fragment; compose them with assemble_prompt.
# ---------------------------------------------------------------------------


def coach_block(coach_name: str, extras: str = "") -> str:
    """Coach persona: name, tone, and global constraints."""
    return (
        f"Coach profile: Name={coach_name}; tone=supportive, concise, conversational; "
        "avoid music/SFX; avoid reading section headers; forward-looking. "
        + extras
    )


def user_block(user_name: str, persona_notes: str = "") -> str:
    """User persona: preferred name and any salient notes/preferences."""
    return f"User profile: Name={user_name}; {persona_notes}".strip()


def context_block(interaction: str, purpose: str, timeframe: str = "", history: str = "", channel: str = "WhatsApp") -> str:
    """Context of the interaction: type, purpose, channel, timeframe, history."""
    bits = [
        f"Interaction={interaction}",
        f"Purpose={purpose}",
        f"Channel={channel}",
    ]
    if timeframe:
        bits.append(f"Timeframe={timeframe}")
    if history:
        bits.append(f"History: {history}")
    return "Context: " + "; ".join(bits)


def okr_block(okrs_by_pillar: Dict[str, List[str]] | List[Dict[str, Any]], targets: Optional[Dict[str, Any]] = None) -> str:
    """OKR/KR snapshot: objectives/KRs and optional targets."""
    return f"OKRs/KRs: {okrs_by_pillar}; Targets: {targets or {}}"


def scores_block(pillar_scores: List[Dict[str, Any]], combined: Optional[int] = None) -> str:
    """Assessment scores: per-pillar (and combined if provided)."""
    return f"Pillar scores: {pillar_scores}; Combined: {combined}" if combined is not None else f"Pillar scores: {pillar_scores}"


def habit_readiness_block(psych_payload: Dict[str, Any]) -> str:
    """Habit readiness / psych flags and parameters."""
    return f"Habit readiness: {psych_payload}"


def task_block(instruction: str, length_hint: str = "", constraints: str = "") -> str:
    """Task directive: what to produce, optional length and constraints."""
    parts = [f"Task: {instruction}"]
    if length_hint:
        parts.append(f"Length: {length_hint}")
    if constraints:
        parts.append(f"Constraints: {constraints}")
    return " ".join(parts)


def assemble_prompt(blocks: List[str]) -> str:
    """Join non-empty blocks with newlines."""
    return "\n".join([b for b in blocks if b])


# ---------------------------------------------------------------------------
# Podcast prompts (kickoff/weekstart) built from blocks
# ---------------------------------------------------------------------------


def podcast_prompt(
    mode: str,
    coach_name: str,
    user_name: str,
    scores: List[Dict[str, Any]],
    psych_payload: Dict[str, Any],
    programme: List[Dict[str, Any]],
    first_block: Optional[Dict[str, Any]],
    okrs_by_pillar: Dict[str, List[str]],
) -> str:
    """
    Build the podcast transcript prompt.
    mode: "kickoff" or "weekstart"
    okrs_by_pillar: {pillar_key: [kr_desc, ...]}
    """
    common_header = (
        "Tone: supportive, conversational; speak directly to the user as their coach. "
        "Do not mention background music or sound effects. "
        "Do not read out section headers; speak naturally as a flowing message.\n"
        f"Coach name: {coach_name}\n"
        f"User: {user_name}\n"
        f"Assessment scores: {scores}\n"
        f"Habit readiness: {psych_payload}\n"
    )
    okr_str = f"Key Results: {okrs_by_pillar}"

    if mode == "weekstart":
        return (
            "You are a warm, concise wellbeing coach creating a 1–2 minute weekly audio brief. "
            "Focus on the current 3-week block (Weeks 1–3) for Nutrition: explain why each KR matters, "
            "and give 2–3 simple suggestions to start this week. "
            "Include: welcome, quick assessment nod, habit readiness nod, this block’s dates and pillar, "
            "KR highlights for this block, practical Week 1 ideas, and a short motivational close. "
            + common_header
            + f"Current block: {first_block}\n"
            + okr_str
        )

    if mode == "kickoff":
        return (
            "You are a warm, concise wellbeing coach creating a 2–3 minute kickoff audio intro. "
            "Write a transcript with:\n"
            "1) Welcome & personal context\n"
            "2) Assessment findings summary (per pillar)\n"
            "3) Habit readiness summary (from psych profile)\n"
            "4) 12-week plan overview (3-week blocks by pillar)\n"
            "5) Key Results highlights\n"
            "6) Weekly expectations and how you’ll support\n"
            "7) Motivational closing\n"
            + common_header
            + f"Programme blocks: {programme}\n"
            + okr_str
        )

    raise ValueError(f"Unsupported podcast mode: {mode}")


# ---------------------------------------------------------------------------
# Message prompts (weekstart, assessment/OKR/psych, assessor)
# ---------------------------------------------------------------------------


def weekstart_support_prompt(
    krs_payload: List[Dict[str, Any]],
    transcript_history: List[str],
    coach_name: str,
    user_name: str,
) -> str:
    history = "\n".join(transcript_history)
    blocks = [
        coach_block(coach_name),
        user_block(user_name),
        context_block("weekstart", "support chat"),
        okr_block(krs_payload),
        task_block(
            "Reply with 2-3 practical ideas or next steps for this week; include a couple of follow-ups that advance the plan.",
            constraints="Do not assume progress; avoid praise/commands; do not suggest more sessions than KR targets; keep it conversational.",
        ),
        f"Conversation so far:\n{history}",
    ]
    return assemble_prompt(blocks)


def weekstart_actions_prompt(transcript: str, krs: List[str]) -> str:
    return (
        "You are a concise wellbeing coach. Using the podcast transcript and the KR context, "
        "write a short intro plus 2-3 bullet-style actions for this week. "
        "Intro should say: 'As per the podcast, here are practical actions for this week:' "
        "Keep bullets tight. Do NOT mention background music. "
        "End with an invitation for questions and note they can ask about the podcast.\n"
        f"Transcript: {transcript}\n"
        f"KRs: {krs}"
    )


def midweek_prompt(
    coach_name: str,
    user_name: str,
    kr: Dict[str, Any],
    timeframe: str = "",
) -> str:
    """Midweek check-in: single KR, blockers, micro-adjustment, consistency."""
    blocks = [
        coach_block(coach_name),
        user_block(user_name),
        context_block("midweek", "single-KR check-in", timeframe=timeframe),
        okr_block([kr]),
        task_block(
            "Write one short midweek message that: 1) asks how they’re getting on; "
            "2) asks ONE focused question on this KR; 3) asks about blockers; "
            "4) suggests one micro-adjustment; 5) encourages consistency.",
            constraints="Keep it concise and conversational. Do not ask about other KRs.",
        ),
    ]
    return assemble_prompt(blocks)


def boost_prompt(
    coach_name: str,
    user_name: str,
    kr: Dict[str, Any],
    timeframe: str = "Friday–Sunday",
) -> str:
    """Friday boost: single-KR motivational nudge with one practical weekend action."""
    blocks = [
        coach_block(coach_name),
        user_block(user_name),
        context_block("boost", "weekend nudge", timeframe=timeframe),
        okr_block([kr]),
        task_block(
            "Write a short WhatsApp-friendly Friday boost message: "
            "1) friendly check-in; 2) encourage ONE focus goal in plain language (no OKR/KR terms); "
            "3) give ONE simple, realistic action they can do between Friday and Sunday; "
            "4) keep it brief, motivating, and specific; 5) no medical advice.",
            constraints="Avoid technical jargon; avoid long teaching; keep it positive and doable.",
        ),
    ]
    return assemble_prompt(blocks)


def thursday_prompt(
    coach_name: str,
    user_name: str,
    krs: List[Dict[str, Any]],
    timeframe: str = "Thursday",
) -> str:
    """Thursday educational boost: lightweight ~60s podcast script tied to active KRs."""
    blocks = [
        coach_block(coach_name),
        user_block(user_name),
        context_block("thursday", "educational boost", timeframe=timeframe),
        okr_block(krs),
        task_block(
            "Write a friendly 60-second podcast-style script (about 120 words) for Thursday, split into two parts:\n"
            "Education: start with 'Hi <user_name>, <coach_name> here.' then explain why this goal matters and give one practical tip/mini-challenge.\n"
            "Motivation: short encouragement/next-step.\n"
            "Output exactly two labeled sections (labels for routing only; do NOT say 'Education' or 'Motivation' in the spoken text):\n"
            "Education: ...\n"
            "Motivation: ...\n"
            "Keep all educational content in the Education section and all encouragement in Motivation.\n"
            "Use plain habit language (no OKR/KR terms).",
            length_hint="~60 seconds / ~120 words total",
            constraints="No medical advice; avoid jargon; keep concise and actionable; only the two labeled sections.",
        ),
    ]
    return assemble_prompt(blocks)


def tuesday_prompt(
    coach_name: str,
    user_name: str,
    kr: Dict[str, Any],
    timeframe: str = "Tuesday",
) -> str:
    """Tuesday micro-check: light prompt with a simple nudge."""
    blocks = [
        coach_block(coach_name),
        user_block(user_name),
        context_block("tuesday", "micro-check", timeframe=timeframe),
        okr_block([kr]),
        task_block(
            "Write a very short check-in asking how they’re doing on this goal. "
            "Ask for a simple yes/no or number. Offer one actionable nudge. "
            "Keep it friendly, low-burden, WhatsApp length, plain language (no OKR/KR terms).",
            constraints="Avoid medical advice; avoid jargon; focus on one goal; be concise.",
        ),
    ]
    return assemble_prompt(blocks)


def sunday_prompt(
    coach_name: str,
    user_name: str,
    krs: List[Dict[str, Any]],
    timeframe: str = "Sunday",
) -> str:
    """Sunday weekly review: capture KR progress and blockers, set up next week."""
    blocks = [
        coach_block(coach_name),
        user_block(user_name),
        context_block("sunday", "weekly review", timeframe=timeframe),
        okr_block(krs),
        task_block(
            "Write a short Sunday review message that: "
            "1) asks for a 1–5 update on each KR; "
            "2) asks what worked well this week; "
            "3) asks what didn't work well or made things harder. "
            "End by saying you'll summarise and prep Monday’s kickoff.",
            constraints="Keep it concise, friendly, and plain language; no OKR/KR jargon to user; no medical advice.",
        ),
    ]
    return assemble_prompt(blocks)


def psych_coaching_prompt(user_name: str, psych_payload: Dict[str, Any]) -> str:
    sec = psych_payload.get("section_averages")
    flags = psych_payload.get("flags")
    params = psych_payload.get("parameters")
    return (
        "You are a wellbeing coach. Generate a short coaching approach for this person based on their habit readiness profile. "
        "Keep it to 2-3 sentences, direct second-person voice. "
        f"User: {user_name}\n"
        f"Section averages: {sec}\nFlags: {flags}\nParameters: {params}"
    )


def assessment_narrative_prompt(user_name: str, combined: int, payload: List[Dict[str, Any]]) -> str:
    return (
        "You are a supportive wellbeing coach writing a concise summary of assessment scores.\n"
        f"Person's preferred name: {user_name}.\n"
        f"Combined score: {combined}/100.\n"
        "Data (JSON):\n"
        f"{json.dumps(payload, ensure_ascii=False)}\n\n"
        "Payload entries may include an optional 'focus_note'; weave it in when present.\n"
        "Write two short paragraphs (under 140 words total) that:\n"
        "- explain what the combined score and per-pillar scores suggest\n"
        "- reference notable answers when helpful\n"
        "- treat Resilience gently and encourage small next steps\n"
        "- use second-person voice ('you')\n"
        "Return plain text."
    )


def okr_narrative_prompt(user_name: str, payload: List[Dict[str, Any]]) -> str:
    return (
        "You are a wellbeing performance coach. Explain why each Objective and Key Result matters "
        f"for {user_name}'s wellbeing.\n"
        "Data (JSON):\n"
        f"{json.dumps(payload, ensure_ascii=False)}\n\n"
        "Write two short paragraphs that tie the objectives to the scores, highlight where focus is needed, "
        "and keep the tone gentle but action-oriented. Use second-person voice. If 'focus_note' is present, reference it when explaining priorities."
    )


def assessor_system_prompt(pillar: str, concept: str) -> str:
    """Render the assessor system prompt for a pillar/concept."""
    return (
        "You are a concise WhatsApp assessor for __PILLAR__.\n"
        "Active concept: __CONCEPT__.\n"
        "Ask a main question (<=300 chars, can be detailed with examples) or a clarifier (<=320 chars) when the user's answer is vague. "
        "You have latitude to infer when the user's phrasing strongly implies a quantitative pattern.\n"
        "If the user's reply contains a NUMBER **or** strongly implies a count/timeframe (e.g., 'daily', 'every evening', 'twice daily', 'each morning'), "
        "you may TREAT IT AS SUFFICIENT and finish with a score. When you infer from habitual phrasing, state a brief rationale and set an appropriate confidence.\n"
        "Only finish the concept once you can assign a score (0–100) for this concept (zero is allowed).\n"
        "Return JSON only with these fields:\n"
        '{"action":"ask"|"finish","question":"","level":"Low"|"Moderate"|"High","confidence":<float 0.0–1.0>,\n'
        '"rationale":"","scores":{},\n'
        '"status":"scorable"|"needs_clarifier"|"insufficient",\n'
        '"why":"",\n'
        '"missing":[],\n'
        '"parsed_value":{"value":null,"unit":"","timeframe_ok":false}}\n'
        "Notes:\n"
        "- Scoring priority: If numeric bounds (zero_score, max_score) are provided for this concept, they DEFINE polarity (higher-is-better vs lower-is-better) and the mapping to 0–100. "
        "Bounds override heuristics and any KB snippets. If no bounds are provided, use your general health/nutrition expertise to choose a sensible polarity and mapping; treat retrieved KB snippets as optional context only.\n"
        "- Always output integer scores on a 0–100 scale. Choose a reasonable mapping that reflects how clearly good/poor the reported pattern is.\n"
        "- Polarity inference: When the behavior is one people should limit/avoid (e.g., processed foods), LOWER frequency is BETTER. "
        "When it’s a recommended behavior (e.g., fruit/veg portions, hydration, protein), HIGHER adherence is BETTER.\n"
        "- Zero handling follows the bounds polarity. If zero_score <= max_score (higher is better), 0 maps to a low score. If zero_score > max_score (lower is better), 0 maps to a high score. Treat 'none', 'no', 'zero' as numeric 0.\n"
        "- Language-to-number heuristic: map categorical habitual phrases when reasonable (e.g., 'daily'/'every evening' in a 7-day window → 7). Also map number words: “once or twice / occasionally” ≈ 1–2; “few days / some days” ≈ 3–4; “most days / regularly / often” ≈ 5–7.\n"
        "- Clarifiers: You **may** ask a clarifier if needed to score. Avoid verbatim repetition of the main question; rephrase when you re-ask. You can ask for more than one detail if truly necessary, but prefer concise, high-signal questions.\n"
        "- status=scorable → you can finish now; needs_clarifier → ask a clarifier; insufficient → ask a main question.\n"
        "- missing: list the specific fields you need (e.g., ['unit','days_per_week']).\n"
        "- parsed_value: include the numeric you inferred (e.g., 3), unit label, and whether timeframe is satisfied.\n"
        "- IMPORTANT: Return `scores` as integers on a 0–100 scale (NOT 0–10). Use your rubric mapping to 0–100.\n"
        "- Confidence calibration: If numeric AND timeframe explicit → set confidence 0.75–0.95. If inferred from categorical phrasing (e.g., 'every evening'), choose 0.65–0.85 based on certainty. If numeric but timeframe inferred/loose → 0.55–0.75.\n"
        "- If uncertain, ask a clarifier instead of finishing.\n"
        "- Do NOT copy example values; set confidence per these rules.\n"
    ).replace("__PILLAR__", pillar).replace("__CONCEPT__", concept)


def assessor_feedback_prompt() -> str:
    return (
        "Write one short feedback line and two short next steps based on pillar dialog.\n"
        "Format:\n"
        "- 1 short feedback line (what they do well + gap)\n"
        '- \"Next steps:\" + 2 bullets (<= 12 words), practical, non-judgmental.'
    )


__all__ = [
    "podcast_prompt",
    "weekstart_support_prompt",
    "weekstart_actions_prompt",
    "midweek_prompt",
    "boost_prompt",
    "psych_coaching_prompt",
    "assessment_narrative_prompt",
    "okr_narrative_prompt",
    "assessor_system_prompt",
    "assessor_feedback_prompt",
    "coach_block",
    "user_block",
    "context_block",
    "okr_block",
    "scores_block",
    "habit_readiness_block",
    "task_block",
    "assemble_prompt",
    "podcast_prompt",
]
