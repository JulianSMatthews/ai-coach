from __future__ import annotations

import os
from pathlib import Path


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    try:
        from dotenv import load_dotenv

        load_dotenv(dotenv_path=path, override=False)
        return
    except Exception:
        pass
    for line in path.read_text(encoding="utf-8").splitlines():
        value = line.strip()
        if not value or value.startswith("#") or "=" not in value:
            continue
        key, raw = value.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue
        os.environ[key] = raw.strip().strip("'\"")


_BASE_DIR = Path(__file__).resolve().parent
_load_env_file(_BASE_DIR / ".env.local")
_load_env_file(_BASE_DIR.parent / ".env")


def _env(name: str, default: str = "") -> str:
    return str(os.getenv(name) or default).strip()


APP_NAME = "MemberSense"
GYM_NAME = _env("MEMBERSENSE_GYM_NAME", "Anytime Fitness High Wycombe")
DATABASE_URL = _env("MEMBERSENSE_DATABASE_URL", "sqlite:///./membersense.db")

ADMIN_TOKEN = _env("MEMBERSENSE_ADMIN_TOKEN")
SESSION_SECRET = _env("MEMBERSENSE_SESSION_SECRET", ADMIN_TOKEN or "membersense-local-dev-secret-change-me")
SESSION_COOKIE_SECURE = _env(
    "MEMBERSENSE_SESSION_COOKIE_SECURE",
    "1" if os.getenv("RENDER") else "0",
).lower() in {"1", "true", "yes", "on"}
DEFAULT_COUNTRY_CODE = _env("MEMBERSENSE_DEFAULT_COUNTRY_CODE", "44")

TWILIO_ACCOUNT_SID = _env("MEMBERSENSE_TWILIO_ACCOUNT_SID", _env("TWILIO_ACCOUNT_SID"))
TWILIO_AUTH_TOKEN = _env("MEMBERSENSE_TWILIO_AUTH_TOKEN", _env("TWILIO_AUTH_TOKEN"))
TWILIO_FROM = _env("MEMBERSENSE_TWILIO_FROM", _env("TWILIO_FROM"))
TWILIO_MESSAGING_SERVICE_SID = _env(
    "MEMBERSENSE_TWILIO_MESSAGING_SERVICE_SID",
    _env("TWILIO_MESSAGING_SERVICE_SID"),
)
PUBLIC_BASE_URL = _env("MEMBERSENSE_PUBLIC_BASE_URL", _env("RENDER_EXTERNAL_URL"))
TWILIO_STATUS_CALLBACK_BASE = PUBLIC_BASE_URL

DRY_RUN_MESSAGES = _env("MEMBERSENSE_DRY_RUN", "1").lower() not in {"0", "false", "no", "off"}

BOOTSTRAP_STAFF_USERNAME = _env("MEMBERSENSE_BOOTSTRAP_STAFF_USERNAME")
BOOTSTRAP_STAFF_PASSWORD = _env("MEMBERSENSE_BOOTSTRAP_STAFF_PASSWORD")
BOOTSTRAP_STAFF_NAME = _env("MEMBERSENSE_BOOTSTRAP_STAFF_NAME", BOOTSTRAP_STAFF_USERNAME or "Owner")
BOOTSTRAP_STAFF_EMAIL = _env("MEMBERSENSE_BOOTSTRAP_STAFF_EMAIL")
