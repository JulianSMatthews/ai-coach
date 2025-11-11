# app/review_log.py
from __future__ import annotations
from typing import List, Dict, Any, Optional
from datetime import datetime
from .db import SessionLocal
from .models import AssessmentRun, AssessmentTurn, ConceptDelta, PillarResult
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError

def start_run(user_id: int, pillars: List[str], model_name: str, kb_version: str, rubric_version: str) -> int:
    with SessionLocal() as s:
        run = AssessmentRun(
            user_id=user_id, pillars=pillars, model_name=model_name,
            kb_version=kb_version, rubric_version=rubric_version, is_completed=False
        )
        s.add(run); s.commit(); s.refresh(run)
        return run.id
def log_turn(
    run_id: int, idx: int, pillar: str, concept_key: Optional[str],
    assistant_q: Optional[str], user_a: Optional[str],
    retrieval: Optional[List[Dict[str, Any]]],
    llm_raw: Optional[str], action: Optional[str],
    deltas: Optional[Dict[str, Any]], confidence: Optional[float],
    is_clarifier: bool = False,
    before_after: Optional[List[Dict[str, Any]]] = None,
) -> int:
    """
    Write an AssessmentTurn. If the provided (run_id, idx) collides (e.g., due to webhook retries or races),
    retry once with idx = MAX(idx)+1 from the DB for this run_id.
    """
    with SessionLocal() as s:
        turn = AssessmentTurn(
            run_id=run_id, idx=idx, pillar=pillar, concept_key=concept_key or None,
            assistant_q=assistant_q, user_a=user_a, retrieval=retrieval,
            llm_raw=llm_raw, action=action, deltas=deltas, confidence=confidence,
            is_clarifier=is_clarifier
        )
        s.add(turn)
        try:
            s.commit()
        except IntegrityError:
            # Another process used this idx; retry with DB-derived next idx
            s.rollback()
            next_idx = s.execute(
                select(func.coalesce(func.max(AssessmentTurn.idx), 0))
                .where(AssessmentTurn.run_id == run_id)
            ).scalar_one() + 1
            turn.idx = next_idx
            s.add(turn)
            s.commit()

        s.refresh(turn)

        if before_after:
            for item in before_after:
                row = ConceptDelta(
                    turn_id=turn.id, pillar=pillar, concept_key=item["concept_key"],
                    score_before=item.get("before"), delta=item.get("delta", 0.0),
                    score_after=item.get("after"), note=item.get("note", "")
                )
                s.add(row)
            s.commit()

        return turn.id

def finish_pillar(run_id: int, pillar: str, level: str, confidence: float, coverage: Dict[str, Any], summary_msg: str):
    with SessionLocal() as s:
        pr = PillarResult(
            run_id=run_id, pillar=pillar, level=level, confidence=confidence,
            coverage=coverage, summary_msg=summary_msg
        )
        s.add(pr); s.commit()

def finish_run(run_id: int):
    with SessionLocal() as s:
        run = s.get(AssessmentRun, run_id)
        if run:
            run.is_completed = True
            run.finished_at = datetime.utcnow()
            s.commit()
