# app/retriever.py
from __future__ import annotations
from typing import List, Dict, Any
from .db import SessionLocal
from .models import KBVector, KBSnippet
from .llm import embed_text

def _cosine(a: list[float], b: list[float]) -> float:
    import math
    dot = sum(x*y for x, y in zip(a, b))
    na = math.sqrt(sum(x*x for x in a)) or 1.0
    nb = math.sqrt(sum(y*y for y in b)) or 1.0
    return dot / (na * nb)

def retrieve_snippets(pillar: str, concept_key: str, query_text: str, locale: str = "en-GB", top_k: int = 8) -> List[Dict[str, Any]]:
    qvec = embed_text(query_text)
    out: List[Dict[str, Any]] = []
    with SessionLocal() as s:
        rows = (
            s.query(KBVector, KBSnippet)
            .join(KBSnippet, KBVector.snippet_id == KBSnippet.id)
            .filter(KBSnippet.pillar_key == pillar, KBSnippet.concept_code == concept_key)
            .all()
        )
        scored = [(_cosine(v.embedding, qvec), sn.id, sn) for v, sn in rows]
        scored.sort(reverse=True)
        for sc, sid, sn in scored[:top_k]:
            out.append(
                {
                    "id": sid,
                    "type": "snippet",
                    "title": sn.title,
                    "text": sn.text,
                    "score": sc,
                    "locale": locale,
                }
            )
    return out

def diversify(snippets: List[Dict[str, Any]], want_types: List[str] | None = None, max_total: int = 5) -> List[Dict[str, Any]]:
    want_types = want_types or ["rubric","definition","howto","example_high","example_moderate"]
    picked: List[Dict[str, Any]] = []
    for t in want_types:
        for sn in snippets:
            if sn.get("type") == t and sn not in picked:
                picked.append(sn); break
            if len(picked) >= max_total: return picked[:max_total]
    for sn in snippets:
        if sn not in picked:
            picked.append(sn)
        if len(picked) >= max_total: break
    return picked[:max_total]
