# app/admin_routes.py
from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from .db import SessionLocal
from .models import AssessmentRun, AssessmentTurn, PillarResult

admin = APIRouter(prefix="/admin", tags=["admin"])

@admin.get("/runs", response_class=HTMLResponse)
def list_runs(limit: int = 50):
    with SessionLocal() as s:
        runs = s.query(AssessmentRun).order_by(AssessmentRun.id.desc()).limit(limit).all()
        rows = []
        for r in runs:
            rows.append(
                f"<tr>"
                f"<td><a href='/admin/runs/{r.id}'>#{r.id}</a></td>"
                f"<td>{r.user_id}</td>"
                f"<td>{r.started_at}</td>"
                f"<td>{'✓' if r.is_completed else '…'}</td>"
                f"<td>{','.join(r.pillars or [])}</td>"
                f"<td>{r.model_name}</td>"
                f"<td>{r.kb_version}</td>"
                f"</tr>"
            )
        html = (
            "<h2>Assessment Runs</h2>"
            "<table border='1' cellpadding='6' cellspacing='0'>"
            "<tr><th>ID</th><th>User</th><th>Started</th><th>Done</th><th>Pillars</th><th>Model</th><th>KB</th></tr>"
            + "".join(rows) + "</table>"
        )
        return HTMLResponse(html)

@admin.get("/runs/{run_id}", response_class=HTMLResponse)
def run_detail(run_id: int):
    with SessionLocal() as s:
        run = s.get(AssessmentRun, run_id)
        if not run:
            raise HTTPException(404, "Run not found")
        turns = s.query(AssessmentTurn).filter(AssessmentTurn.run_id == run_id).order_by(AssessmentTurn.idx.asc()).all()
        results = s.query(PillarResult).filter(PillarResult.run_id == run_id).all()

        turn_rows = []
        for t in turns:
            retr = t.retrieval or []
            retr_html = "<br>".join([f"<code>{x.get('id')}</code> <em>{x.get('type')}</em>: {x.get('text','')[:160]}…" for x in retr])
            deltas_html = "<pre style='white-space:pre-wrap'>" + (str(t.deltas) if t.deltas else "") + "</pre>"
            turn_rows.append(
                "<tr>"
                f"<td>{t.idx}</td>"
                f"<td>{t.pillar}</td>"
                f"<td>{t.concept_key or ''}</td>"
                f"<td>{'clarifier' if t.is_clarifier else ''}</td>"
                f"<td>{(t.assistant_q or '')[:200]}</td>"
                f"<td>{(t.user_a or '')[:200]}</td>"
                f"<td>{retr_html}</td>"
                f"<td><pre style='white-space:pre-wrap'>{(t.llm_raw or '')[:400]}</pre></td>"
                f"<td>{t.action or ''}</td>"
                f"<td>{deltas_html}</td>"
                f"<td>{'' if t.confidence is None else t.confidence}</td>"
                "</tr>"
            )

        res_rows = []
        for r in results:
            res_rows.append(
                "<tr>"
                f"<td>{r.pillar}</td>"
                f"<td>{r.level}</td>"
                f"<td>{r.confidence}</td>"
                f"<td><pre style='white-space:pre-wrap'>" + (str(r.coverage)[:400]) + "</pre></td>"
                f"<td><pre style='white-space:pre-wrap'>" + (r.summary_msg or "") + "</pre></td>"
                "</tr>"
            )

        html = (
            f"<h2>Run #{run.id} — user {run.user_id}</h2>"
            f"<p>Started: {run.started_at} | Completed: {run.is_completed} | Model: {run.model_name} | KB: {run.kb_version}</p>"
            "<h3>Turns</h3>"
            "<table border='1' cellpadding='6' cellspacing='0'>"
            "<tr><th>#</th><th>Pillar</th><th>Concept</th><th>Clarifier?</th><th>Assistant Q</th><th>User A</th><th>Retrieval</th><th>LLM Raw</th><th>Action</th><th>Deltas</th><th>Conf</th></tr>"
            + "".join(turn_rows) + "</table>"
            "<h3>Pillar Results</h3>"
            "<table border='1' cellpadding='6' cellspacing='0'>"
            "<tr><th>Pillar</th><th>Level</th><th>Confidence</th><th>Coverage</th><th>Summary</th></tr>"
            + "".join(res_rows) + "</table>"
        )
        return HTMLResponse(html)
