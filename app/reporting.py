# app/reporting.py
from __future__ import annotations

import os
from datetime import datetime
from typing import Optional, Dict, Any, List, Tuple
import textwrap

from .db import SessionLocal
from .models import AssessmentRun, PillarResult, User, JobAudit

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

def _safe_name(user: User) -> str:
    n = (getattr(user, "name", None) or getattr(user, "first_name", "") or "").strip()
    return n or "User"

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
    fig.suptitle(f"Overall Score: {combined}/100\nWellbeing Assessment for {_safe_name(user)}",
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