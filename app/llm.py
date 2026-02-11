from __future__ import annotations

from pathlib import Path
from dotenv import load_dotenv
import os
from langchain_openai import ChatOpenAI

# Load environment variables from .env
env_path = Path('.') / '.env'
load_dotenv(dotenv_path=env_path)

api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    raise ValueError("OPENAI_API_KEY not found in environment")

DEFAULT_LLM_MODEL = "gpt-5.1"

# Assessment model selector (assessment Q&A + narratives).
assessment_model = (os.getenv("ASS_MODEL") or "").strip() or DEFAULT_LLM_MODEL
# Coaching interaction selector (weekly prompts, support chats, podcasts, etc).
coaching_model = (os.getenv("LLM_MODEL") or "").strip() or DEFAULT_LLM_MODEL

_ASSESSMENT_TOUCHPOINTS = {
    "assessment",
    "assessment_scores",
    "assessment_okr",
    "assessment_approach",
    "assessor_system",
    "assessor_feedback",
    "coaching_approach",
    "okr_narrative",
}


def is_assessment_touchpoint(touchpoint: str | None) -> bool:
    key = (touchpoint or "").strip().lower()
    if not key:
        return False
    if key.startswith("assessment_") or key.startswith("assessor_"):
        return True
    return key in _ASSESSMENT_TOUCHPOINTS


def resolve_model_name_for_touchpoint(
    touchpoint: str | None = None,
    model_override: str | None = None,
) -> str:
    override = (model_override or "").strip()
    if override:
        return override
    return assessment_model if is_assessment_touchpoint(touchpoint) else coaching_model


_llm_assessment = ChatOpenAI(model=assessment_model, temperature=0, api_key=api_key)
_llm_coaching = ChatOpenAI(model=coaching_model, temperature=0, api_key=api_key)

# Backward compatibility for older imports.
default_model = assessment_model
_llm = _llm_assessment


def get_llm_client(
    touchpoint: str | None = None,
    model_override: str | None = None,
) -> ChatOpenAI:
    model_name = resolve_model_name_for_touchpoint(touchpoint=touchpoint, model_override=model_override)
    if (model_override or "").strip():
        return ChatOpenAI(model=model_name, temperature=0, api_key=api_key)
    return _llm_assessment if is_assessment_touchpoint(touchpoint) else _llm_coaching

def compose_prompt(kind: str, context: dict) -> str:
    """
    kind: 'daily_micro_nudge' | 'weekly_reflection' | 'review_30d' | 'timeout_followup'
    context: dict with pillar/level/history etc.
    """
    base = {
        "daily_micro_nudge": "Keep it to 1–2 lines, warm tone. Offer a single easy action.",
        "weekly_reflection": "One reflective question; reinforce identity and progress.",
        "review_30d": "Invite a short 5Q reassessment; keep it encouraging.",
        "timeout_followup": "Gentle check-in acknowledging silence; offer smaller next step."
    }[kind]
    prompt = f"""You are a health AI coach.
Instruction: {base}
User context: {context}
Write the message (max 220 chars)."""
    client = get_llm_client()
    return client.invoke(prompt).content.strip()

EMBED_DIM = int(os.getenv("KB_EMBED_DIM", "1536"))

def embed_text(text: str) -> list[float]:
    """
    Return a length-EMBED_DIM embedding vector for text.
    Implement using your embedding model. This stub returns a fixed-size hash vector.
    Replace with a real call (e.g., OpenAI text-embedding-3-small).
    """
    import hashlib, math, random
    h = hashlib.sha256(text.encode("utf-8")).digest()
    random.seed(h)
    v = [random.random() - 0.5 for _ in range(EMBED_DIM)]
    # L2 normalize
    n = math.sqrt(sum(x*x for x in v)) or 1.0
    return [x / n for x in v]
