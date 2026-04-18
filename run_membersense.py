from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.request
from pathlib import Path

import uvicorn

from membersense import config as membersense_config


TRUTHY = {"1", "true", "yes", "on"}


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in TRUTHY


def _addr_matches_port(addr: object, port: int) -> bool:
    value = str(addr or "")
    return value.endswith(f":{port}") or value.endswith(f"//localhost:{port}") or value == str(port)


def _read_ngrok_tunnel(domain: str | None, port: int, *, require_port: bool = True) -> str | None:
    try:
        with urllib.request.urlopen("http://127.0.0.1:4040/api/tunnels", timeout=1.0) as response:
            data = json.load(response)
    except Exception:
        return None
    tunnels = data.get("tunnels") or []
    for tunnel in tunnels:
        public_url = str(tunnel.get("public_url") or "")
        if not public_url.startswith("https://"):
            continue
        if domain and domain not in public_url:
            continue
        addr = (tunnel.get("config") or {}).get("addr")
        if _addr_matches_port(addr, port):
            return public_url
        if domain and not require_port:
            return public_url
    if domain:
        return None
    for tunnel in tunnels:
        public_url = str(tunnel.get("public_url") or "")
        addr = (tunnel.get("config") or {}).get("addr")
        if public_url.startswith("https://") and _addr_matches_port(addr, port):
            return public_url
    return None


def _tail_file(path: Path, max_bytes: int = 4000) -> str:
    try:
        if path.exists():
            return path.read_bytes()[-max_bytes:].decode("utf-8", errors="ignore")
    except Exception:
        return ""
    return ""


def _write_ngrok_config(path: Path, *, authtoken: str | None, port: int, domain: str | None) -> None:
    lines = ['version: "2"']
    if authtoken:
        lines.append(f"authtoken: {authtoken}")
    lines.extend(
        [
            "tunnels:",
            "  membersense:",
            "    proto: http",
            f"    addr: {port}",
        ]
    )
    if domain:
        lines.append(f"    domain: {domain}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _start_ngrok(port: int) -> str | None:
    if not _env_bool("MEMBERSENSE_NGROK", default=False):
        return None
    domain = (
        os.getenv("MEMBERSENSE_NGROK_DOMAIN")
        or os.getenv("API_NGROK_DOMAIN")
        or os.getenv("NGROK_DOMAIN")
        or ""
    ).strip() or None
    authtoken = (
        os.getenv("MEMBERSENSE_NGROK_AUTHTOKEN")
        or os.getenv("API_NGROK_AUTHTOKEN")
        or os.getenv("NGROK_AUTHTOKEN")
        or ""
    ).strip() or None
    retry_seconds = int(os.getenv("MEMBERSENSE_NGROK_RETRY_SECONDS", "45") or "45")
    log_path = Path("/tmp/membersense-ngrok.log")
    config_path = Path("/tmp/membersense-ngrok.yml")

    if _env_bool("MEMBERSENSE_KILL_NGROK_ON_START", default=False):
        subprocess.run(["pkill", "-f", "ngrok"], check=False)
        try:
            log_path.write_text("", encoding="utf-8")
        except Exception:
            pass
        time.sleep(0.5)

    existing = _read_ngrok_tunnel(domain, port, require_port=True)
    if existing:
        return existing

    wrong_port = _read_ngrok_tunnel(domain, port, require_port=False) if domain else None
    if wrong_port:
        print(
            f"[membersense][ngrok] {domain} is already online but is not pointing at port {port}."
        )
        print("[membersense][ngrok] Stop the other ngrok process or set MEMBERSENSE_KILL_NGROK_ON_START=1.")
        return None

    if not authtoken:
        print("[membersense][ngrok] No ngrok authtoken found; reserved domains may fail.")
    _write_ngrok_config(config_path, authtoken=authtoken, port=port, domain=domain)
    cmd = ["ngrok", "start", "membersense", "--config", str(config_path), "--log", str(log_path)]
    print(f"[membersense][ngrok] launching: {' '.join(cmd)}")
    log_file = open(log_path, "ab", buffering=0)
    subprocess.Popen(cmd, stdout=log_file, stderr=log_file)

    deadline = time.time() + max(retry_seconds, 1)
    while time.time() < deadline:
        public_url = _read_ngrok_tunnel(domain, port, require_port=True)
        if public_url:
            return public_url.rstrip("/")
        time.sleep(0.5)

    print("[membersense][ngrok] tunnel did not become ready.")
    tail = _tail_file(log_path)
    if tail:
        print("[membersense][ngrok] log tail:\n" + tail)
    return None


if __name__ == "__main__":
    port = int(os.getenv("MEMBERSENSE_PORT", "8010"))
    public_url = _start_ngrok(port)
    if public_url:
        os.environ["MEMBERSENSE_PUBLIC_BASE_URL"] = public_url
        membersense_config.TWILIO_STATUS_CALLBACK_BASE = public_url
        print("[membersense] public URL:", public_url)
        print("[membersense] admin URL:", f"{public_url}/admin")
        print("[membersense] Twilio SMS webhook:", f"{public_url}/webhooks/twilio")
    uvicorn.run(
        "membersense.main:app",
        host=os.getenv("MEMBERSENSE_HOST", "0.0.0.0"),
        port=port,
        reload=os.getenv("MEMBERSENSE_RELOAD", "1").lower() not in {"0", "false", "no", "off"},
    )
