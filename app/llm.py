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

# Default to gpt-5.1; can be overridden via LLM_MODEL env
default_model = os.getenv("LLM_MODEL") or "gpt-5.1"
_llm = ChatOpenAI(model=default_model, temperature=0, api_key=api_key)

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
    return _llm.invoke(prompt).content.strip()

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
