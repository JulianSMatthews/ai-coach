# app/kb_ingest.py
from __future__ import annotations
import json
import re
from typing import List, Dict, Any, Optional

from sqlalchemy import select  # (kept if you use it elsewhere)
from .db import SessionLocal
from .models import KBSnippet, KBVector, EMBEDDING_DIM
from .llm import embed_text


def _coalesce(d: Dict[str, Any], *keys, default=None):
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return default


def _derive_title(text: str, fallback: str) -> str:
    """First sentence up to ~80 chars; fallback to id."""
    if not text:
        return fallback
    first = re.split(r"(?<=[.!?])\s+", text.strip(), maxsplit=1)[0]
    return (first[:80] or fallback).strip()


def _version_str(v: Optional[str], fallback: str) -> str:
    s = str(v or fallback)
    return s[:16]  # KBVector.version is String(16)


def upsert_kb(snippets_path: str, version: str = "1.0.0", locale_default: str = "en-GB"):
    """
    Load snippets JSON and upsert into KBSnippet + KBVector.

    Accepts both legacy and new JSON keys:
      - pillar | pillar_key
      - concept_id | concept_key
    """
    with open(snippets_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    snips: List[Dict[str, Any]] = data.get("snippets", [])
    root_version = data.get("version", version)

    with SessionLocal() as s:
        for sn in snips:
            # Required fields
            sid = sn["id"]
            text = (sn.get("text") or "").strip()
            if not text:
                # Skip empty text; you can log if desired
                continue

            # Accept both legacy and new naming
            pillar_key = _coalesce(sn, "pillar_key", "pillar")
            concept_key = _coalesce(sn, "concept_key", "concept_id")
            if not pillar_key or not concept_key:
                # Skip malformed entries
                continue

            typ = sn.get("type", "definition")
            locale = sn.get("locale") or locale_default
            tags_list = sn.get("tags") or []
            tags_csv = ",".join([str(t) for t in tags_list])[:250]
            weight = float(sn.get("weight", 1.0))
            ver = _version_str(sn.get("version"), root_version)

            # ---------- KBSnippet UPSERT ----------
            snippet_meta = {
                "pillar_key": pillar_key,
                "concept_key": concept_key,
                "type": typ,
                "locale": locale,
                "tags": tags_csv,
                "weight": weight,
                "version": ver,
            }
            row = s.get(KBSnippet, sid)
            if not row:
                row = KBSnippet(id=sid, text=text, **snippet_meta)
                s.add(row)
            else:
                row.text = text
                for k, v in snippet_meta.items():
                    setattr(row, k, v)

            # ---------- Embedding ----------
            vec = embed_text(text)  # -> List[float], length EMBEDDING_DIM
            if not isinstance(vec, list) or len(vec) != EMBEDDING_DIM:
                raise ValueError(f"Embedding dimension mismatch (got {len(vec)}, expected {EMBEDDING_DIM})")

            # ---------- KBVector UPSERT (aligns with your model) ----------
            title = sn.get("title") or _derive_title(text, fallback=sid)

            kbv = s.get(KBVector, sid)
            if not kbv:
                kbv = KBVector(
                    id=sid,
                    pillar_key=pillar_key,
                    concept_key=concept_key,
                    type=typ,
                    locale=locale,
                    embedding=vec,       # Vector(1536), NOT NULL
                    title=title,         # NOT NULL
                    text=text,           # NOT NULL
                    version=ver,         # String(16)
                    # created_at uses model default if defined
                )
                s.add(kbv)
            else:
                kbv.pillar_key = pillar_key
                kbv.concept_key = concept_key
                kbv.type = typ
                kbv.locale = locale
                kbv.embedding = vec
                kbv.title = title
                kbv.text = text
                kbv.version = ver

        s.commit()