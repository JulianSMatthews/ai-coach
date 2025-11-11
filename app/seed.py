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
import os
import hashlib, math, random

from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import SessionLocal
from .models import (
    User,
    Pillar,
    Concept,
    ConceptQuestion,
    KbSnippet,
    KbVector,
    Club,
    ADMIN_ROLE_MEMBER,
    ADMIN_ROLE_CLUB,
    ADMIN_ROLE_GLOBAL,
)

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
        "processed_food":   "Processed food",
    },
    "training": {
        "cardio_frequency":     "Cardio frequency",
        "strength_training":    "Strength training",
        "flexibility_mobility": "Flexibility & mobility",
    },
    "resilience": {
        "emotional_regulation":   "Emotional regulation",
        "positive_connection":    "Positive connection & enjoyment",
        "stress_recovery":        "Stress recovery",
        "optimism_perspective":   "Optimism & perspective",
        "support_openness":       "Support & openness",
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
            "primary": "In the last 7 days, how many portions of fruit and vegetables did you eat on average per day? For reference: 1 portion = 1 apple or banana, 1 fist-sized serving of vegetables, or 1 handful of salad or berries."
        },
        "hydration": {
            "primary": "Thinking about the last 7 days, how much water did you usually drink per day? For reference: 1 glass = 250ml, 1 small bottle = 500ml."
        },
        "processed_food": {
            "primary": "In the last 7 days, how many portions of processed food did you eat on average per day? Examples: 1 portion = a chocolate bar, 1 can of fizzy drink, 1 handful of sweets, or a pastry."
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
        "emotional_regulation": {
            "primary": "In the past 7 days, on how many days did you feel calm and in control of your emotions for most of the day?"
        },
        "positive_connection": {
            "primary": "In the past 7 days, on how many days did you do something that made you feel genuinely good — either by taking time for yourself or connecting with someone you enjoy spending time with?"
        },
        "stress_recovery": {
            "primary": "In the past 7 days, on how many days did you take a short break to relax, breathe deeply, or reset when you felt stressed or tired?"
        },
        "optimism_perspective": {
            "primary": "In the past 7 days, on how many days did you feel able to stay positive and keep things in perspective when challenges arose?"
        },
        "support_openness": {
            "primary": "In the past 7 days, on how many days did you actively connect with others to discuss your goals, progress, or challenges?"
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
            {"title": "Portion baseline", "text": "Aim ~3–4 protein portions/day; 1 portion = palm of lean protein, 2 eggs, or 1 cup beans/lentils."},
            {"title": "Scoring cue (0–5/day)", "text": "0–1/day = low, 2–3/day = fair, 3–4/day = good, 5/day = excellent; spread evenly across meals."},
        ],
        "fruit_veg": [
            {"title": "Target & variety", "text": "≥5 portions/day; mix colours for fibre and micronutrients."},
            {"title": "Make it easy", "text": "Front-load fruit/veg into the first two meals; batch-cook to stay consistent."},
        ],
        "hydration": [
            {"title": "Daily target", "text": "Women: 2–3 L/day; Men: 3–4 L/day (more with heat/training). Pale-straw urine ≈ good hydration."},
            {"title": "Scoring cue (0–6 L/day)", "text": "2–4 L/day = strong; spread intake through the day; pair sips with routine cues."},
        ],
        "processed_food": [
            {"title": "Definition & unit", "text": "UPFs include crisps, sweets, pastries, ready meals, sugary drinks; count portions per day."},
            {"title": "Scoring cue (reverse; 0–4+/day)", "text": "0/day = best, 0–1/day = good, 2–3/day = fair, ≥4/day = poor; use an 80/20 approach and reward gradual reduction."},
        ],
    },
    "training": {
        "cardio_frequency": [
            {"title": "Aerobic baseline", "text": "Do ≥20 min most days in Zone 2–3; include 1–2 sessions/week in Zone 4–5 for range."},
            {"title": "Scoring cue (0–5 days/wk)", "text": "0–1 days = low, 2–3 = fair, 4 = good, 5 = excellent; 150–300 min/week moderate (or 75–150 vigorous) is the weekly anchor."},
        ],
        "strength_training": [
            {"title": "Dose & structure", "text": "2–3 full-body sessions/week; cover push, pull, squat, hinge, carry, core."},
            {"title": "Scoring cue (0–4 sessions/wk)", "text": "1 = low, 2 = fair, 3 = good, 4 = excellent if recovery (sleep/energy/soreness) is solid."},
        ],
        "flexibility_mobility": [
            {"title": "Baseline habit", "text": "≥10 minutes on ≥3 days/week; link to a fixed time (post-workout or pre-bed)."},
            {"title": "Scoring cue (0–5 days/wk)", "text": "Consistency beats one-off long sessions; more days at 10–15 min score higher."},
        ],
    },
    "resilience": {
        "emotional_regulation": [
            {"title": "Micro-resets", "text": "Take 5–10 min walks or mindful breaks; use 2–3 presence prompts/day (breath, posture, body scan)."},
            {"title": "Scoring cue (0–7 days/wk)", "text": "Reward intentional regulation efforts and consistency, not the absence of difficult emotion."},
        ],
        "positive_connection": [
            {"title": "Gratitude & contact", "text": "Note 2–3 gratitudes/day; brief check-ins (message/call) count as positive connection."},
            {"title": "Scoring cue (0–7 days/wk)", "text": "Intentional engagement and gratitude both improve scores; more days = higher."},
        ],
        "stress_recovery": [
            {"title": "Active coping", "text": "Use journaling and reach out to supports to reduce overload; short resets beat avoidance."},
            {"title": "Scoring cue (0–7 days/wk)", "text": "Consistent use of a coping strategy scores higher than infrequent, long sessions."},
        ],
        "optimism_perspective": [
            {"title": "Reframe & evidence", "text": "Widen the view: ask what else could be true; track one small win daily."},
            {"title": "Scoring cue (0–7 days/wk)", "text": "Regular practice of reframing/perspective-taking increases the score."},
        ],
        "support_openness": [
            {"title": "Ask early & specifically", "text": "Share goals/challenges before they build; make specific asks or check-ins."},
            {"title": "Scoring cue (0–7 days/wk)", "text": "Willingness to request or accept support earlier and more consistently scores higher."},
        ],
    },
    "recovery": {
        "sleep_duration": [
            {"title": "Hours & anchor", "text": "Most adults benefit from 7–9 h/night; keep a consistent wake time."},
            {"title": "Scoring cue (0–7 nights/wk)", "text": "More nights at ≥7 h score higher; if fatigued, go to bed earlier rather than sleeping in."},
        ],
        "sleep_quality": [
            {"title": "Wind-down routine", "text": "Dim lights, quiet time, breathing/reading; avoid screens ≥60 min before bed."},
            {"title": "Scoring cue (0–7 mornings/wk)", "text": "Improvement = faster sleep onset, deeper rest, fewer night wakes; more mornings feeling refreshed score higher."},
        ],
        "bedtime_consistency": [
            {"title": "Circadian window", "text": "Keep sleep/wake within ±60 min to support circadian rhythm."},
            {"title": "Scoring cue (0–7 nights/wk)", "text": "Reward stabilising a regular schedule over rigid perfection; consistency > total hours for circadian alignment."},
        ],
    },
}
# Clubs to seed (you can change names/slugs as you like)
CLUBS = [
    ("healthsense",   "HealthSense HQ"),
    ("anytime-eden",  "Anytime Fitness – Eden"),
]
DEMO_USERS = [
    {
        "first_name": "Julian",
        "surname": "Matthews",
        "phone": "+447710307026",
        "is_superuser": True,
        "admin_role": ADMIN_ROLE_GLOBAL,
        "club_slug": "healthsense",
    },
    {
        "first_name": "Rhys",
        "surname": "Williams",
        "phone": "+447860362908",
        "is_superuser": True,
        "admin_role": ADMIN_ROLE_CLUB,
        "club_slug": "healthsense",
    },
]

def _seed_admin_role(entry: dict) -> str:
    role = (entry.get("admin_role") or "").strip().lower()
    if role in {ADMIN_ROLE_MEMBER, ADMIN_ROLE_CLUB, ADMIN_ROLE_GLOBAL}:
        return role
    return ADMIN_ROLE_GLOBAL if bool(entry.get("is_superuser")) else ADMIN_ROLE_MEMBER

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
        "fruit_veg":      {"zero_score": 0, "max_score": 5},
        "hydration":      {"zero_score": 0, "max_score": 6},
        "processed_food": {"zero_score": 4, "max_score": 0},  # days/week; reverse (7 days bad=0, 0 days best=100)
    },
    "training": {
        "cardio_frequency":     {"zero_score": 0, "max_score": 5},
        "strength_training":    {"zero_score": 0, "max_score": 4},
        "flexibility_mobility": {"zero_score": 0, "max_score": 5},
    },
    "resilience": {
        "emotional_regulation":   {"zero_score": 0, "max_score": 7},
        "positive_connection":    {"zero_score": 0, "max_score": 7},
        "stress_recovery":        {"zero_score": 0, "max_score": 7},
        "optimism_perspective":   {"zero_score": 0, "max_score": 7},
        "support_openness":       {"zero_score": 0, "max_score": 7},
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

 
def upsert_clubs(session: Session) -> int:
    created = 0
    for slug, name in CLUBS:
        row = session.execute(select(Club).where(Club.slug == slug)).scalar_one_or_none()
        if not row:
            session.add(Club(slug=slug, name=name, is_active=True))
            created += 1
    session.commit()
    return created

def get_club_by_slug(session: Session, slug: str) -> Club | None:
    return session.execute(select(Club).where(Club.slug == slug, Club.is_active == True)).scalar_one_or_none()

def upsert_demo_users(session: Session) -> int:
    now = datetime.utcnow()
    created = 0
    for u in DEMO_USERS:
        phone = u.get("phone")
        if not phone:
            continue
        club_slug = (u.get("club_slug") or "healthsense").strip()
        club = get_club_by_slug(session, club_slug)

        if not club:
            # If a referenced club wasn't pre-seeded, create it on the fly
            club = Club(
                slug=club_slug,
                name=club_slug.replace("-", " ").title(),
                is_active=True
            )
            session.add(club)
            session.flush()  # get club.id without committing the whole transaction

        # Always proceed to user upsert (regardless of whether club existed)
        row = session.execute(select(User).where(User.phone == phone)).scalar_one_or_none()
        if not row:
            session.add(User(
                club_id=club.id,
                first_name=u.get("first_name"),
                surname=u.get("surname"),
                phone=phone,
                is_superuser=bool(u.get("is_superuser")),
                admin_role=_seed_admin_role(u),
                **(
                    {"created_on": now, "updated_on": now}
                    if "created_on" in User.__table__.columns and "updated_on" in User.__table__.columns
                    else {}
                ),
            ))
            created += 1
        else:
            updated = False
            # Ensure club is set; if missing, set it (do not overwrite if different)
            if getattr(row, "club_id", None) is None:
                row.club_id = club.id
                updated = True
            # Keep superuser flag in sync (promote to True if seed says so)
            if bool(u.get("is_superuser")) and not getattr(row, "is_superuser", False):
                row.is_superuser = True
                updated = True
            target_role = _seed_admin_role(u)
            if getattr(row, "admin_role", None) != target_role:
                row.admin_role = target_role
                updated = True
            # Ensure first_name/surname are set / corrected
            fn = u.get("first_name")
            sn = u.get("surname")
            if fn is not None and getattr(row, "first_name", None) != fn:
                row.first_name = fn
                updated = True
            if sn is not None and getattr(row, "surname", None) != sn:
                row.surname = sn
                updated = True
            if updated and "updated_on" in User.__table__.columns.keys():
                row.updated_on = now

    session.commit()
    return created

def run_seed() -> None:
    """
    Full seed entrypoint. Safely seeds in the right order and won't crash
    if a helper is missing (it will just skip that step).
    """

    with SessionLocal() as s:
        try:
            # 1) Clubs first (so users.club_id NOT NULL can be satisfied)
            cl = upsert_clubs(s) if 'upsert_clubs' in globals() else 0

            # 2) Pillars / Concepts / Questions
            p  = upsert_pillars(s) if 'upsert_pillars' in globals() else 0
            c  = upsert_concepts(s) if 'upsert_concepts' in globals() else 0
            cq = upsert_concept_questions(s) if 'upsert_concept_questions' in globals() else 0

            # 3) KB snippets / vectors
            sn = upsert_kb_snippets(s) if 'upsert_kb_snippets' in globals() else 0
            kv = ensure_vectors_for_snippets(s, dim=256) if 'ensure_vectors_for_snippets' in globals() else 0

            # 4) Users last (requires clubs)
            u  = upsert_demo_users(s) if 'upsert_demo_users' in globals() else 0

            # Commit once at the end
            s.commit()

            total_concepts = sum(len(v) for v in CONCEPTS.values()) if 'CONCEPTS' in globals() else 'n/a'
            print(f"[seed] Clubs seed complete. new_clubs={cl}")
            print(f"[seed] KB upsert complete. new_snippets={sn}")
            print(f"[seed] Concepts seed complete. pillars={len(PILLARS) if 'PILLARS' in globals() else 'n/a'} "
                  f"concepts={total_concepts} new_concepts={c}")
            print(f"[seed] Concept questions upsert complete. new_questions={cq}")
            print(f"[seed] KB vectors complete. new_vectors={kv} (dim=256)")
            print(f"[seed] Users seed complete. Created {u} new user(s).")

        except Exception as e:
            s.rollback()
            print(f"[seed] ERROR during seeding: {e}")
            raise
