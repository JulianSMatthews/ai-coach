# app/reporting.py
from __future__ import annotations

import os
from datetime import datetime, date, timedelta
import html
import json
try:
    from zoneinfo import ZoneInfo  # Python 3.9+
except Exception:
    ZoneInfo = None  # type: ignore
from typing import Optional, Dict, Any, List, Tuple
import textwrap

from .db import SessionLocal
from .models import AssessmentRun, PillarResult, User, JobAudit, UserConceptState

# For raw SQL fallback when OKR models are unavailable
from sqlalchemy import text

# Optional OKR tables – support both naming variants in models.py
OkrObjective = None  # type: ignore
OkrKeyResult = None  # type: ignore
try:
    # Preferred snake-camel variant
    from .models import OkrObjective as _O1, OkrKeyResult as _K1  # type: ignore
    OkrObjective, OkrKeyResult = _O1, _K1
except Exception:
    try:
        # Alternate ALLCAPS variant
        from .models import OKRObjective as _O2, OKRKeyResult as _K2  # type: ignore
        OkrObjective, OkrKeyResult = _O2, _K2
    except Exception:
        OkrObjective, OkrKeyResult = None, None  # type: ignore

# Audit/logging controls (silence console by default)
AUDIT_TO_CONSOLE = os.getenv("AUDIT_TO_CONSOLE", "0") == "1"
AUDIT_TO_DB = os.getenv("AUDIT_TO_DB", "1") == "1"
BRAND_NAME = (os.getenv("BRAND_NAME") or "Purple Clubs").strip() or "Purple Clubs"
BRAND_YEAR = os.getenv("BRAND_YEAR") or str(datetime.utcnow().year)
BRAND_FOOTER = f"© {BRAND_YEAR} {BRAND_NAME}"

def _audit(job: str, status: str = "ok", payload: Dict[str, Any] | None = None, error: str | None = None) -> None:
    if AUDIT_TO_CONSOLE:
        try:
            print(f"[AUDIT] {job} status={status} payload={(payload or {})} err={error or ''}")
        except Exception:
            pass
    if not AUDIT_TO_DB:
        return
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

# Best-effort role display from user model
def _display_role(user: User) -> str:
    """Best-effort role display from user model; returns empty string if unavailable."""
    # Try common attribute names in priority order
    for attr in ("role", "job_title", "title", "position", "member_role"):
        try:
            val = getattr(user, attr, None)
        except Exception:
            val = None
        if val is None:
            continue
        s = str(val).strip()
        if s:
            return s
    return ""

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


# Format a finished_at timestamp for PDF display: dd/mm/yy HH:MM in report-local time
def _format_finished_for_pdf(val: Any, *, tz_env: str = "REPORT_TZ") -> str:
    """
    Format a finished_at timestamp into a compact local string (dd/mm/yy HH:MM).
    - If naive, assume UTC.
    - Convert to timezone in $REPORT_TZ (default Europe/London) when zoneinfo is available.
    - Hide seconds and microseconds.
    - Return empty string if parsing fails.
    """
    if not val:
        return ""
    try:
        if isinstance(val, datetime):
            dt = val
        else:
            # Accept ISO strings; fallback to strptime without tz if needed
            try:
                dt = datetime.fromisoformat(str(val))
            except Exception:
                # Fallback: strip microseconds if present
                raw = str(val).split(".")[0]
                dt = datetime.fromisoformat(raw)
        # Assume UTC if naive
        if dt.tzinfo is None:
            try:
                tz_utc = ZoneInfo("UTC") if ZoneInfo else None
            except Exception:
                tz_utc = None
            if tz_utc is not None:
                dt = dt.replace(tzinfo=tz_utc)
        # Convert to local/report TZ if possible
        tz_name = os.getenv(tz_env, "Europe/London")
        try:
            tz = ZoneInfo(tz_name) if ZoneInfo else None
        except Exception:
            tz = None
        if tz is not None:
            dt = dt.astimezone(tz)
        # dd/mm/yy HH:MM (per Julian's preference)
        return dt.strftime("%d/%m/%y %H:%M")
    except Exception:
        return str(val)

def _pillar_order() -> List[str]:
    return ["nutrition", "training", "resilience", "recovery"]

def _title_for_pillar(p: str) -> str:
    return (p or "").replace("_", " ").title()

def _concept_display(code: str) -> str:
    return (code or "").replace("_", " ").title()


# Utility: get first non-empty attribute (handles bytes, None)
def _first_non_empty_attr(obj: Any, fields: List[str]) -> str:
    for f in fields:
        try:
            val = getattr(obj, f, None)
        except Exception:
            val = None
        if val is None:
            continue
        if isinstance(val, (bytes, bytearray)):
            try:
                val = val.decode("utf-8", errors="ignore")
            except Exception:
                val = str(val)
        val = str(val).strip()
        if val:
            return val
    return ""

# ──────────────────────────────────────────────────────────────────────────────
# OKR helpers (prefer structured OKR tables; fallback to PillarResult.advice)
# ──────────────────────────────────────────────────────────────────────────────

def _fetch_okrs_for_run(run_id: int) -> Dict[str, Dict[str, Any]]:
    """
    Return a map: pillar_key -> { 'objective': str, 'krs': [str, ...] }
    Prefers dedicated OKR tables when available (OkrObjective/OkrKeyResult) and
    falls back to parsing PillarResult.advice if tables are not present.
    """
    out: Dict[str, Dict[str, Any]] = {}

    # Resolve user_id for this run_id (used for fallback when okr_objectives lacks run_id)
    _user_id_for_run = None
    try:
        with SessionLocal() as _s_uid:
            _row = _s_uid.execute(
                text("SELECT user_id FROM assessment_runs WHERE id = :rid"),
                {"rid": run_id}
            ).first()
            if _row and _row[0] is not None:
                _user_id_for_run = int(_row[0])
    except Exception:
        _user_id_for_run = None

    # Resolve assess_session_id for this run (used to link OKRs via okr_objectives.source_assess_session_id)
    _assess_session_id_for_run = None
    try:
        with SessionLocal() as _s_asid:
            # Try common column names in assessment_runs for the session id
            _row = None
            try:
                _row = _s_asid.execute(
                    text("SELECT assess_session_id FROM assessment_runs WHERE id = :rid"),
                    {"rid": run_id}
                ).first()
            except Exception:
                try:
                    _s_asid.rollback()
                except Exception:
                    pass
            if (not _row) or (_row[0] is None):
                try:
                    _row = _s_asid.execute(
                        text("SELECT session_id FROM assessment_runs WHERE id = :rid"),
                        {"rid": run_id}
                    ).first()
                except Exception:
                    try:
                        _s_asid.rollback()
                    except Exception:
                        pass
            if _row and _row[0] is not None:
                _assess_session_id_for_run = _row[0]
    except Exception:
        _assess_session_id_for_run = None

    # Audit linkage inputs for OKR fetch
    _audit('okr_link_inputs', 'ok', {
        'run_id': run_id,
        'user_id': _user_id_for_run,
        'assess_session_id': _assess_session_id_for_run,
        'orm_models': bool(OkrObjective is not None and OkrKeyResult is not None),
    })

    # Try structured OKR tables first
    if OkrObjective is not None and OkrKeyResult is not None:
        try:
            with SessionLocal() as s:
                # Fetch objectives linked to this assessment run via its assess_session_id (preferred)
                objs = []
                try:
                    assess_session_row = s.execute(
                        text("SELECT assess_session_id FROM assessment_runs WHERE id = :rid"),
                        {"rid": run_id}
                    ).first()
                    assess_session_id = assess_session_row[0] if assess_session_row and assess_session_row[0] is not None else None
                except Exception:
                    try:
                        s.rollback()
                    except Exception:
                        pass
                    assess_session_id = None

                if assess_session_id is not None:
                    objs = (
                        s.query(OkrObjective)
                         .filter(OkrObjective.source_assess_session_id == assess_session_id)
                         .all()
                    )
                    _audit('okr_obj_select', 'ok', {'run_id': run_id, 'by': 'orm_source_assess_session_id', 'rows': len(objs or [])})

                # Fallback: if no session-linked OKRs, try by owner_user_id (latest first)
                if not objs:
                    try:
                        user_row = s.execute(
                            text("SELECT user_id FROM assessment_runs WHERE id = :rid"),
                            {"rid": run_id}
                        ).first()
                        user_id = user_row[0] if user_row and user_row[0] is not None else None
                    except Exception:
                        try:
                            s.rollback()
                        except Exception:
                            pass
                        user_id = None

                    if user_id is not None:
                        objs = (
                            s.query(OkrObjective)
                             .filter(OkrObjective.owner_user_id == user_id)
                             .order_by(OkrObjective.id.desc())
                             .all()
                        )
                        _audit('okr_obj_select', 'ok', {'run_id': run_id, 'by': 'orm_owner_user_id', 'rows': len(objs or [])})

                if objs:
                    # Map pillar_result.id -> pillar_key for this run (to ensure pillar comes from source_pillar_id)
                    pr_id_to_key: Dict[int, str] = {}
                    try:
                        _pr_rows = s.execute(
                            text("SELECT id, pillar_key FROM pillar_results WHERE run_id = :rid"),
                            {"rid": run_id}
                        ).fetchall()
                        for _r in _pr_rows or []:
                            try:
                                pr_id_to_key[int(_r[0])] = (str(_r[1] or "").strip().lower().replace(" ", "_"))
                            except Exception:
                                continue
                    except Exception:
                        try:
                            s.rollback()
                        except Exception:
                            pass
                    # Prefer relationship 'key_results' if present on the ORM model, else fallback query
                    by_obj: Dict[Any, List[Any]] = {}
                    rel_used = False
                    for o in objs:
                        oid = getattr(o, 'id', None)
                        if oid is None:
                            continue
                        rel_krs = getattr(o, 'key_results', None)
                        if isinstance(rel_krs, list) and rel_krs:
                            by_obj[oid] = rel_krs
                            rel_used = True
                    if not rel_used:
                        obj_ids = [getattr(o, 'id', None) for o in objs if getattr(o, 'id', None) is not None]
                        if obj_ids:
                            kr_rows = (
                                s.query(OkrKeyResult)
                                 .filter(getattr(OkrKeyResult, 'objective_id').in_(obj_ids))
                                 .all()
                            )
                            for kr in kr_rows:
                                by_obj.setdefault(getattr(kr, 'objective_id', None), []).append(kr)
                    _audit('okr_kr_orm_source', 'ok', {'run_id': run_id, 'via': 'relationship' if rel_used else 'query', 'objectives': len(objs or [])})

                    for obj in objs:
                        # Prefer deriving pillar from source_pillar_id -> pillar_results to ensure it matches this run
                        _spid = getattr(obj, 'source_pillar_id', None)
                        pk = ''
                        if _spid is not None and int(_spid) in pr_id_to_key:
                            pk = pr_id_to_key[int(_spid)]
                        if not pk:
                            pk = (getattr(obj, 'pillar_key', None) or getattr(obj, 'pillar', '') or '').strip().lower().replace(' ', '_')
                        if not pk:
                            continue
                        objective_text = (getattr(obj, 'objective', None) or getattr(obj, 'title', None) or getattr(obj, 'text', '') or '').strip()
                        krs: List[str] = []
                        for kr in by_obj.get(getattr(obj, 'id', None), []):
                            base_txt = _first_non_empty_attr(kr, ['text','description','title','kr_text','kr_description','details','body','content'])
                            # Try to extract numeric baseline/target and unit-ish labels from common field names
                            baseline_val = _first_non_empty_attr(kr, ['baseline', 'baseline_value', 'baseline_num', 'start_value', 'start'])
                            target_val   = _first_non_empty_attr(kr, ['target', 'target_value', 'target_num', 'target_text', 'goal_value', 'goal'])
                            unit_label   = _first_non_empty_attr(kr, ['unit', 'metric_unit', 'unit_label', 'metric_label'])
                            per_label    = _first_non_empty_attr(kr, ['per', 'unit_per', 'per_period'])  # e.g., 'day', 'week'

                            def _fmt_num(x: str) -> str:
                                try:
                                    f = float(x)
                                    if f.is_integer():
                                        return str(int(f))
                                    return str(f)
                                except Exception:
                                    return str(x).strip()

                            def _fmt_unit(u: str, per: str) -> str:
                                u = (u or '').strip()
                                per = (per or '').strip()
                                if not u and not per:
                                    return ''
                                # Special case percent
                                if u.lower() in ('percent', '%') and not per:
                                    return '%'
                                if u and per:
                                    # e.g., 'portions per day'
                                    return f' {u} per {per}'
                                if u and not per:
                                    return f' {u}'
                                if per and not u:
                                    return f' per {per}'
                                return ''

                            enriched = base_txt.strip() if base_txt else ''
                            if enriched:
                                b = baseline_val
                                t = target_val
                                if b and t:
                                    enriched = f"{enriched} (from {_fmt_num(b)}{_fmt_unit(unit_label, per_label)} to {_fmt_num(t)}{_fmt_unit(unit_label, per_label)})"
                                elif t:
                                    enriched = f"{enriched} (target {_fmt_num(t)}{_fmt_unit(unit_label, per_label)})"
                                elif b:
                                    enriched = f"{enriched} (baseline {_fmt_num(b)}{_fmt_unit(unit_label, per_label)})"
                                krs.append(enriched)
                        out[pk] = {'objective': objective_text, 'krs': krs, 'llm_prompt': getattr(obj, 'llm_prompt', None)}
            # Audit successful fetch just before return
            _audit('okr_fetch_structured_summary', 'ok', {'run_id': run_id, 'objectives': len(out), 'has_okrs': bool(out)})
        except Exception as e:
            _audit('okr_fetch_structured_error', 'error', {'run_id': run_id}, error=str(e))

    # Audit if models are not importable (for logging)
    if OkrObjective is None or OkrKeyResult is None:
        _audit('okr_models_unavailable', 'warn', {'run_id': run_id}, error='OKR ORM models not importable')

    # Fallback: if OKR ORM models aren't importable, try raw SQL against okr_* tables
    if not out and (OkrObjective is None or OkrKeyResult is None):
        try:
            with SessionLocal() as s:
                rows = []
                # 1) Preferred: by okr_objectives.source_assess_session_id (links directly to the originating assessment session)
                if _assess_session_id_for_run is not None:
                    try:
                        rows = s.execute(
                            text("SELECT id, pillar_key, objective, source_pillar_id, llm_prompt FROM okr_objectives WHERE source_assess_session_id = :sid ORDER BY id ASC"),
                            {"sid": _assess_session_id_for_run}
                        ).fetchall()
                    except Exception:
                        try:
                            s.rollback()
                        except Exception:
                            pass
                        rows = []
                        # fallback to without llm_prompt
                        try:
                            rows = s.execute(
                                text("SELECT id, pillar_key, objective, source_pillar_id FROM okr_objectives WHERE source_assess_session_id = :sid ORDER BY id ASC"),
                                {"sid": _assess_session_id_for_run}
                            ).fetchall()
                        except Exception:
                            try:
                                s.rollback()
                            except Exception:
                                pass
                            rows = []
                    _audit('okr_obj_select', 'ok', {'run_id': run_id, 'by': 'source_assess_session_id', 'rows': len(rows or [])})

                # 2) Next: by run_id (if column exists)
                if not rows:
                    try:
                        rows = s.execute(
                            text("SELECT id, pillar_key, objective, source_pillar_id, llm_prompt FROM okr_objectives WHERE run_id = :rid"),
                            {"rid": run_id}
                        ).fetchall()
                    except Exception:
                        try:
                            s.rollback()
                        except Exception:
                            pass
                        rows = []
                        # fallback to without llm_prompt
                        try:
                            rows = s.execute(
                                text("SELECT id, pillar_key, objective, source_pillar_id FROM okr_objectives WHERE run_id = :rid"),
                                {"rid": run_id}
                            ).fetchall()
                        except Exception:
                            try:
                                s.rollback()
                            except Exception:
                                pass
                            rows = []
                    _audit('okr_obj_select', 'ok', {'run_id': run_id, 'by': 'run_id', 'rows': len(rows or [])})

                # 3) Fallback: by owner_user_id (if column exists) — keep latest per pillar
                if not rows and _user_id_for_run is not None:
                    try:
                        rows_all = s.execute(
                            text("SELECT id, pillar_key, objective, source_pillar_id, llm_prompt FROM okr_objectives WHERE owner_user_id = :uid ORDER BY id DESC"),
                            {"uid": _user_id_for_run}
                        ).fetchall()
                    except Exception:
                        try:
                            s.rollback()
                        except Exception:
                            pass
                        rows_all = []
                        # fallback to without llm_prompt
                        try:
                            rows_all = s.execute(
                                text("SELECT id, pillar_key, objective, source_pillar_id FROM okr_objectives WHERE owner_user_id = :uid ORDER BY id DESC"),
                                {"uid": _user_id_for_run}
                            ).fetchall()
                        except Exception:
                            try:
                                s.rollback()
                            except Exception:
                                pass
                            rows_all = []
                    seen = set()
                    filtered = []
                    for r in rows_all:
                        pk_norm = (r[1] or "").strip().lower().replace(" ", "_")
                        if pk_norm and pk_norm not in seen:
                            filtered.append(r)
                            seen.add(pk_norm)
                    rows = filtered
                    _audit('okr_obj_select', 'ok', {'run_id': run_id, 'by': 'owner_user_id', 'rows': len(rows or [])})

                if rows:
                    # Map pillar_result.id -> pillar_key for this run for source_pillar_id mapping
                    pr_id_to_key: Dict[int, str] = {}
                    try:
                        _pr_rows = s.execute(
                            text("SELECT id, pillar_key FROM pillar_results WHERE run_id = :rid"),
                            {"rid": run_id}
                        ).fetchall()
                        for _r in _pr_rows or []:
                            try:
                                pr_id_to_key[int(_r[0])] = (str(_r[1] or "").strip().lower().replace(" ", "_"))
                            except Exception:
                                continue
                    except Exception:
                        try:
                            s.rollback()
                        except Exception:
                            pass
                    # Build KR map keyed by objective_id
                    okr_map = {}
                    for r in rows:
                        oid = r[0]
                        raw_pk = (r[1] or "").strip().lower().replace(" ", "_")
                        obj_txt = (r[2] or "").strip()
                        _spid = r[3] if len(r) > 3 else None
                        prompt_txt = (r[4] if len(r) > 4 else None) or None
                        pk = ''
                        try:
                            if _spid is not None and int(_spid) in pr_id_to_key:
                                pk = pr_id_to_key[int(_spid)]
                        except Exception:
                            pk = ''
                        if not pk:
                            pk = raw_pk
                        okr_map[oid] = (pk, obj_txt, prompt_txt)
                    by_obj = {oid: [] for oid in okr_map.keys()}
                    # Detect available textual columns in okr_key_results and build a COALESCE for KR text
                    kr_cols_available = []
                    try:
                        _cols = s.execute(
                            text("SELECT column_name FROM information_schema.columns WHERE table_name = 'okr_key_results'")
                        ).fetchall() or []
                        kr_cols_available = [str(c[0]) for c in _cols]
                    except Exception:
                        try:
                            s.rollback()
                        except Exception:
                            pass
                        kr_cols_available = []
                    # Candidate text-like columns in order of preference
                    _cand = ['text', 'description', 'title', 'kr_text', 'kr_description', 'details', 'body']
                    _present = [c for c in _cand if c in kr_cols_available]
                    if not _present and kr_cols_available:
                        _present = [kr_cols_available[0]]
                    coalesce_expr = "COALESCE(" + ",".join(_present) + ") AS kr" if _present else "NULL AS kr"

                    # Detect optional numeric/unit columns for enrichment
                    _b_cols = [c for c in ['baseline', 'baseline_value', 'baseline_num', 'start_value', 'start'] if c in kr_cols_available]
                    _t_cols = [c for c in ['target', 'target_value', 'target_num', 'target_text', 'goal_value', 'goal'] if c in kr_cols_available]
                    _u_cols = [c for c in ['unit', 'metric_unit', 'unit_label', 'metric_label'] if c in kr_cols_available]
                    _p_cols = [c for c in ['per', 'unit_per', 'per_period'] if c in kr_cols_available]

                    b_expr = _b_cols[0] if _b_cols else 'NULL'
                    t_expr = _t_cols[0] if _t_cols else 'NULL'
                    u_expr = _u_cols[0] if _u_cols else 'NULL'
                    p_expr = _p_cols[0] if _p_cols else 'NULL'

                    _audit('okr_kr_columns', 'ok', {
                        'run_id': run_id,
                        'present': _present,
                        'baseline_col': b_expr if b_expr != 'NULL' else None,
                        'target_col': t_expr if t_expr != 'NULL' else None,
                        'unit_col': u_expr if u_expr != 'NULL' else None,
                        'per_col': p_expr if p_expr != 'NULL' else None,
                    })

                    # Fetch KRs per objective id (simple loop to avoid dialect-specific IN binding)
                    for oid in okr_map.keys():
                        kr_rows = s.execute(
                            text(f"SELECT {coalesce_expr}, {b_expr} AS baseline, {t_expr} AS target, {u_expr} AS unit, {p_expr} AS per FROM okr_key_results WHERE objective_id = :oid ORDER BY id ASC"),
                            {"oid": oid}
                        ).fetchall()
                        if kr_rows:
                            by_obj[oid] = kr_rows
                    # Assemble output
                    for oid, (pk, obj_txt, prompt_txt) in okr_map.items():
                        krs: List[str] = []
                        for row in by_obj.get(oid, []):
                            # row indices: 0=text, 1=baseline, 2=target, 3=unit, 4=per (when selected above)
                            kr_txt = (row[0] or "")
                            if isinstance(kr_txt, bytes):
                                try:
                                    kr_txt = kr_txt.decode('utf-8', errors='ignore')
                                except Exception:
                                    kr_txt = str(kr_txt)
                            kr_txt = str(kr_txt).strip()
                            b = str(row[1]).strip() if len(row) > 1 and row[1] is not None else ''
                            t = str(row[2]).strip() if len(row) > 2 and row[2] is not None else ''
                            u = str(row[3]).strip() if len(row) > 3 and row[3] is not None else ''
                            p = str(row[4]).strip() if len(row) > 4 and row[4] is not None else ''

                            def _fmt_num(x_: str) -> str:
                                try:
                                    f = float(x_)
                                    if f.is_integer():
                                        return str(int(f))
                                    return str(f)
                                except Exception:
                                    return str(x_).strip()

                            def _fmt_unit(u_: str, p_: str) -> str:
                                if not u_ and not p_:
                                    return ''
                                if u_.lower() in ('percent', '%') and not p_:
                                    return '%'
                                if u_ and p_:
                                    return f' {u_} per {p_}'
                                if u_:
                                    return f' {u_}'
                                if p_:
                                    return f' per {p_}'
                                return ''

                            if kr_txt:
                                if b and t:
                                    disp = f"{kr_txt} (from {_fmt_num(b)}{_fmt_unit(u, p)} to {_fmt_num(t)}{_fmt_unit(u, p)})"
                                elif t:
                                    disp = f"{kr_txt} (target {_fmt_num(t)}{_fmt_unit(u, p)})"
                                elif b:
                                    disp = f"{kr_txt} (baseline {_fmt_num(b)}{_fmt_unit(u, p)})"
                                else:
                                    disp = kr_txt
                                krs.append(disp)
                        if pk:
                            out[pk] = {"objective": obj_txt, "krs": krs, "llm_prompt": prompt_txt}
                # Add a tag indicating which path was used
                _path = "source_assess_session_id" if _assess_session_id_for_run is not None and out else ("run_id" if rows else ("owner_user_id" if _user_id_for_run is not None else "unknown"))
                _audit('okr_fetch_structured_summary', 'ok', {'run_id': run_id, 'objectives': len(out), 'has_okrs': bool(out), 'fallback': True, 'path': _path})
        except Exception as e:
            try:
                # make sure this session isn't left in a failed state
                s.rollback()  # note: if 's' isn't defined in this scope, ignore
            except Exception:
                pass
            _audit('okr_models_unavailable', 'error', {'run_id': run_id}, error=str(e))

    return out


# ──────────────────────────────────────────────────────────────────────────────
# OKR Summary (admin) report – date range across users/runs, with OKRs
# ──────────────────────────────────────────────────────────────────────────────
def _collect_okr_summary_rows(start_dt: datetime, end_dt: datetime, club_id: int | None = None) -> list[dict]:
    """
    Collect assessment runs within range, combining pillar scores with OKRs.
    Returns rows: { name, finished_at, pillar, score, objective, key_results, user_id, run_id }
    """
    base = _collect_summary_rows(start_dt, end_dt, club_id=club_id)
    rows: list[dict] = []
    for b in base:
        run_id = b.get("run_id")
        if not run_id:
            continue
        okr_map = _fetch_okrs_for_run(int(run_id))
        try:
            _audit("okr_summary_run_okrs", "ok", {
                "run_id": int(run_id),
                "has_okrs": bool(okr_map),
                "has_any_llm_prompt": any(bool((v or {}).get("llm_prompt")) for v in (okr_map or {}).values())
            })
        except Exception:
            pass
        for pillar in _pillar_order():
            okr = okr_map.get(pillar)
            if not okr:
                continue
            krs = [str(x).strip() for x in (okr.get("krs") or []) if str(x).strip()]
            rows.append({
                "name": b.get("name"),
                "finished_at": b.get("finished_at"),
                "pillar": _title_for_pillar(pillar),
                "score": b.get(pillar),
                "objective": okr.get("objective") or "",
                "key_results": "\n".join(krs),
                "user_id": b.get("user_id"),
                "run_id": run_id,
                "llm_prompt": okr.get("llm_prompt"),
            })
    return rows


def generate_okr_summary_html(
    start: date | str | None = None,
    end: date | str | None = None,
    *,
    include_llm_prompt: bool = False,
    club_id: int | None = None,
) -> str:
    """Generate an OKR summary **HTML** file for [start, end] and return its absolute path.
    Uses _collect_okr_summary_rows(). Columns wrap; no Role column.
    """
    # Resolve date window and fetch rows
    start_dt, end_dt, s_str, e_str = _normalise_date_range(start, end)
    # Audit: entry + requested column
    try:
        _audit("okr_summary_html_start", "ok", {
            "include_llm_prompt": include_llm_prompt,
            "start": s_str,
            "end": e_str
        })
    except Exception:
        pass
    rows = _collect_okr_summary_rows(start_dt, end_dt, club_id=club_id)
    # Audit: how many rows have an llm_prompt payload
    total_rows = len(rows)
    llm_prompt_rows = sum(1 for r in rows if (r.get("llm_prompt") or "").strip())
    try:
        _audit("okr_summary_rows_stats", "ok", {
            "rows_total": total_rows,
            "rows_with_llm_prompt": llm_prompt_rows,
            "include_llm_prompt": include_llm_prompt
        })
    except Exception:
        pass

    # Escape helper
    def _esc(x: str | None) -> str:
        s = "" if x is None else str(x)
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    title = f"OKR Summary Report ({s_str} – {e_str})"

    # Header
    head = ["Name", "Pillar", "Score", "Objective", "Key Results"]
    if include_llm_prompt:
        head.append("LLM Prompt")
    thead = "<thead><tr>" + "".join(f"<th>{_esc(h)}</th>" for h in head) + "</tr></thead>"
    # Compute column count for colspan
    col_count = 6 if include_llm_prompt else 5

    # Body rows
    body_rows: list[str] = []
    for r in rows:
        name = _esc(str(r.get("name") or ""))
        pillar = _esc(str(r.get("pillar") or ""))
        sc = r.get("score")
        try:
            score = "" if sc is None else str(int(round(float(sc))))
        except Exception:
            score = _esc(str(sc) if sc is not None else "")
        objective = _esc(str(r.get("objective") or ""))

        # Key results: accept list or newline-separated string
        krs_blob = r.get("key_results")
        if isinstance(krs_blob, (list, tuple)):
            kr_items = [str(x) for x in krs_blob if str(x).strip()]
        else:
            krs_str = str(krs_blob or "").strip()
            kr_items = [li for li in krs_str.split("\n") if li.strip()] if krs_str else []
        krs_html = ("<ul>" + "".join(f"<li>{_esc(li)}</li>" for li in kr_items) + "</ul>") if kr_items else ""

        prompt_td = ""
        if include_llm_prompt:
            raw_prompt = str(r.get("llm_prompt") or "")
            prompt_td = f"<td class=\"prompt\"><pre>{_esc(raw_prompt)}</pre></td>"

        body_rows.append(
            f"<tr>"
            f"<td class=\"name\">{name}</td>"
            f"<td class=\"pillar\">{pillar}</td>"
            f"<td class=\"score num\">{score}</td>"
            f"<td class=\"objective\">{objective}</td>"
            f"<td class=\"krs\">{krs_html}</td>"
            + prompt_td +
            f"</tr>"
        )

    # CSS for fixed layout + wrapping
    css = """
    <style>
      :root { --fg:#222; --muted:#666; --bg:#fff; --head:#f3f3f3; --grid:#ddd; }
      * { box-sizing: border-box; }
      body { margin: 24px; font-family: -apple-system, BlinkMacSystemFont, Segoe UI, Roboto, Helvetica, Arial, sans-serif; color: var(--fg); background: var(--bg); }
      h1 { font-size: 20px; margin: 0 0 10px 0; }
      .meta { color: var(--muted); margin-bottom: 16px; }
      table { width: 100%; border-collapse: collapse; table-layout: fixed; }
      thead th { background: var(--head); border: 1px solid var(--grid); padding: 8px 6px; text-align: left; font-weight: 600; }
      tbody td { border: 1px solid var(--grid); padding: 8px 6px; vertical-align: top; overflow-wrap: anywhere; word-break: break-word; }
      .num { text-align: right; white-space: nowrap; }
      .name { width: 22%; }
      .pillar { width: 10%; }
      .score { width: 6%; }
      .objective { width: 26%; }
      .krs { width: 30%; }
      .prompt { width: 30%; color: var(--fg); }
      ul { margin: 0; padding-left: 18px; }
      li { margin: 0 0 6px 0; }
      pre { margin: 0; white-space: pre-wrap; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, 'Liberation Mono', monospace; font-size: 12px; line-height: 1.35; }
    </style>
    """

    # Assemble document
    html_doc = (
        "<!doctype html>\n<html lang=\"en\">\n<meta charset=\"utf-8\">\n"
        f"<title>{_esc(title)}</title>\n"
        f"{css}\n"
        f"<h1>{_esc(title)}</h1>\n"
        f"<div class=\"meta\">Generated: {_esc(_today_str())}</div>\n"
        f"<table>\n{thead}\n<tbody>\n"
        + ("".join(body_rows) if body_rows else f'<tr><td colspan="{col_count}">No data</td></tr>')
        + "\n</tbody>\n</table>\n"
    )

    # Write to /public/reports
    out_base = _reports_root_global()
    out_name = f"okr_summary_{s_str}_to_{e_str}.html"
    out_path = os.path.join(out_base, out_name)
    os.makedirs(out_base, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html_doc)

    try:
        _audit("okr_summary_html_saved", "ok", {
            "html_path": out_path,
            "rows": len(rows),
            "rows_total": total_rows,
            "rows_with_llm_prompt": llm_prompt_rows,
            "include_llm_prompt": include_llm_prompt
        })
    except Exception:
        pass
    return out_path


def _write_okr_summary_pdf(
    path: str,
    start_str: str,
    end_str: str,
    rows: list[dict],
    *,
    include_llm_prompt: bool = False
) -> None:
    """Landscape PDF listing OKRs per pillar across runs in the date window."""
    try:
        from reportlab.platypus import BaseDocTemplate, Frame, PageTemplate, Paragraph, Spacer, Table, TableStyle
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib import colors
    except Exception as e:
        raise RuntimeError(f"reportlab not available: {e!r}")

    styles = getSampleStyleSheet()
    from reportlab.lib.styles import ParagraphStyle
    wrap = ParagraphStyle('wrap', parent=styles['Normal'], fontSize=9, leading=12)
    doc = BaseDocTemplate(path, pagesize=landscape(A4), leftMargin=30, rightMargin=30, topMargin=30, bottomMargin=30)
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id='normal')
    doc.addPageTemplates([PageTemplate(id='main', frames=frame)])

    story = []
    story.append(Paragraph(f"OKR Summary Report ({start_str} – {end_str})", styles["Title"]))
    story.append(Spacer(1, 12))

    if include_llm_prompt:
        data = [["Name", "Pillar", "Score", "Objective", "Key Results", "LLM Prompt"]]
    else:
        data = [["Name", "Pillar", "Score", "Objective", "Key Results"]]

    for r in rows:
        # Sanitize Name field (no role column)
        _name_raw = str(r.get("name") or "").strip()
        _looks_polluted = (
            len(_name_raw) > 40 and (
                "|" in _name_raw.lower() or _name_raw.lower().startswith("system:") or _name_raw.lower().startswith("assistant:") or _name_raw.lower().startswith("user:") or "digits phrasing" in _name_raw.lower()
            )
        )
        if _looks_polluted or not _name_raw:
            try:
                uid = r.get("user_id")
                if uid:
                    with SessionLocal() as _s_fix:
                        _u = _s_fix.query(User).filter(User.id == int(uid)).first()
                        if _u is not None and (_looks_polluted or not _name_raw):
                            _name_raw = _display_full_name(_u)
            except Exception:
                pass
        if len(_name_raw) > 80:
            _name_raw = _name_raw[:80] + "…"
        name_cell = Paragraph(_name_raw.replace("<", "&lt;").replace(">", "&gt;"), wrap)
        pillar_cell = Paragraph(str(r.get("pillar") or ""), wrap)
        # Score: keep short
        score_val = r.get("score")
        try:
            score_disp = "" if score_val is None else str(int(round(float(score_val))))
        except Exception:
            score_disp = str(score_val) if score_val is not None else ""
        obj_cell = Paragraph(str(r.get("objective") or ""), wrap)
        krs_text = r.get("key_results") or ""
        krs_text = str(krs_text).replace("\n", "<br/>")  # Ensure newlines render in Paragraph
        krs_cell = Paragraph(krs_text, wrap)

        if include_llm_prompt:
            prompt_text = r.get("llm_prompt") or ""
            prompt_text = str(prompt_text).replace("\n", " ")
            prompt_text = prompt_text.replace("<", "&lt;").replace(">", "&gt;")
            MAX_PROMPT_CHARS = 100
            prompt_cell = Paragraph(prompt_text[:MAX_PROMPT_CHARS] + ("…" if len(prompt_text) > MAX_PROMPT_CHARS else ""), wrap)
            data.append([name_cell, pillar_cell, score_disp, obj_cell, krs_cell, prompt_cell])
        else:
            data.append([name_cell, pillar_cell, score_disp, obj_cell, krs_cell])

    try:
        _audit("okr_summary_pdf_data", "ok", {
            "row_count": len(data) - 1,  # minus header
            "include_llm_prompt": include_llm_prompt
        })
    except Exception:
        pass

    # Adjusted column widths (removed Role column)
    if include_llm_prompt:
        col_widths = [225, 100, 40, 260, 290, 220]
    else:
        col_widths = [245, 110, 44, 290, 320]

    table = Table(data, repeatRows=1, colWidths=col_widths)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), colors.lightgrey),
        ("GRID", (0,0), (-1,-1), 0.25, colors.grey),
        ("VALIGN", (0,0), (-1,-1), "TOP"),
        ("ALIGN", (3,1), (3,-1), "RIGHT"),   # Score column
        ("LEFTPADDING", (0,0), (-1,-1), 6),
        ("RIGHTPADDING", (0,0), (-1,-1), 6),
        ("TOPPADDING", (0,0), (-1,-1), 4),
        ("BOTTOMPADDING", (0,0), (-1,-1), 6),
    ]))
    story.append(table)
    doc.build(story)
    
def generate_okr_summary_report(start: date | str | None = None, end: date | str | None = None, *, club_id: int | None = None) -> str:
    """Generate an OKR summary **HTML** for the given date window and return its path."""
    return generate_okr_summary_html(start, end, include_llm_prompt=False, club_id=club_id)


def generate_okr_summary_report_redacted(start: date | str | None = None, end: date | str | None = None, *, club_id: int | None = None) -> str:
    """Generate an OKR summary **HTML** (no LMS prompt column) for the given date window and return its path."""
    return generate_okr_summary_html(start, end, include_llm_prompt=False, club_id=club_id)

# New public entry point: generate OKR summary HTML including LLM prompt
def generate_okr_summary_report_llm(start: date | str | None = None, end: date | str | None = None, *, club_id: int | None = None) -> str:
    """Generate an OKR summary **HTML** including the LLM prompt column for the given date window and return its path."""
    try:
        _audit("okr_summary_llm_entry", "ok", {"start": str(start), "end": str(end)})
    except Exception:
        pass
    return generate_okr_summary_html(start, end, include_llm_prompt=True, club_id=club_id)

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
    subsequent_indent = (" " * len(initial_indent)) if bullet else ""
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
    Render a multi-page, portrait PDF grouped by pillar, with a concept table:
      Columns: Concept | Score | Question | Answer | Confidence
      – Wrap long text in Concept/Question/Answer
      – Footer page numbers
      – Shows user name in Run Overview (no report path)
      – Includes OKR (from PillarResult.advice) under each pillar table
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

    # Fetch OKRs for this run (uses structured OKR tables if available)
    okr_map = _fetch_okrs_for_run(getattr(run, 'id', None))

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

        # --- OKR block per pillar (prefer structured tables) ------------------
        okr_obj = okr_map.get(pk, None)
        okr_text = ''
        kr_lines: List[str] = []
        if okr_obj:
            okr_text = (okr_obj.get('objective') or '').strip()
            kr_lines = [str(x).strip() for x in (okr_obj.get('krs') or []) if str(x).strip()]

        if okr_text:
            story.append(Spacer(1, 6))
            story.append(Paragraph('OKR', styles['Heading3']))
            # Objective (no leading symbol and use requested heading text)
            story.append(Paragraph('<b>Quarter Objective</b>', styles['Normal']))
            story.append(Paragraph((okr_text or '').replace('\n', '<br/>'), styles['Normal']))
            # Key Results / Next steps (if any)
            if kr_lines:
                story.append(Spacer(1, 4))
                story.append(Paragraph('<b>Key Results</b>', styles['Normal']))
                for i, kr in enumerate(kr_lines[:3], start=1):
                    # Constrain each KR to a single compact line; add ellipsis if too long
                    line = _wrap_block(str(kr), width=80, max_lines=1, bullet=f"{i}. ")
                    story.append(Paragraph(line.replace('\n', '<br/>'), styles['Normal']))                   
                    story.append(Spacer(1, 12))
    else:
            story.append(Spacer(1, 12))

    doc.build(story)
    _audit("detailed_report_pdf_saved", "ok", {"pdf_path": path})

# ──────────────────────────────────────────────────────────────────────────────
# Summary (admin) report – date range across users/runs
# ──────────────────────────────────────────────────────────────────────────────
def _collect_summary_rows(start_dt: datetime, end_dt: datetime, club_id: int | None = None) -> list[dict]:
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
        query = (
            s.query(AssessmentRun, User)
             .join(User, AssessmentRun.user_id == User.id)
             .filter(AssessmentRun.finished_at.isnot(None))
             .filter(AssessmentRun.finished_at >= start_dt)
             .filter(AssessmentRun.finished_at <= end_dt)
             .order_by(AssessmentRun.finished_at.desc())
        )
        if club_id is not None:
            query = query.filter(User.club_id == club_id)
        runs = query.all()
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
                "role": _display_role(user),
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
    from reportlab.lib.styles import ParagraphStyle
    wrap = ParagraphStyle('wrap', parent=styles['Normal'], fontSize=9, leading=11)
    story: list = []

    # Header
    title = Paragraph(f"<b>{BRAND_NAME} Assessment Summary Report</b>", styles["Title"])
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
    from reportlab.platypus import Paragraph
    for idx, r in enumerate(rows, start=1):
        dt = r.get("finished_at")
        date_str = ""
        if isinstance(dt, datetime):
            date_str = dt.strftime("%d-%b-%Y")
        # Wrap Name column so long user names don't overflow; escape HTML-sensitive chars
        name_text = str(r.get("name", "") or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        name_cell = Paragraph(name_text, wrap)
        data.append([
            str(idx),
            name_cell,
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
        ("ALIGN", (1,1), (1,-1), "LEFT"),     # Name column
        ("VALIGN", (1,1), (1,-1), "TOP"),     # Name column
        ("GRID", (0,0), (-1,-1), 0.25, colors.grey),
        ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, colors.HexColor("#f5f5f5")]),
    ]))
    story.append(table)

    story.append(Spacer(1, 10))
    story.append(Paragraph(f"{BRAND_FOOTER} — Confidential internal summary", styles["Normal"]))

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

    # Fetch OKRs (structured if available) to populate cards
    okr_map = _fetch_okrs_for_run(getattr(run, 'id', None))

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

        # Prefer OKR tables for Objective/KRs only; no fallback to advice
        fb_line = ''
        bullets: List[str] = []
        okr_obj = okr_map.get(k, None)
        if okr_obj:
            fb_line = (okr_obj.get('objective') or '').strip()
            for t in (okr_obj.get('krs') or [])[:3]:
                t = (t or '').strip()
                if t:
                    bullets.append(t)
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

            # Pull per-card content (avoid NameError)
            fb = (p.get("feedback") or "").strip()
            steps = (p.get("steps") or [])

            # Consistent vertical spacing between subheaders and their text blocks
            SUBHEAD_TO_TEXT_GAP = 0.09

            # Quarter Objective
            obj_subhead_y = 0.72
            ax_card.text(0.04, obj_subhead_y, "Quarter Objective", fontsize=10, fontweight="bold",
                         ha="left", va="top", transform=ax_card.transAxes)
            if fb:
                fb_block = _wrap_block(fb, width=44, max_lines=8, bullet=None)
                obj_text_y = obj_subhead_y - SUBHEAD_TO_TEXT_GAP
                ax_card.text(0.04, obj_text_y, fb_block, fontsize=9.5,
                             ha="left", va="top", transform=ax_card.transAxes)

            # Key Results
            if steps:
                kr_subhead_y = 0.49
                ax_card.text(0.04, kr_subhead_y, "Key Results", fontsize=10, fontweight="bold",
                             ha="left", va="top", transform=ax_card.transAxes)

                kr_lines = []
                for i, s in enumerate(steps[:3], start=1):
                    s = (s or "").strip()
                    if not s:
                        continue
                    kr_lines.append(_wrap_block(s, width=44, max_lines=2, bullet=f"{i}. "))
                if kr_lines:
                    kr_block = "\n".join(kr_lines)
                    kr_text_y = kr_subhead_y - SUBHEAD_TO_TEXT_GAP
                    ax_card.text(0.04, kr_text_y, kr_block, fontsize=9.5,
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

        # ── Page 1: Introduction / How to read this report ────────────────
        left = 40
        right = width - 40
        top = height - 40
        line_w = right - left

        # Title
        pdf.setFont("Helvetica-Bold", 22)
        pdf.drawString(left, top, "Wellbeing Assessment – How to Read This Report")

        # Subtitle
        _nm = _display_full_name(user)
        _dt_disp = getattr(run, "finished_at", None) or datetime.utcnow()
        if not isinstance(_dt_disp, datetime):
            _dt_disp = datetime.utcnow()
        pdf.setFont("Helvetica", 11)
        pdf.setFillGray(0.35)
        pdf.drawString(left, top - 22, f"For: {_nm}   •   Completed: {_dt_disp.strftime('%d %b %Y')}")
        pdf.setFillGray(0.0)

        # Paragraph writer
        def _write_para(y, text, font_size=12, leading=16, indent=0):
            import textwrap as _tw
            pdf.setFont("Helvetica", font_size)
            wrapped = _tw.fill(text, width=max(20, int((line_w - indent) / 6.0)))
            t = pdf.beginText()
            t.setTextOrigin(left + indent, y)
            t.setLeading(leading)
            for ln in wrapped.split("\n"):
                t.textLine(ln)
            pdf.drawText(t)
            lines = wrapped.count("\n") + 1
            return y - lines * leading

        def _write_heading(y, text):
            pdf.setFont("Helvetica-Bold", 14)
            pdf.drawString(left, y, text)
            return y - 18

        y = top - 54
        y = _write_heading(y, "Purpose of This Report")
        y = _write_para(y, (
            "This report provides a snapshot of your current wellbeing across four key areas — "
            "Nutrition, Training, Resilience, and Recovery. It combines your assessment results "
            "with goal-oriented OKRs to help you focus on the habits that drive performance and wellbeing.")) - 8

        y = _write_heading(y, "How to Read Your Scores")
        y = _write_para(y, (
            "Overall Score summarises balance across all pillars (out of 100). Pillar bars show strengths and "
            "areas that need attention: Strong (≥ 80), Good (60–79), Needs Focus (< 60).")) - 8

        y = _write_heading(y, "Understanding Objectives and Key Results (OKRs)")
        y = _write_para(y, (
            "Each pillar includes a Quarter Objective — a focused aim for the next 12 weeks — and up to three "
            "Key Results (KRs), which are measurable actions or outcomes that indicate progress toward the objective.")) - 6
        # Example block
        pdf.setFont("Helvetica-Oblique", 11)
        pdf.drawString(left + 12, y, "Example:")
        y -= 16
        pdf.setFont("Helvetica", 11)
        y = _write_para(y, "Quarter Objective: Improve overall nutrition quality.", font_size=11, indent=12)
        y = _write_para(y, "1. Increase fruit and vegetable intake.", font_size=11, indent=12)
        y = _write_para(y, "2. Reduce processed food consumption.", font_size=11, indent=12)
        y = _write_para(y, "3. Maintain adequate protein intake.", font_size=11, indent=12) - 8

        y = _write_heading(y, "How to Use This Report")
        y = _write_para(y, (
            "Review your lowest pillar for the biggest impact, track progress using the listed KRs, and re-assess "
            "each quarter to measure improvement and adjust goals.")) - 8

        y = _write_heading(y, "Next Steps")
        y = _write_para(y, (
            "Focus on 1–2 pillars over the next quarter, embed the KRs as weekly habits, and revisit your goals in 12 weeks."))

        # Footer (intro page)
        pdf.setFillGray(0.35)
        pdf.setFont("Helvetica", 9)
        pdf.drawRightString(right, 18, f"{BRAND_FOOTER} — Confidential wellbeing report")
        pdf.setFillGray(0.0)
        pdf.showPage()

        # ── Page 2: Dashboard image ─────────────────────────────────────────
        pdf.drawImage(jpg_path, 0, 0, width=width, height=height, preserveAspectRatio=True, mask='auto')
        dt = getattr(run, "finished_at", None) or datetime.utcnow()
        if not isinstance(dt, datetime):
            dt = datetime.utcnow()
        pdf.setFillGray(0.3)
        pdf.setFont("Helvetica", 9)
        pdf.drawString(20, 14, f"Completed on: {dt.strftime('%B %d, %Y')}")
        pdf.setFillGray(0.0)

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

def generate_assessment_dashboard_html(run_id: int) -> str:
    _audit("dashboard_html_start", "ok", {"run_id": run_id})
    user, run, pillars = _collect_report_data(run_id)
    if not user or not run:
        raise ValueError("Assessment run not found")

    okr_map = _fetch_okrs_for_run(run.id)
    ordered_keys = _pillar_order()
    pr_map = {getattr(pr, "pillar_key", ""): pr for pr in pillars}

    combined = getattr(run, "combined_overall", None)
    if combined is None:
        vals = []
        for k in ordered_keys:
            pr = pr_map.get(k)
            if pr and getattr(pr, "overall", None) is not None:
                vals.append(int(getattr(pr, "overall", 0) or 0))
        combined = round(sum(vals) / max(1, len(vals))) if vals else 0
    combined = int(combined)

    def _score_bucket(pct: int) -> str:
        if pct >= 80:
            return "high"
        if pct >= 60:
            return "mid"
        return "low"

    def _concept_scores_for(pr: PillarResult | None) -> Dict[str, float]:
        raw = getattr(pr, "concept_scores", None)
        if not raw:
            return {}
        if isinstance(raw, dict):
            return raw
        if isinstance(raw, str):
            try:
                data = json.loads(raw)
                if isinstance(data, dict):
                    return data
            except Exception:
                return {}
        try:
            return dict(raw)
        except Exception:
            return {}

    def _score_row(label: str, pct: int | None) -> str:
        if pct is None:
            return ""
        pct = max(0, min(100, int(round(pct))))
        bucket = _score_bucket(pct)
        return (
            "<div class='score-row'>"
            f"<div class='score-label'>{html.escape(label)}</div>"
            "<div class='score-track'>"
            f"<span class='score-fill {bucket}' style='width:{pct}%;'></span>"
            "</div>"
            f"<div class='score-value'>{pct}%</div>"
            "</div>"
        )

    def _concept_block(pr: PillarResult | None) -> str:
        scores = _concept_scores_for(pr)
        if not scores:
            return ""
        rows = []
        for code in sorted(scores.keys(), key=lambda c: _concept_display(c).lower()):
            val = scores.get(code)
            if val is None:
                continue
            pct = max(0, min(100, int(round(float(val)))))
            bucket = _score_bucket(pct)
            rows.append(
                "<div class='concept-row'>"
                f"<div class='concept-name'>{html.escape(_concept_display(code))}</div>"
                "<div class='concept-track'>"
                f"<span class='concept-fill {bucket}' style='width:{pct}%;'></span>"
                "</div>"
                f"<div class='concept-score'>{pct}%</div>"
                "</div>"
            )
        if not rows:
            return ""
        return f"<div class='concept-block'>{''.join(rows)}</div>"

    sections = []
    today = _today_str()
    for key in ordered_keys:
        pr = pr_map.get(key)
        if not pr:
            continue
        score = int(getattr(pr, "overall", 0) or 0)
        okr = okr_map.get(key, {})
        objective = html.escape(okr.get("objective", "") or "Not available yet.")
        krs = okr.get("krs") or []
        kr_lines = "".join(f"<li>{html.escape(kr)}</li>" for kr in krs[:3] if kr) or "<li>No key results yet.</li>"

        score_pct = max(0, min(100, score))
        sections.append(
            f"<section data-pillar='{html.escape(key)}'>"
            "<div class='pillar-head'>"
            f"<h2>{html.escape(_title_for_pillar(key))}</h2>"
            "<div class='pillar-score'>"
            f"<span class='score-value'>{score_pct}%</span>"
            "<div class='score-track'>"
            f"<span class='score-fill {_score_bucket(score_pct)}' style='width:{score_pct}%'></span>"
            "</div>"
            "</div>"
            "</div>"
            f"{_concept_block(pr)}"
            "<div class='okr-card'>"
            "<h3>This Quarter Objective</h3>"
            f"<p>{objective}</p>"
            "<h3>Key Results</h3>"
            f"<ul>{kr_lines}</ul>"
            "</div>"
            "</section>"
        )

    first = (getattr(user, "first_name", None) or "").strip() or "there"
    score_rows = [
        _score_row("Combined", combined),
        _score_row("Nutrition", int(getattr(pr_map.get("nutrition"), "overall", None) or 0) if pr_map.get("nutrition") else None),
        _score_row("Training", int(getattr(pr_map.get("training"), "overall", None) or 0) if pr_map.get("training") else None),
        _score_row("Resilience", int(getattr(pr_map.get("resilience"), "overall", None) or 0) if pr_map.get("resilience") else None),
        _score_row("Recovery", int(getattr(pr_map.get("recovery"), "overall", None) or 0) if pr_map.get("recovery") else None),
    ]
    score_panel = "".join([row for row in score_rows if row]) or "<p class='score-empty'>Scores will appear here once available.</p>"
    html_doc = f"""<!DOCTYPE html>
<html lang='en'>
<head>
  <meta charset='utf-8'/>
  <meta name='viewport' content='width=device-width, initial-scale=1'/>
  <title>Your Wellbeing Dashboard</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; margin: 0; padding: 16px; background: #f5f5f5; }}
    .card {{ background: #fff; border-radius: 12px; padding: 16px; margin-bottom: 16px; box-shadow: 0 2px 6px rgba(0,0,0,0.06); }}
    .summary-card {{ display: flex; flex-direction: column; gap: 16px; }}
    .summary-main h1 {{ font-size: 1.45rem; margin-bottom: 4px; }}
    .summary-main p {{ margin: 4px 0; color: #333; }}
    .score-panel {{ background: #f7f9fc; border-radius: 12px; padding: 12px; }}
    .score-empty {{ margin: 0; color: #6b7280; font-size: 0.95rem; }}
    .score-row {{ display: flex; align-items: center; gap: 12px; margin-bottom: 12px; }}
    .score-row:last-child {{ margin-bottom: 0; }}
    .score-label {{ flex: 0 0 95px; font-weight: 600; color: #1f2933; }}
    .score-track {{ flex: 1; height: 8px; border-radius: 999px; background: #e4e8f1; overflow: hidden; }}
    .score-fill {{ display: block; height: 100%; border-radius: 999px; }}
    .score-fill.high {{ background: linear-gradient(90deg, #0ba360, #3cba92); }}
    .score-fill.mid {{ background: linear-gradient(90deg, #f6d365, #fda085); }}
    .score-fill.low {{ background: linear-gradient(90deg, #f76b1c, #f54b64); }}
    .score-value {{ width: 56px; text-align: right; font-weight: 600; color: #111827; font-variant-numeric: tabular-nums; }}
    .pillars-card section {{ margin-bottom: 32px; border-bottom: 1px solid #f0f0f0; padding-bottom: 24px; }}
    .pillars-card section:last-child {{ border-bottom: none; padding-bottom: 0; }}
    .pillar-head {{ display: flex; flex-direction: column; gap: 8px; }}
    .pillar-head h2 {{ font-size: 1.2rem; margin: 0; color: #0f172a; }}
    .pillar-score {{ display: flex; align-items: center; gap: 12px; }}
    .pillar-score .score-value {{ width: auto; }}
    .concept-block {{ margin: 12px 0 16px; border: 1px solid #edf1f7; border-radius: 12px; padding: 12px; background: #fafcff; }}
    .concept-row {{ display: flex; align-items: center; gap: 12px; margin-bottom: 10px; }}
    .concept-row:last-child {{ margin-bottom: 0; }}
    .concept-name {{ flex: 0 0 45%; font-weight: 600; color: #111827; }}
    .concept-track {{ flex: 1; height: 6px; border-radius: 999px; background: #e4e8f1; overflow: hidden; }}
    .concept-fill {{ display: block; height: 100%; border-radius: 999px; }}
    .concept-fill.high {{ background: linear-gradient(90deg, #0ba360, #3cba92); }}
    .concept-fill.mid {{ background: linear-gradient(90deg, #f6d365, #fda085); }}
    .concept-fill.low {{ background: linear-gradient(90deg, #f76b1c, #f54b64); }}
    .concept-score {{ width: 48px; text-align: right; font-weight: 600; font-variant-numeric: tabular-nums; color: #111827; }}
    .okr-card h3 {{ font-size: 1rem; margin: 12px 0 6px; color: #475467; }}
    .okr-card p {{ margin: 0 0 8px; color: #1f2933; line-height: 1.4; }}
    .okr-card ul {{ padding-left: 18px; margin: 0; color: #1f2933; }}
    @media (min-width: 720px) {{
      .summary-card {{ flex-direction: row; justify-content: space-between; align-items: flex-start; }}
      .summary-main {{ flex: 1; }}
      .score-panel {{ flex: 0 0 320px; }}
      .pillar-head {{ flex-direction: row; justify-content: space-between; align-items: center; }}
    }}
  </style>
 </head>
 <body>
   <div class='card summary-card'>
     <div class='summary-main'>
       <h1>Your Wellbeing Dashboard</h1>
       <p>Hi {html.escape(first)}, here's your latest assessment snapshot.</p>
       <p style='color:#475467;'>Updated {html.escape(today)}</p>
     </div>
     <div class='score-panel'>
       {score_panel}
     </div>
   </div>
   <div class='card pillars-card'>
     {''.join(sections)}
   </div>
 </body>
</html>"""

    out_dir = _reports_root_for_user(user.id)
    out_path = os.path.join(out_dir, "latest.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html_doc)
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
def generate_assessment_summary_pdf(start: date | str, end: date | str, *, club_id: int | None = None) -> str:
    """
    Generate a PDF summarising assessments completed within the date range [start, end] (inclusive).
    Returns absolute filesystem path to the PDF.
    """
    start_dt, end_dt, start_str, end_str = _normalise_date_range(start, end)
    _audit("summary_report_start", "ok", {"start": start_str, "end": end_str})
    try:
        rows = _collect_summary_rows(start_dt, end_dt, club_id=club_id)
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
