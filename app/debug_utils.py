import json
import os
from typing import Any, Optional


def _truthy(value: Optional[str]) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


def debug_enabled() -> bool:
    return _truthy(os.getenv("AI_COACH_DEBUG"))


def debug_log(message: str, payload: Optional[dict[str, Any]] = None, tag: str = "debug") -> None:
    if not debug_enabled():
        return
    try:
        if payload is None:
            print(f"[{tag}] {message}")
        else:
            try:
                payload_str = json.dumps(payload, ensure_ascii=False, default=str)
            except Exception:
                payload_str = str(payload)
            print(f"[{tag}] {message} :: {payload_str}")
    except Exception:
        pass
