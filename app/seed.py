# app/seed.py
from __future__ import annotations
import os, json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
from sqlalchemy import select, func
from sqlalchemy.exc import SQLAlchemyError

from .db import SessionLocal, engine
import app.models as models       # ensures models are mapped
from app.kb_ingest import upsert_kb

# Resolve metadata (SQLAlchemy or SQLModel)
Base = getattr(models, "Base", None)
metadata = getattr(Base, "metadata", None)

# ---------- USERS ------------------------------------------------------------

@dataclass
class TestUser:
    name: str
    phone_e164: str  # store +44… (no 'whatsapp:')
    tz: str

def _normalize_phone(p: str) -> str:
    p = (p or "").strip()
    return p[len("whatsapp:"):] if p.startswith("whatsapp:") else p

def _get_seed_users() -> list[TestUser]:
    u1 = TestUser(
        os.getenv("SEED_USER1_NAME", os.getenv("SEED_USER_NAME", "Julian")),
        _normalize_phone(os.getenv("SEED_USER1_PHONE", os.getenv("SEED_USER_PHONE", "whatsapp:+447710307026"))),
        os.getenv("SEED_USER1_TZ", os.getenv("SEED_USER_TZ", "Europe/London")),
    )
    u2 = TestUser(
        os.getenv("SEED_USER2_NAME", "Rhys"),
        _normalize_phone(os.getenv("SEED_USER2_PHONE", "whatsapp:+447860362908")),
        os.getenv("SEED_USER2_TZ", "Europe/London"),
    )
    # De-dupe by phone
    seen, users = set(), []
    for u in (u1, u2):
        if u.phone_e164 and u.phone_e164 not in seen:
            users.append(u)
            seen.add(u.phone_e164)
    return users

def seed_users():
    if os.getenv("SEED_TEST_USER") != "1":
        print("[seed] SEED_TEST_USER!=1; skipping user seeding.")
        return

    # Create tables (safe to call repeatedly)
    if metadata is not None:
        try:
            metadata.create_all(bind=engine)
        except TypeError:
            metadata.create_all(engine)

    # Model must exist
    try:
        User = models.User
    except AttributeError as e:
        raise RuntimeError("app.models must define a User model class") from e

    users = _get_seed_users()
    created = 0
    with SessionLocal() as db:
        for u in users:
            exists = db.query(User).filter_by(phone=u.phone_e164).first()
            if exists:
                print(f"[seed] User already exists: {exists.name} ({exists.phone})")
                continue
            db.add(User(name=u.name, phone=u.phone_e164, tz=u.tz))
            created += 1
        db.commit()
    print(f"[seed] Users seed complete. Created {created} new user(s).")

# ---------- CONCEPTS & KB ----------------------------------------------------

# Convenience getters
Pillar = models.Pillar
Concept = models.Concept
ConceptRubric = models.ConceptRubric
ConceptQuestion = models.ConceptQuestion
ConceptClarifier = models.ConceptClarifier

CONCEPTS_PATH = os.getenv("AI_COACH_CONCEPTS_PATH", "kb/concepts.json")
KB_PATH       = os.getenv("AI_COACH_KB_PATH", "kb/kb_snippets.json")

def _safe_list(v: Any) -> List[str]:
    if isinstance(v, list): return [str(x) for x in v]
    if isinstance(v, str):  return [v]
    return []

def _get_or_create_pillar(s, key: str, name: Optional[str]) -> Pillar:
    key = (key or "").strip().lower()
    pil = s.query(Pillar).filter_by(key=key).first()
    if pil:
        if name and not pil.name:
            pil.name = name
        if pil.active is None:
            pil.active = True
        s.flush()
        return pil
    pil = Pillar(key=key, name=name or key.title(), sort_order=0, active=True)
    s.add(pil); s.flush()
    return pil

def _upsert_concept(s, pillar_id: int, c: Dict[str, Any], default_version: str) -> Concept:
    key   = (c.get("id") or c.get("key") or "").strip().lower()
    name  = c.get("name") or key.replace("_"," ").title()
    desc  = c.get("description", "")
    weight= c.get("weight", 1.0)
    version = (c.get("version") or default_version or "1.0.0").strip()

    con = s.query(Concept).filter_by(pillar_id=pillar_id, key=key).first()
    if con:
        con.name = con.name or name
        if desc and not con.description:
            con.description = desc
        try: con.weight = float(weight or con.weight or 1.0)
        except Exception: pass
        if not con.version:
            con.version = version
        s.flush()
        return con

    con = Concept(
        pillar_id=pillar_id, key=key, name=name,
        weight=float(weight or 1.0), description=desc or "",
        sort_order=0, active=True, version=version
    )
    s.add(con); s.flush()
    return con

def _upsert_rubrics(s, concept_id: int, rubric: Dict[str, Any]):
    for lvl in ("low", "moderate", "high"):
        r = (rubric or {}).get(lvl, {})
        band = r.get("band") or r.get("range") or [0.0, 0.0]
        try:
            bmin = float(band[0]) if len(band) > 0 else 0.0
            bmax = float(band[1]) if len(band) > 1 else 0.0
        except Exception:
            bmin, bmax = 0.0, 0.0
        anchors  = "\n".join(_safe_list(r.get("anchors")))
        examples = "\n".join(_safe_list(r.get("examples")))

        row = s.query(ConceptRubric).filter_by(concept_id=concept_id, level=lvl).first()
        if row:
            row.band_min = bmin; row.band_max = bmax
            row.anchors = anchors; row.examples = examples
        else:
            s.add(ConceptRubric(
                concept_id=concept_id, level=lvl,
                band_min=bmin, band_max=bmax,
                anchors=anchors, examples=examples
            ))

def _existing_texts(s, model, concept_id: int) -> set[str]:
    rows = s.execute(select(model.text).where(model.concept_id == concept_id)).scalars().all()
    return {(r or "").strip() for r in rows}

def _upsert_questions(s, concept_id: int, qs: List[str]) -> int:
    if not qs: return 0
    existing = _existing_texts(s, ConceptQuestion, concept_id)
    added = 0
    for q in qs:
        qt = (q or "").strip()
        if not qt or qt in existing: continue
        s.add(ConceptQuestion(concept_id=concept_id, text=qt, active=True))
        added += 1
    return added

def _upsert_clarifiers(s, concept_id: int, qs: List[str]) -> int:
    if not qs: return 0
    existing = _existing_texts(s, ConceptClarifier, concept_id)
    added = 0
    for q in qs:
        qt = (q or "").strip()
        if not qt or qt in existing: continue
        s.add(ConceptClarifier(concept_id=concept_id, text=qt, active=True))
        added += 1
    return added

def _db_has_version(s, version: str) -> bool:
    if not version: return False
    count = s.execute(
        select(func.count()).select_from(Concept).where(Concept.version == version)
    ).scalar() or 0
    return count > 0

def seed_concepts_and_kb(concepts_path: str = CONCEPTS_PATH, kb_path: str = KB_PATH) -> Tuple[int,int,int,int]:
    """
    Returns (pillars_upserted, concepts_upserted, questions_added, clarifiers_added)
    """
    with open(concepts_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    version = str(data.get("version") or "1.0.0").strip()
    pillars = data.get("pillars") or []

    p_up = c_up = q_add = cl_add = 0
    with SessionLocal() as s:
        if _db_has_version(s, version):
            print(f"[seed] Concepts already at version {version}; skipping.")
            return (0, 0, 0, 0)

        for p in pillars:
            pil = _get_or_create_pillar(s, p.get("id") or p.get("key"), p.get("name"))
            p_up += 1

            for c in (p.get("concepts") or []):
                con = _upsert_concept(s, pil.id, c, version); c_up += 1
                _upsert_rubrics(s, con.id, c.get("rubric") or {})
                q_add += _upsert_questions(s, con.id, c.get("question_bank") or [])
                cl_add += _upsert_clarifiers(s, con.id, c.get("clarifiers") or [])
        s.commit()

    # Upsert KB embeddings/snippets (idempotent inside upsert_kb)
    try:
        upsert_kb(kb_path, version=version)
        print(f"[seed] KB upsert complete from {kb_path}.")
    except Exception as e:
        print(f"[seed] KB upsert failed: {e}")

    print(f"[seed] Concepts seed complete. pillars={p_up} concepts={c_up} new_questions={q_add} new_clarifiers={cl_add}")
    return (p_up, c_up, q_add, cl_add)

def seed_concepts_and_kb_if_empty():
    """
    Idempotent entrypoint for app startup: only seeds if concepts/KB look empty.
    """
    # Ensure tables exist if called standalone
    if metadata is not None:
        try:
            metadata.create_all(bind=engine)
        except TypeError:
            metadata.create_all(engine)

    with SessionLocal() as s:
        concepts_count = s.execute(select(func.count()).select_from(Concept)).scalar() or 0
    try:
        from sqlalchemy import text
        with engine.connect() as conn:
            kb_count = conn.execute(text("SELECT COUNT(*) FROM kb_vectors")).scalar() or 0
    except Exception:
        kb_count = 0

    if concepts_count > 0 and kb_count > 0:
        print("[seed] Concepts/KB already present; skipping.")
        return

    seed_concepts_and_kb()