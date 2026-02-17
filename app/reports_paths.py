from __future__ import annotations

import os


def resolve_reports_dir_with_source() -> tuple[str, str]:
    """
    Resolve the reports directory with explicit source metadata.
    Order:
    1) REPORTS_DIR env var (explicit)
    2) /var/data/reports when present (Render disk conventional mount path)
    3) local fallback ./public/reports
    """
    env_value = (os.getenv("REPORTS_DIR") or "").strip()
    if env_value:
        return env_value, "env:REPORTS_DIR"
    render_default = "/var/data/reports"
    if os.path.isdir(render_default):
        return render_default, "auto:render_mount"
    return os.path.join(os.getcwd(), "public", "reports"), "fallback:local_public_reports"


def resolve_reports_dir() -> str:
    path, _source = resolve_reports_dir_with_source()
    return path

