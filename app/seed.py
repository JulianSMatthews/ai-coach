# app/seed.py
# PATCH (2025-09-03)
# • Seeds pillars (incl. goals), 5 concepts/pillar (20 total).
# • Seeds per-concept primary + alternates (concept_questions).
# • Seeds 2 KB snippets per concept (kb_snippets).
# • Generates deterministic placeholder embeddings (kb_vectors).
# • Seeds demo users.
# • Adds seed_users() shim for legacy import.

from __future__ import annotations

from typing import Dict, List
from datetime import datetime
import hashlib, math, random

from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import SessionLocal
from .models import User, Pillar, Concept, ConceptQuestion, KbSnippet, KbVector

PILLARS = [
    ("nutrition",  "Nutrition"),
    ("training",   "Training"),
    ("resilience", "Resilience"),
    ("recovery",   "Recovery"),
]

CONCEPTS: Dict[str, Dict[str, str]] = {
    "nutrition": {
        "protein_intake":   "Protein intake",
        "fruit_veg":        "Fruit & vegetables",
        "hydration":        "Hydration",
        "processed_sugar":   "Processed foods & sugar",
    },
    "training": {
        "cardio_frequency":     "Cardio frequency",
        "strength_training":    "Strength training",
        "flexibility_mobility": "Flexibility & mobility",
    },
    "resilience": {
        "stress_management":         "Stress management",
        "mood_stability":            "Mood stability",
        "selfcare_social":           "Self-care & social support",
    },
    "recovery": {
        "sleep_duration":       "Sleep duration",
        "sleep_quality":        "Sleep quality",
        "bedtime_consistency":  "Bedtime consistency",
    },
}

CONCEPT_QUESTIONS = {
    "nutrition": {
        "protein_intake": {
            "primary": "Thinking about the last 7 days, how many protein portions did you usually eat per day? For reference: 1 portion = palm-sized meat or fish, 2 eggs, 1 handful of nuts, or 1 cup of beans/lentils."
        },
        "fruit_veg": {
            "primary": "On a day in the last 7 days, how many portions of fruit and vegetables did you eat? For reference: 1 portion = 1 apple or banana, 1 fist-sized serving of vegetables, or 1 handful of salad or berries."
        },
        "hydration": {
            "primary": "Thinking about the last 7 days, how much water did you usually drink per day? For reference: 1 glass = 250ml, 1 small bottle = 500ml."
        },
        "processed_sugar": {
            "primary": "In the last 7 days, on how many days did you eat processed or sugary foods, and roughly how many portions per day? Examples: 1 portion = a chocolate bar, 1 can of fizzy drink, 1 handful of sweets, or a pastry."
        },
    },
    "training": {
        "cardio_frequency": {
            "primary": "In the last 7 days, on how many days did you do at least 20 minutes of cardio exercise, such as running, cycling, or swimming?"
        },
        "strength_training": {
            "primary": "In the last 7 days, how many strength training sessions did you do, such as weights, bodyweight exercises, or resistance bands?"
        },
        "flexibility_mobility": {
            "primary": "In the last 7 days, on how many days did you do stretching, yoga, or mobility work for at least 10 minutes?"
        },
    },
    "resilience": {
        "stress_management": {
            "primary": "In the last 7 days, on how many days did you spend at least 10 minutes on stress management, such as breathing exercises, meditation, or relaxation techniques?"
        },
        "mood_stability": {
            "primary": "Thinking about the last 7 days, on how many days did you feel calm and balanced for most of the day?"
        },
        "selfcare_social": {
            "primary": "In the last 7 days, on how many days did you spend time on enjoyable activities for yourself or with supportive friends and family?"
        },
    },
    "recovery": {
        "sleep_duration": {
            "primary": "In the last 7 days, on how many nights did you sleep for 7 or more hours?"
        },
        "sleep_quality": {
            "primary": "In the last 7 days, on how many mornings did you wake up feeling rested and refreshed?"
        },
        "bedtime_consistency": {
            "primary": "In the last 7 days, on how many nights did you go to bed at roughly the same time?"
        },
    },
}

KB_SNIPPETS: Dict[str, Dict[str, List[Dict]]] = {
    "nutrition": {
        "protein_intake": [
            {"title": "Protein targets", "text": "Aim ~1.6–2.2 g/kg/day; spread over 3–4 meals for muscle retention."},
            {"title": "Hand measure", "text": "One palm of lean protein per meal is an easy baseline for most people."},
        ],
        "fruit_veg": [
            {"title": "5-a-day", "text": "Target 5+ portions/day; include color variety for micronutrients and fiber."},
            {"title": "Front-load", "text": "Add veg/fruit to the first two meals to make the target easier."},
        ],
        "hydration": [
            {"title": "Daily intake", "text": "A simple start is ~30–35 ml/kg/day; more if hot or training hard."},
            {"title": "Urine check", "text": "Pale straw color generally indicates good hydration."},
        ],
        "processed_sugar": [
        {"title": "Healthy pattern", "text": "Avoid or rarely consume processed and sugary foods. Zero days in a week is best."},
        {"title": "Unhealthy pattern","text": "Eating processed or sugary foods on most days is poor. Frequent sweets, pastries, or sugary drinks signal a bad pattern."}   
        ],
    },
    "training": {
        "cardio_frequency": [
            {"title": "Cardio baseline", "text": "Aim for regular moderate cardio most days; start with brisk walks 20–30 min."},
            {"title": "Progress gently", "text": "Increase time or pace gradually to build endurance safely."},
        ],
        "strength_training": [
            {"title": "Progressive overload", "text": "Add small amounts of load or reps when technique is solid."},
            {"title": "Plan sessions", "text": "Schedule 2–3 strength sessions weekly for best progress."},
        ],
        "flexibility_mobility": [
            {"title": "Short daily work", "text": "10–20 min of stretching or mobility on most days helps range and recovery."},
            {"title": "Anchor habit", "text": "Link mobility to existing cues (after workout or before bed)."},
        ],
    },
    "resilience": {
        "stress_management": [
            {"title": "2-minute calm", "text": "Box breathing 4-4-4-4 or slow exhale breathing reduces acute stress."},
            {"title": "Micro-reset", "text": "Short walk + sunlight + music can flip state in minutes."},
        ],
        "mood_stability": [
            {"title": "Mood supports", "text": "Sleep, meals, and movement stabilize mood; keep basics steady."},
            {"title": "Name & reframe", "text": "Label feelings and reframe thoughts to reduce reactivity."},
        ],
        "stress_reactions_control": [
            {"title": "Pause & choose", "text": "Use a brief pause before responding; pick a calm action."},
            {"title": "Practice cue", "text": "Create a cue like 'slow breath' when stress spikes."},
        ],
        "selfcare_social": [
            {"title": "Protect buffers", "text": "Plan small enjoyable activities as stress buffers."},
            {"title": "Support time", "text": "Regular contact with supportive people boosts resilience."},
        ],
    },
    "recovery": {
        "sleep_duration": [
            {"title": "7–9 hours", "text": "Most adults benefit from 7–9 hours of sleep per night."},
            {"title": "Bank sleep", "text": "Prioritize earlier nights if short on sleep to catch up."},
        ],
        "sleep_quality": [
            {"title": "Sleep hygiene", "text": "Dark, cool room; reduce caffeine late; limit screens before bed."},
            {"title": "Wind-down", "text": "Have a simple wind-down routine to signal sleep time."},
        ],
        "bedtime_consistency": [
            {"title": "Regular schedule", "text": "Keeping similar bed/wake times supports circadian rhythm."},
            {"title": "Small shifts", "text": "Adjust bedtime in small steps (15–30 min) to improve consistency."},
        ],
    },
}

DEMO_USERS = [
    {"name": "Julian", "phone": "+447710307026", "is_superuser": True},
    {"name": "Rhys",   "phone": "+447860362908", "is_superuser": True},
]

def _hash_floats(text: str, dim: int = 256) -> list[float]:
    if not text:
        text = " "
    seed = int(hashlib.sha256(text.encode("utf-8")).hexdigest(), 16) % (2**31 - 1)
    rng = random.Random(seed)
    vec = []
    for _ in range(dim):
        h = hashlib.sha256(f"{text}|{rng.randint(0,1_000_000)}".encode("utf-8")).hexdigest()
        v = int(h[:8], 16) / 0xFFFFFFFF
        vec.append(v)
    norm = math.sqrt(sum(v*v for v in vec)) or 1.0
    return [v / norm for v in vec]

CONCEPT_SCORE_BOUNDS = {
    "nutrition": {
        "protein_intake": {"zero_score": 0, "max_score": 5},
        "fruit_veg":      {"zero_score": 0, "max_score": 7},
        "hydration":      {"zero_score": 0, "max_score": 7},
        "processed_sugar": {"zero_score": 7, "max_score": 0},  # days/week; reverse (7 days bad=0, 0 days best=100)
    },
    "training": {
        "cardio_frequency":     {"zero_score": 0, "max_score": 7},
        "strength_training":    {"zero_score": 0, "max_score": 7},
        "flexibility_mobility": {"zero_score": 0, "max_score": 7},
    },
    "resilience": {
        "stress_management": {"zero_score": 0, "max_score": 7},
        "mood_stability":    {"zero_score": 0, "max_score": 7},
        "selfcare_social":   {"zero_score": 0, "max_score": 7},
    },
    "recovery": {
        "sleep_duration":      {"zero_score": 0, "max_score": 7},
        "sleep_quality":       {"zero_score": 0, "max_score": 7},
        "bedtime_consistency": {"zero_score": 0, "max_score": 7},
    },
}

def upsert_pillars(session: Session) -> int:
    created = 0
    for key, name in PILLARS:
        row = session.execute(select(Pillar).where(Pillar.key == key)).scalar_one_or_none()
        if not row:
            session.add(Pillar(key=key, name=name, created_at=datetime.utcnow())); created += 1
    session.commit(); return created

def upsert_concepts(session: Session) -> int:
    created = 0
    for pillar_key, mapping in CONCEPTS.items():
        for code, name in mapping.items():
            row = session.execute(
                select(Concept).where(Concept.pillar_key == pillar_key, Concept.code == code)
            ).scalar_one_or_none()
            bounds = (CONCEPT_SCORE_BOUNDS.get(pillar_key, {}) or {}).get(code)
            if not row:
                session.add(Concept(
                    pillar_key=pillar_key,
                    code=code,
                    name=name,
                    description=None,
                    created_at=datetime.utcnow(),
                    zero_score=(bounds or {}).get("zero_score"),
                    max_score=(bounds or {}).get("max_score"),
                ))
                created += 1
            else:
                if bounds:
                    row.zero_score = bounds.get("zero_score")
                    row.max_score  = bounds.get("max_score")
    session.commit(); return created

def upsert_concept_questions(session: Session) -> int:
    created = 0
    for pillar_key, concepts in CONCEPT_QUESTIONS.items():
        for code, bundle in concepts.items():
            concept = session.execute(
                select(Concept).where(Concept.pillar_key == pillar_key, Concept.code == code)
            ).scalar_one_or_none()
            if not concept:
                continue
            # primary
            primary = (bundle.get("primary") or "").strip()
            if primary:
                exists = session.execute(
                    select(ConceptQuestion).where(
                        ConceptQuestion.concept_id == concept.id,
                        ConceptQuestion.text == primary
                    )
                ).scalar_one_or_none()
                if not exists:
                    session.add(ConceptQuestion(concept_id=concept.id, text=primary, is_primary=True)); created += 1
            # alternates
            for alt in bundle.get("alts", []):
                t = (alt or "").strip()
                if not t: continue
                exists = session.execute(
                    select(ConceptQuestion).where(
                        ConceptQuestion.concept_id == concept.id,
                        ConceptQuestion.text == t
                    )
                ).scalar_one_or_none()
                if not exists:
                    session.add(ConceptQuestion(concept_id=concept.id, text=t, is_primary=False)); created += 1
    session.commit(); return created

def upsert_kb_snippets(session: Session) -> int:
    created = 0
    for pillar_key, concepts in KB_SNIPPETS.items():
        for concept_code, items in concepts.items():
            for item in items:
                title = item.get("title") or None
                text  = (item.get("text") or "").strip()
                if not text: continue
                existing = session.execute(
                    select(KbSnippet).where(
                        KbSnippet.pillar_key == pillar_key,
                        KbSnippet.concept_code == concept_code,
                        KbSnippet.title == title,
                        KbSnippet.text == text
                    )
                ).scalar_one_or_none()
                if existing: continue
                session.add(KbSnippet(
                    pillar_key=pillar_key, concept_code=concept_code,
                    title=title, text=text, tags=None, created_at=datetime.utcnow()
                )); created += 1
    session.commit(); return created

def ensure_vectors_for_snippets(session: Session, dim: int = 256) -> int:
    new_vectors = 0
    snippets = session.execute(select(KbSnippet)).scalars().all()
    for sn in snippets:
        exists = session.execute(select(KbVector).where(KbVector.snippet_id == sn.id)).scalar_one_or_none()
        if exists: continue
        emb = _hash_floats(f"{sn.title or ''} | {sn.text}", dim=dim)
        session.add(KbVector(snippet_id=sn.id, embedding=emb, created_at=datetime.utcnow()))
        new_vectors += 1
    session.commit(); return new_vectors

def upsert_demo_users(session: Session) -> int:
    created = 0
    for u in DEMO_USERS:
        phone = u.get("phone")
        if not phone:
            continue
        row = session.execute(select(User).where(User.phone == phone)).scalar_one_or_none()
        if not row:
            session.add(User(
                name=u.get("name"),
                phone=phone,
                is_superuser=bool(u.get("is_superuser")),
                created_on=datetime.utcnow(),
                updated_on=datetime.utcnow(),
            ))
            created += 1
        else:
            # PATCH — 2025-09-11: keep superuser flag in sync with seed config
            if bool(u.get("is_superuser")) and not getattr(row, "is_superuser", False):
                row.is_superuser = True
    session.commit()
    return created

def run_seed() -> None:
    with SessionLocal() as s:
        p  = upsert_pillars(s)
        c  = upsert_concepts(s)
        cq = upsert_concept_questions(s)
        sn = upsert_kb_snippets(s)
        kv = ensure_vectors_for_snippets(s, dim=256)
        u  = upsert_demo_users(s)
        total_concepts = sum(len(v) for v in CONCEPTS.values())
        print(f"[seed] KB upsert complete. new_snippets={sn}")
        print(f"[seed] Concepts seed complete. pillars={len(PILLARS)} concepts={total_concepts} new_concepts={c}")
        print(f"[seed] Concept questions upsert complete. new_questions={cq}")
        print(f"[seed] KB vectors complete. new_vectors={kv} (dim=256)")
        print(f"[seed] Users seed complete. Created {u} new user(s).")

# Legacy shim expected by older code
def seed_users():
    run_seed()