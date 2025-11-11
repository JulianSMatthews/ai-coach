# app/retriever.py
from __future__ import annotations
from typing import List, Dict, Any
from sqlalchemy import text
from .db import SessionLocal
from .models import KBVector, HAS_PGVECTOR, KBSnippet
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
        if HAS_PGVECTOR:
            sql = text("""
                SELECT id, type, locale
                FROM kb_vectors
                WHERE pillar_key=:pillar AND concept_key=:concept AND locale=:locale
                ORDER BY embedding <=> :qvec
                LIMIT :k
            """)
            rows = s.execute(sql, {"pillar": pillar, "concept": concept_key, "locale": locale, "qvec": qvec, "k": top_k}).fetchall()
            ids = [r[0] for r in rows]
            if ids:
                snips = {sn.id: sn for sn in s.query(KBSnippet).filter(KBSnippet.id.in_(ids)).all()}
                for sid, typ, loc in rows:
                    sn = snips.get(sid)
                    if sn:
                        out.append({"id": sid, "type": typ, "text": sn.text, "locale": loc})
        else:
            vecs = s.query(KBVector).filter(
                KBVector.pillar_key==pillar, KBVector.concept_key==concept_key, KBVector.locale==locale
            ).all()
            scored = [(_cosine(v.embedding, qvec), v.id, v.type, v.locale) for v in vecs]
            scored.sort(reverse=True)
            ids = [sid for _, sid, _, _ in scored[:top_k]]
            snips = {sn.id: sn for sn in s.query(KBSnippet).filter(KBSnippet.id.in_(ids)).all()}
            for sc, sid, typ, loc in scored[:top_k]:
                sn = snips.get(sid)
                if sn:
                    out.append({"id": sid, "type": typ, "text": sn.text, "score": sc, "locale": loc})
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
