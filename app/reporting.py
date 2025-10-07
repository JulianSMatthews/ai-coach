# app/reporting.py
from __future__ import annotations

import os
from datetime import datetime, date, timedelta
from typing import Optional, Dict, Any, List, Tuple
import textwrap

from .db import SessionLocal
from .models import AssessmentRun, PillarResult, User, JobAudit, UserConceptState

def _audit(job: str, status: str = "ok", payload: Dict[str, Any] | None = None, error: str | None = None) -> None:
    try:
        print(f"[AUDIT] {job} status={status} payload={(payload or {})} err={error or ''}")
    except Exception:
        pass
    try:
        with SessionLocal() as s:
            s.add(JobAudit(job_name=job, status=status, payload=payload or {}, error=error or None))
            s.commit()
    except Exception:
        pass

# ──────────────────────────────────────────────────────────────────────────────
# Report generation (PDF via reportlab)
# ──────────────────────────────────────────────────────────────────────────────

def _reports_root_for_user(user_id: int) -> str:
    """
    Determine the filesystem directory where reports should be written.
    Uses REPORTS_DIR env var if set, otherwise ./public/reports/{user_id}.
    """
    base = os.getenv("REPORTS_DIR") or os.path.join(os.getcwd(), "public", "reports")
    path = os.path.join(base, str(user_id))
    os.makedirs(path, exist_ok=True)
    return path

# Global reports output directory (not per-user)
def _reports_root_global() -> str:
    """
    Global reports output directory. Uses REPORTS_DIR if set, otherwise ./public/reports
    """
    base = os.getenv("REPORTS_DIR") or os.path.join(os.getcwd(), "public", "reports")
    os.makedirs(base, exist_ok=True)
    return base


def _display_full_name(user: User) -> str:
    first = (getattr(user, "first_name", None) or "").strip()
    last = (getattr(user, "surname", None) or "").strip()
    full = f"{first} {last}".strip()
    if full:
        return full
    phone = (getattr(user, "phone", None) or "").strip()
    return phone or "User"

# Normalise date range helper
def _normalise_date_range(start: date | str | None, end: date | str | None) -> tuple[datetime, datetime, str, str]:
    """
    Accepts ISO date strings or date objects.
    Returns (start_dt_utc, end_dt_utc_inclusive, start_str, end_str)
    """
    def _to_date(d):
        if d is None:
            return None
        if isinstance(d, date) and not isinstance(d, datetime):
            return d
        if isinstance(d, datetime):
            return d.date()
        # assume ISO string
        return datetime.fromisoformat(str(d)).date()

    s = _to_date(start) or datetime.utcnow().date()
    e = _to_date(end) or s
    if e < s:
        s, e = e, s

    # Interpret range in UTC; end inclusive -> set to 23:59:59.999999
    start_dt = datetime(s.year, s.month, s.day, 0, 0, 0)
    end_dt = datetime(e.year, e.month, e.day, 23, 59, 59, 999999)
    return start_dt, end_dt, s.isoformat(), e.isoformat()

# Safe float conversion helper
def _to_float(x, default: float = 0.0) -> float:
    try:
        return float(x)
    except Exception:
        return default

def _today_str() -> str:
    # Use UTC so it's deterministic server-side
    return datetime.utcnow().strftime("%b %d, %Y")

def _pillar_order() -> List[str]:
    return ["nutrition", "training", "resilience", "recovery"]

def _title_for_pillar(p: str) -> str:
    return (p or "").replace("_", " ").title()

def _concept_display(code: str) -> str:
    return (code or "").replace("_", " ").title()

def _collect_report_data(run_id: int) -> Tuple[Optional[User], Optional[AssessmentRun], List[PillarResult]]:
    with SessionLocal() as s:
        run = s.query(AssessmentRun).filter(AssessmentRun.id == run_id).first()
        if not run:
            return None, None, []
        user = s.query(User).filter(User.id == run.user_id).first()
        pillars = (
            s.query(PillarResult)
             .filter(PillarResult.run_id == run_id)
             .all()
        )
        return user, run, pillars

def _score_color_rgb(v: int) -> tuple:
    """Map a 0–100 score to RGB color (green/amber/red). Amber uses bright orange (#FFA500)."""
    try:
        v = float(v)
    except Exception:
        v = 0.0
    if v >= 80:
        return (0.2, 0.6, 0.2)   # green
    if v >= 60:
        return (1.0, 0.65, 0.0)  # bright orange (#FFA500)
    return (0.8, 0.2, 0.2)       # red


def _pillar_symbol(key: str) -> str:
    m = {
        "nutrition": "[N]",
        "training": "[T]",
        "resilience": "[R]",
        "recovery": "[Rc]",
    }
    return m.get((key or "").lower(), "[•]")


# Hard-wrap text to card width and cap lines so it never spills the box
def _wrap_block(text: str, width: int = 42, max_lines: int = 4, bullet: str | None = None) -> str:
    if not text:
        return ""
    initial_indent = (bullet or "")
    subsequent_indent = ("  " if bullet else "")
    wrapped = textwrap.fill(
        text.strip(),
        width=width,
        initial_indent=initial_indent,
        subsequent_indent=subsequent_indent,
        break_long_words=True,
        break_on_hyphens=True,
        replace_whitespace=False,
    )
    lines = wrapped.splitlines()
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1].rstrip() + "…"
    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────────────────
# Detailed (admin) report – grouped by pillar with concept breakdown
# ──────────────────────────────────────────────────────────────────────────────

def _collect_detailed_report_data(user_id: int) -> Tuple[Optional[User], Optional[AssessmentRun], List[UserConceptState]]:
    """Fetch the latest AssessmentRun for the user and their concept state rows."""
    with SessionLocal() as s:
        run = (
            s.query(AssessmentRun)
             .filter(AssessmentRun.user_id == user_id)
             .order_by(AssessmentRun.started_at.desc())
             .first()
        )
        user = s.query(User).filter(User.id == user_id).first()
        rows: List[UserConceptState] = (
            s.query(UserConceptState)
             .filter(UserConceptState.user_id == user_id)
             .order_by(UserConceptState.updated_at.desc())
             .all()
        )
        return user, run, rows or []


def _write_detailed_pdf(path: str, user: User, run: AssessmentRun, rows: List[UserConceptState]) -> None:
    """
    Render a multi‑page, portrait PDF grouped by pillar, with a concept table:
      Columns: Concept | Score | Question | Answer | Confidence
      – Wrap long text in Concept/Question/Answer
      – Footer page numbers
      – Shows user name in Run Overview (no report path)
    """
    # Lazy import so the app can start without reportlab installed.
    try:
        from reportlab.platypus import BaseDocTemplate, Frame, PageTemplate, Paragraph, Spacer, Table, TableStyle
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib import colors
        from reportlab.lib.units import mm
    except Exception as e:
        raise RuntimeError(f"reportlab not available: {e!r}")

    _audit("detailed_report_start", "ok", {"user_id": getattr(user, "id", None), "run_id": getattr(run, "id", None), "out_pdf": path})

    styles = getSampleStyleSheet()
    wrap = ParagraphStyle('wrap', parent=styles['Normal'], fontSize=9, leading=11)

    # Group rows by pillar using configured order, then any others
    by_pillar: Dict[str, List[UserConceptState]] = {}
    for r in rows:
        pk = (getattr(r, 'pillar_key', None) or 'unknown').lower()
        by_pillar.setdefault(pk, []).append(r)

    def _on_page(c, doc):
        c.setFont("Helvetica", 8)
        c.drawRightString(200*mm, 15*mm, f"Page {c.getPageNumber()}")

    # Ensure directory exists
    out_dir = os.path.dirname(path)
    os.makedirs(out_dir, exist_ok=True)

    doc = BaseDocTemplate(path, pagesize=A4, leftMargin=36, rightMargin=36, topMargin=36, bottomMargin=36)
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id='normal')
    doc.addPageTemplates([PageTemplate(id='with_page_numbers', frames=frame, onPage=_on_page)])

    story: List[Any] = []

    # Title
    story.append(Paragraph("Assessment Report", styles["Title"]))
    story.append(Spacer(1, 10))

    # Run overview (user name; omit report path)
    story.append(Paragraph("<b>Run Overview</b>", styles["Heading2"]))
    display_name = _display_full_name(user)
    started = getattr(run, 'started_at', None) or ""
    finished = getattr(run, 'finished_at', None) or ""
    combined = getattr(run, 'combined_overall', None) or ""

    ov_rows = [
        ("Name", display_name),
        ("Started", str(started)),
        ("Finished", str(finished)),
        ("Combined Overall", str(combined)),
    ]
    ov_table = Table(ov_rows, hAlign="LEFT", colWidths=[120, 350])
    ov_table.setStyle(TableStyle([["GRID", (0,0), (-1,-1), 0.25, colors.grey]]))
    story.append(ov_table)
    story.append(Spacer(1, 14))

    # Pillar sections
    ordered = _pillar_order()
    pillar_keys = [p for p in ordered if p in by_pillar] + [p for p in by_pillar.keys() if p not in ordered]

    for pk in pillar_keys:
        grp = by_pillar.get(pk, [])
        # heading with avg score
        scores = [float(getattr(r, 'score')) for r in grp if getattr(r, 'score') is not None]
        avg = round(sum(scores)/len(scores)) if scores else None
        avg_txt = f"{avg}/100" if avg is not None else "Unscored"
        story.append(Paragraph(f"{_title_for_pillar(pk)} – Overall: {avg_txt}", styles["Heading2"]))

        data: List[List[Any]] = [["Concept", "Score", "Question", "Answer", "Confidence"]]
        for item in grp:
            concept = Paragraph(str(getattr(item, 'concept', '') or ''), wrap)
            sc = getattr(item, 'score', None)
            sc_txt = f"{int(round(float(sc)))}/100" if sc is not None else "Unscored"
            q = Paragraph(str(getattr(item, 'question', '') or ''), wrap)
            a = Paragraph(str(getattr(item, 'answer', '') or ''), wrap)
            cf = getattr(item, 'confidence', None)
            cf_txt = f"{float(cf):.2f}" if cf is not None else ""
            data.append([concept, sc_txt, q, a, cf_txt])

        table = Table(data, repeatRows=1, colWidths=[90, 45, 160, 120, 55])
        table.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (-1,0), colors.lightgrey),
            ("GRID", (0,0), (-1,-1), 0.25, colors.grey),
            ("VALIGN", (0,0), (-1,-1), "TOP"),
            ("ALIGN", (1,1), (1,-1), "RIGHT"),
        ]))
        story.append(table)
        story.append(Spacer(1, 12))

    doc.build(story)
    _audit("detailed_report_pdf_saved", "ok", {"pdf_path": path})

# ──────────────────────────────────────────────────────────────────────────────
# Summary (admin) report – date range across users/runs
# ──────────────────────────────────────────────────────────────────────────────
def _collect_summary_rows(start_dt: datetime, end_dt: datetime) -> list[dict]:
    """
    Collect assessment runs finished within [start_dt, end_dt] along with pillar scores.
    Returns list of dicts: {
      'name': str,
      'finished_at': datetime,
      'overall': float,
      'nutrition': float|None,
      'training': float|None,
      'resilience': float|None,
      'recovery': float|None,
      'user_id': int,
      'run_id': int,
    }
    """
    out: list[dict] = []
    with SessionLocal() as s:
        runs = (
            s.query(AssessmentRun, User)
             .join(User, AssessmentRun.user_id == User.id)
             .filter(AssessmentRun.finished_at.isnot(None))
             .filter(AssessmentRun.finished_at >= start_dt)
             .filter(AssessmentRun.finished_at <= end_dt)
             .order_by(AssessmentRun.finished_at.desc())
             .all()
        )
        if not runs:
            return out

        run_ids = [r.AssessmentRun.id for r in runs]
        # Load all pillar rows for these runs
        pillars = (
            s.query(PillarResult)
             .filter(PillarResult.run_id.in_(run_ids))
             .all()
        )
        by_run: dict[int, list[PillarResult]] = {}
        for pr in pillars:
            by_run.setdefault(getattr(pr, "run_id", 0), []).append(pr)

        for pair in runs:
            run: AssessmentRun = pair.AssessmentRun
            user: User = pair.User
            plist = by_run.get(getattr(run, "id", 0), [])

            # Map pillar -> overall score for that pillar
            pmap: dict[str, float] = {}
            for pr in plist:
                key = (getattr(pr, "pillar_key", "") or "").lower()
                pmap[key] = _to_float(getattr(pr, "overall", None), None)

            # Overall: prefer stored combined_overall, else mean of available pillars
            combined = getattr(run, "combined_overall", None)
            if combined is None:
                vals = [v for v in [pmap.get("nutrition"), pmap.get("training"), pmap.get("resilience"), pmap.get("recovery")] if isinstance(v, (int, float))]
                combined = round(sum(vals) / max(1, len(vals)), 2) if vals else 0.0
            else:
                combined = _to_float(combined, 0.0)

            out.append({
                "name": _display_full_name(user),
                "finished_at": getattr(run, "finished_at", None),
                "overall": combined,
                "nutrition": pmap.get("nutrition"),
                "training": pmap.get("training"),
                "resilience": pmap.get("resilience"),
                "recovery": pmap.get("recovery"),
                "user_id": getattr(user, "id", None),
                "run_id": getattr(run, "id", None),
            })
    return out

def _write_summary_pdf(path: str, start_str: str, end_str: str, rows: list[dict]) -> None:
    """
    A4 landscape PDF listing assessments with per-pillar scores and overall.
    """
    try:
        from reportlab.platypus import BaseDocTemplate, Frame, PageTemplate, Paragraph, Spacer, Table, TableStyle
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib import colors
    except Exception as e:
        raise RuntimeError(f"reportlab not available: {e!r}")

    os.makedirs(os.path.dirname(path), exist_ok=True)

    doc = BaseDocTemplate(path, pagesize=landscape(A4), leftMargin=36, rightMargin=36, topMargin=30, bottomMargin=24)
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="frame")

    def _on_page(c, _doc):
        c.setFont("Helvetica", 8)
        c.setFillGray(0.4)
        c.drawRightString(_doc.pagesize[0]-36, 18, f"Page {c.getPageNumber()}")

    doc.addPageTemplates([PageTemplate(id="with_footer", frames=[frame], onPage=_on_page)])
    styles = getSampleStyleSheet()
    story: list = []

    # Header
    title = Paragraph("<b>HealthSense Assessment Summary Report</b>", styles["Title"])
    meta = Paragraph(f"Date range: {start_str} → {end_str}<br/>Generated: {_today_str()}", styles["Normal"])
    story += [title, Spacer(1, 6), meta, Spacer(1, 10)]

    # Summary stats
    total = len(rows)
    avg_overall = round(sum([_to_float(r.get("overall", 0.0), 0.0) for r in rows]) / max(1, total), 2) if rows else 0.0
    best = None
    if rows:
        best = max(rows, key=lambda r: _to_float(r.get("overall", 0.0), 0.0))
    best_line = f"Best performer: {best['name']} ({best['overall']})" if best else "Best performer: –"
    story += [Paragraph(f"Total assessments: {total}<br/>Average overall score: {avg_overall}<br/>{best_line}", styles["Normal"]), Spacer(1, 12)]

    # Table
    header = ["#", "Name", "Date Completed", "Overall", "Nutrition", "Training", "Resilience", "Recovery"]
    data = [header]
    for idx, r in enumerate(rows, start=1):
        dt = r.get("finished_at")
        date_str = ""
        if isinstance(dt, datetime):
            date_str = dt.strftime("%d-%b-%Y")
        data.append([
            str(idx),
            r.get("name", ""),
            date_str,
            f"{_to_float(r.get('overall'), 0.0):.1f}",
            "" if r.get("nutrition") is None else f"{_to_float(r.get('nutrition'), 0.0):.0f}",
            "" if r.get("training")  is None else f"{_to_float(r.get('training'), 0.0):.0f}",
            "" if r.get("resilience") is None else f"{_to_float(r.get('resilience'), 0.0):.0f}",
            "" if r.get("recovery")  is None else f"{_to_float(r.get('recovery'), 0.0):.0f}",
        ])

    table = Table(data, repeatRows=1, colWidths=[24, 160, 110, 70, 70, 70, 80, 70])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#003366")),
        ("TEXTCOLOR", (0,0), (-1,0), colors.whitesmoke),
        ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
        ("ALIGN", (0,0), (-1,-1), "CENTER"),
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("GRID", (0,0), (-1,-1), 0.25, colors.grey),
        ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, colors.HexColor("#f5f5f5")]),
    ]))
    story.append(table)

    story.append(Spacer(1, 10))
    story.append(Paragraph("© 2025 HealthSense — Confidential internal summary", styles["Normal"]))

    doc.build(story)

def _write_pdf(path: str, user: User, run: AssessmentRun, pillars: List[PillarResult]) -> None:
    """
    Render a landscape dashboard-style PDF:
      • Left: horizontal bar chart of pillar overalls (legend top-right inside chart)
      • Right: four feedback cards with pillar symbol, score-colored header, feedback + two next steps
      • Header title uses overall score (combined_overall if present; computed fallback)
      • Footer shows completion date (run.finished_at if present, else today UTC)

    Also writes a sibling JPEG (latest.jpeg) next to the PDF for web preview.
    """
    # Lazy imports so app can start even if report deps are missing
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.patches import FancyBboxPatch, Patch
    except Exception as e:
        raise RuntimeError(f"matplotlib not available: {e!r}")

    try:
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.pdfgen import canvas
    except Exception as e:
        raise RuntimeError(f"reportlab not available: {e!r}")

    _audit("report_start", "ok", {"user_id": getattr(user, "id", None), "run_id": getattr(run, "id", None), "out_pdf": path})

    # ---------- Prepare data ----------
    ordered_keys = _pillar_order()
    # Map pillar_key -> PillarResult
    pr_map: Dict[str, PillarResult] = {getattr(pr, "pillar_key", ""): pr for pr in pillars}

    # Compute combined score (prefer DB field)
    combined = getattr(run, "combined_overall", None)
    if combined is None:
        vals = []
        for k in ordered_keys:
            pr = pr_map.get(k)
            if pr and getattr(pr, "overall", None) is not None:
                vals.append(int(getattr(pr, "overall", 0) or 0))
        combined = round(sum(vals) / max(1, len(vals))) if vals else 0
    combined = int(combined)

    # Build simple structure for plotting/cards
    cards: List[Dict[str, Any]] = []
    bar_labels: List[str] = []
    bar_values: List[int] = []
    bar_colors: List[tuple] = []

    for k in ordered_keys:
        pr = pr_map.get(k)
        if not pr:
            continue
        score = int(getattr(pr, "overall", 0) or 0)
        bar_labels.append(_title_for_pillar(k))
        bar_values.append(score)
        bar_colors.append(_score_color_rgb(score))

        # Parse advice text into feedback + up to 2 next steps
        advice_text = (getattr(pr, "advice", None) or "").strip()
        fb_line = ""; bullets: List[str] = []
        if advice_text:
            parts = advice_text.split("Next steps:", 1)
            fb_line = parts[0].strip().lstrip("-").strip() if parts else ""
            steps_raw = parts[1] if len(parts) > 1 else ""
            for raw_line in steps_raw.splitlines():
                t = raw_line.strip()
                if not t:
                    continue
                if t.startswith(("-", "•")):
                    t = t[1:].strip()
                bullets.append(t)
                if len(bullets) >= 2:
                    break
        cards.append({
            "pillar_key": k,
            "symbol": _pillar_symbol(k),
            "title": _title_for_pillar(k),
            "score": score,
            "feedback": fb_line,
            "steps": bullets,
        })

    # ---------- Draw dashboard to JPEG ----------
    # Figure sized for A4 landscape proportions (approx)
    fig = plt.figure(figsize=(16, 10))
    fig.patch.set_facecolor("white")

    # Bar chart aligned to card grid (top ≈ 0.89, bottom ≈ 0.22)
    ax_chart = fig.add_axes([0.06, 0.22, 0.38, 0.67])
    y_pos = range(len(bar_labels))
    ax_chart.barh(y_pos, bar_values, color=bar_colors)
    ax_chart.set_yticks(y_pos)
    ax_chart.set_yticklabels(bar_labels, fontsize=11)
    ax_chart.set_xlim(0, 100)
    ax_chart.invert_yaxis()
    ax_chart.set_xlabel("Score / 100")
    ax_chart.set_title("Pillar Overall Scores", fontsize=13, pad=8)

    # Legend (inside top-right)
    legend_elements = [
        Patch(facecolor=_score_color_rgb(85), label='Strong (≥ 80)'),
        Patch(facecolor=_score_color_rgb(70), label='Good (60–79)'),
        Patch(facecolor=_score_color_rgb(40), label='Needs focus (< 60)')
    ]
    ax_chart.legend(handles=legend_elements, loc='upper right', fontsize=9, frameon=True)

    # Feedback cards grid (2 x 2)
    card_w, card_h = 0.22, 0.31
    x0s = [0.50, 0.74]
    y0s = [0.58, 0.22]
    idx = 0
    for r in range(2):
        for c in range(2):
            if idx >= len(cards):
                break
            p = cards[idx]; idx += 1
            x0, y0 = x0s[c], y0s[r]
            ax_card = fig.add_axes([x0, y0, card_w, card_h])
            ax_card.axis("off")
            header_color = _score_color_rgb(p["score"]) 
            # Header strip
            ax_card.add_patch(FancyBboxPatch((0,0.83), 1, 0.17, boxstyle="round,pad=0.005,rounding_size=0.02",
                                             facecolor=header_color, edgecolor="none", transform=ax_card.transAxes))
            header_text = f"{p['symbol']} {p['title']} — {p['score']}/100"
            ax_card.text(0.03, 0.915, header_text, fontsize=11, fontweight="bold", color="white",
                         va="center", ha="left", transform=ax_card.transAxes)
            # Body box
            ax_card.add_patch(FancyBboxPatch((0,0), 1, 0.83, boxstyle="round,pad=0.02,rounding_size=0.02",
                                             facecolor=(0.97,0.97,0.97), edgecolor=(0.9,0.9,0.9), linewidth=1,
                                             transform=ax_card.transAxes))

            # --- Wrapped feedback and steps (use per-card values) ---
            fb = (p.get("feedback") or "").strip()
            steps = (p.get("steps") or [])

            ax_card.text(0.04, 0.72, "Feedback", fontsize=10, fontweight="bold",
                         ha="left", va="top", transform=ax_card.transAxes)
            if fb:
                fb_block = _wrap_block(fb, width=42, max_lines=4, bullet=None)
                ax_card.text(0.04, 0.62, fb_block, fontsize=9.5,
                             ha="left", va="top", transform=ax_card.transAxes)

            # Push Next steps lower for better spacing below Feedback
            ax_card.text(0.04, 0.40, "Next steps", fontsize=10, fontweight="bold",
                         ha="left", va="top", transform=ax_card.transAxes)
            steps_blocks = []
            for sline in steps[:2]:
                steps_blocks.append(_wrap_block(sline, width=42, max_lines=3, bullet="• "))
            steps_text = "\n".join(steps_blocks).strip()
            if steps_text:
                ax_card.text(0.04, 0.28, steps_text, fontsize=9.5,
                             ha="left", va="top", transform=ax_card.transAxes)

    # Page title: overall score + user name
    fig.suptitle(f"Overall Score: {combined}/100\nWellbeing Assessment for {_display_full_name(user)}",
                 fontsize=18, fontweight="bold")

    fig.tight_layout(rect=[0, 0.06, 1, 0.94])

    # Add completion footer directly to the figure (so PNG/JPEG include it)
    dt_fig = getattr(run, "finished_at", None) or datetime.utcnow()
    if not isinstance(dt_fig, datetime):
        dt_fig = datetime.utcnow()
    fig.text(0.01, 0.01, f"Completed on: {dt_fig.strftime('%B %d, %Y')}", fontsize=9, color=(0.3,0.3,0.3), ha='left', va='bottom')

    # Save dashboard image robustly (PNG → JPEG fallback)
    out_dir = os.path.dirname(path)
    os.makedirs(out_dir, exist_ok=True)
    png_path = os.path.join(out_dir, "latest.png")
    jpg_path = os.path.join(out_dir, "latest.jpeg")

    try:
        fig.savefig(png_path, dpi=180, bbox_inches="tight", format="png")
        _audit("report_png_saved", "ok", {"png_path": png_path})
    except Exception as e:
        _audit("report_png_saved", "error", {"png_path": png_path}, error=str(e))
        raise
    finally:
        plt.close(fig)

    # Convert PNG → JPEG
    try:
        from PIL import Image
        with Image.open(png_path) as im:
            if im.mode in ("RGBA", "LA"):
                from PIL import Image as _Image
                bg = _Image.new("RGB", im.size, (255, 255, 255))
                bg.paste(im, mask=im.split()[-1])
                im = bg
            else:
                im = im.convert("RGB")
            im.save(jpg_path, "JPEG", quality=90, optimize=True, progressive=True)
        _audit("report_jpeg_saved", "ok", {"jpeg_path": jpg_path})
    except Exception as e:
        import shutil
        shutil.copyfile(png_path, jpg_path)
        _audit("report_jpeg_saved_fallback", "warn", {"jpeg_path": jpg_path, "png_path": png_path}, error=str(e))

    try:
        pdf = canvas.Canvas(path, pagesize=landscape(A4))
        width, height = landscape(A4)
        pdf.drawImage(jpg_path, 0, 0, width=width, height=height, preserveAspectRatio=True, mask='auto')

        dt = getattr(run, "finished_at", None) or datetime.utcnow()
        if not isinstance(dt, datetime):
            dt = datetime.utcnow()
        pdf.setFillGray(0.3)
        pdf.setFont("Helvetica", 9)
        pdf.drawString(20, 14, f"Completed on: {dt.strftime('%B %d, %Y')}")

        pdf.showPage()
        pdf.save()
        _audit("report_pdf_saved", "ok", {"pdf_path": path})
        print(f"📄 PDF written to {path}")
    except Exception as e:
        _audit("report_pdf_saved", "error", {"pdf_path": path}, error=str(e))
        raise

def generate_assessment_report_pdf(run_id: int) -> str:
    """
    Public entry point to generate a PDF for the given assessment run.
    Returns the absolute path to the generated PDF.
    Raises if reportlab missing or if run not found.
    """
    user, run, pillars = _collect_report_data(run_id)
    if not user or not run:
        raise RuntimeError("Assessment run not found")
    root = _reports_root_for_user(user.id)
    out_path = os.path.join(root, "latest.pdf")
    _write_pdf(out_path, user, run, pillars)
    # audit success
    try:
        with SessionLocal() as s:
            s.add(JobAudit(job_name="report_generate", status="ok",
                           payload={"run_id": run_id, "user_id": user.id, "path": out_path}))
            s.commit()
    except Exception:
        pass
    return out_path

def generate_detailed_report_pdf_by_user(user_id: int) -> str:
    """Public entry point to generate the detailed (grouped) PDF for a user.
    Returns the absolute filesystem path to the generated PDF.
    """
    user, run, rows = _collect_detailed_report_data(user_id)
    if not user or not run:
        raise RuntimeError("Detailed report: user/run not found")
    root = _reports_root_for_user(user.id)
    out_path = os.path.join(root, "detailed.pdf")
    _write_detailed_pdf(out_path, user, run, rows)
    try:
        with SessionLocal() as s:
            s.add(JobAudit(job_name="detailed_report_generate", status="ok",
                           payload={"user_id": user.id, "run_id": getattr(run, 'id', None), "path": out_path}))
            s.commit()
    except Exception:
        pass
    return out_path

# Public entry point to generate summary PDF for a date range
def generate_assessment_summary_pdf(start: date | str, end: date | str) -> str:
    """
    Generate a PDF summarising assessments completed within the date range [start, end] (inclusive).
    Returns absolute filesystem path to the PDF.
    """
    start_dt, end_dt, start_str, end_str = _normalise_date_range(start, end)
    _audit("summary_report_start", "ok", {"start": start_str, "end": end_str})
    try:
        rows = _collect_summary_rows(start_dt, end_dt)
        out_root = _reports_root_global()
        filename = f"assessment-summary-{start_str}_{end_str}.pdf"
        out_path = os.path.join(out_root, filename)
        _write_summary_pdf(out_path, start_str, end_str, rows)
        with SessionLocal() as s:
            s.add(JobAudit(job_name="summary_report_generate", status="ok",
                           payload={"start": start_str, "end": end_str, "path": out_path, "count": len(rows)}))
            s.commit()
        return out_path
    except Exception as e:
        _audit("summary_report_generate", "error", {"start": start_str, "end": end_str}, error=str(e))
        raise