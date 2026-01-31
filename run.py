# run.py
import subprocess, time, json, os, sys, urllib.request
from typing import Optional
from urllib.parse import urlparse
try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None  # type: ignore
import uvicorn

if load_dotenv is not None:
    load_dotenv(override=True)

def _select_tunnel(
    tunnels: list[dict],
    hostname: Optional[str],
    port: int,
    *,
    require_port: bool = False,
) -> Optional[str]:
    # Prefer matching by reserved hostname, then by local port.
    if hostname:
        for t in tunnels:
            public_url = t.get("public_url") or ""
            if hostname in public_url:
                return public_url
        return None
    for t in tunnels:
        cfg = t.get("config") or {}
        addr = cfg.get("addr") or ""
        if isinstance(addr, str) and addr.endswith(f":{port}"):
            return t.get("public_url")
    if require_port:
        return None
    https = next((t for t in tunnels if (t.get("public_url") or "").startswith("https://")), None)
    return https.get("public_url") if https else None


def _read_ngrok_tunnels(
    hostname: Optional[str],
    port: int,
    *,
    require_port: bool = False,
) -> Optional[str]:
    try:
        with urllib.request.urlopen("http://127.0.0.1:4040/api/tunnels") as r:
            data = json.load(r)
        tunnels = data.get("tunnels", [])
        if tunnels:
            return _select_tunnel(tunnels, hostname, port, require_port=require_port)
    except Exception:
        return None
    return None


def _tail_ngrok_log(max_bytes: int = 4000) -> str:
    log_path = "/tmp/ai-coach-ngrok.log"
    try:
        if os.path.exists(log_path):
            with open(log_path, "rb") as f:
                return f.read()[-max_bytes:].decode("utf-8", errors="ignore")
    except Exception:
        return ""
    return ""

def _write_ngrok_config(
    path: str,
    *,
    authtoken: str | None,
    api_port: int,
    api_domain: str | None,
    dashboard_port: int | None = None,
    dashboard_domain: str | None = None,
    admin_port: int | None = None,
    admin_domain: str | None = None,
) -> None:
    lines = ['version: "2"', "tunnels:"]
    if authtoken:
        lines.insert(1, f"authtoken: {authtoken}")
    lines.append("  api:")
    lines.append("    proto: http")
    lines.append(f"    addr: {api_port}")
    if api_domain:
        lines.append(f"    domain: {api_domain}")
    if dashboard_port is not None:
        lines.append("  dashboard:")
        lines.append("    proto: http")
        lines.append(f"    addr: {dashboard_port}")
        if dashboard_domain:
            lines.append(f"    domain: {dashboard_domain}")
    if admin_port is not None:
        lines.append("  admin:")
        lines.append("    proto: http")
        lines.append(f"    addr: {admin_port}")
        if admin_domain:
            lines.append(f"    domain: {admin_domain}")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

def start_ngrok_with_config(
    *,
    authtoken: str | None,
    api_port: int,
    api_domain: str | None,
    dashboard_port: int | None,
    dashboard_domain: str | None,
    admin_port: int | None,
    admin_domain: str | None,
    log_path: str,
    timeout_seconds: int = 60,
) -> tuple[Optional[str], Optional[str], Optional[str]]:
    config_path = "/tmp/ai-coach-ngrok.json"
    _write_ngrok_config(
        config_path,
        authtoken=authtoken,
        api_port=api_port,
        api_domain=api_domain,
        dashboard_port=dashboard_port,
        dashboard_domain=dashboard_domain,
        admin_port=admin_port,
        admin_domain=admin_domain,
    )
    cmd = ["ngrok", "start", "--all", "--config", config_path, "--log", log_path]
    print(f"[ngrok] launching command: {' '.join(cmd)}")
    log_file = open(log_path, "ab", buffering=0)
    subprocess.Popen(cmd, stdout=log_file, stderr=log_file)
    deadline = time.time() + max(0, timeout_seconds)
    api_url = None
    dash_url = None
    admin_url = None
    while time.time() < deadline:
        if api_url is None:
            api_url = _read_ngrok_tunnels(api_domain or None, api_port)
        if dashboard_port is not None and dash_url is None:
            dash_url = _read_ngrok_tunnels(dashboard_domain or None, dashboard_port, require_port=not bool(dashboard_domain))
        if admin_port is not None and admin_url is None:
            admin_url = _read_ngrok_tunnels(admin_domain or None, admin_port, require_port=not bool(admin_domain))
        if api_url and (dashboard_port is None or dash_url):
            if admin_port is None or admin_url:
                break
        time.sleep(0.5)
    return api_url, dash_url, admin_url


def start_ngrok(
    port: int = 8000,
    region: Optional[str] = None,
    hostname: Optional[str] = None,
    pooling_enabled: bool = False,
    require_port: bool = False,
) -> str:
    # Start ngrok in the background (requires `brew install ngrok/ngrok/ngrok` and authtoken configured)
    existing = _read_ngrok_tunnels(hostname, port, require_port=require_port)
    if existing:
        return existing
    cmd = ["ngrok", "http"]
    # ngrok auto-selects region when using reserved domains; only add flag when no hostname provided
    if region and not hostname:
        cmd.extend(["--region", region])
    if hostname:
        # ngrok v3 uses --domain; older binaries accept --hostname
        flag = "--domain" if "--domain" in subprocess.getoutput("ngrok help http") else "--hostname"
        cmd.extend([flag, hostname])
    if pooling_enabled:
        cmd.append("--pooling-enabled")
    cmd.append(str(port))
    print(f"[ngrok] launching command: {' '.join(cmd)}")
    log_path = "/tmp/ai-coach-ngrok.log"
    log_file = open(log_path, "ab", buffering=0)
    subprocess.Popen(cmd, stdout=log_file, stderr=log_file)
    # Wait for ngrok to boot and publish its API
    for _ in range(40):
        try:
            public_url = _read_ngrok_tunnels(hostname, port, require_port=require_port)
            if public_url:
                return public_url
        except Exception:
            time.sleep(0.5)
    raise RuntimeError(f"ngrok did not start or no public tunnel found (see {log_path})")

def run_server(port: int, reload: bool = True):
    """Start uvicorn, retrying without reload if the watcher lacks permission."""
    try:
        uvicorn.run("app.api:app", host="0.0.0.0", port=port, reload=reload)
    except (PermissionError, OSError) as exc:
        err_no = getattr(exc, "errno", None)
        if reload and err_no == 1:
            print("ℹ️  Reload watcher not permitted; restarting server without reload.")
            uvicorn.run("app.api:app", host="0.0.0.0", port=port, reload=False)
        else:
            raise

if __name__ == "__main__":
    server_port = int(
        os.getenv("DEV_SERVER_PORT")
        or os.getenv("API_NGROK_PORT")
        or os.getenv("NGROK_PORT")
        or 8000
    )
    ngrok_region = os.getenv("NGROK_REGION")
    ngrok_domain = (os.getenv("API_NGROK_DOMAIN") or os.getenv("NGROK_DOMAIN") or "").strip()
    ngrok_pooling = (os.getenv("API_NGROK_POOLING") or os.getenv("NGROK_POOLING") or "").strip().lower() in {
        "1",
        "true",
        "yes",
    }
    ngrok_authtoken = (os.getenv("API_NGROK_AUTHTOKEN") or os.getenv("NGROK_AUTHTOKEN") or "").strip() or None
    app_domain = (
        os.getenv("HSAPP_NGROK_DOMAIN")
        or os.getenv("APP_NGROK_DOMAIN")
        or os.getenv("DASHBOARD_NGROK_DOMAIN")
        or ""
    ).strip()
    app_port = int(os.getenv("HSAPP_PORT") or os.getenv("APP_PORT") or os.getenv("DASHBOARD_PORT") or "3000")
    app_pooling_env = os.getenv("HSAPP_NGROK_POOLING", "").strip().lower()
    if not app_pooling_env:
        app_pooling_env = os.getenv("APP_NGROK_POOLING", "").strip().lower()
    if not app_pooling_env:
        app_pooling_env = os.getenv("DASHBOARD_NGROK_POOLING", "").strip().lower()
    app_pooling = app_pooling_env in {"1", "true", "yes"}
    if app_domain and app_pooling_env == "":
        app_pooling = True
    enable_app_ngrok = (
        os.getenv("HSAPP_NGROK", "").strip().lower() in {"1", "true", "yes"}
        or os.getenv("APP_NGROK", "").strip().lower() in {"1", "true", "yes"}
        or os.getenv("DASHBOARD_NGROK", "").strip().lower() in {"1", "true", "yes"}
        or bool(app_domain)
    )
    admin_domain = (os.getenv("HSADMIN_NGROK_DOMAIN") or "").strip()
    admin_port = int(os.getenv("HSADMIN_PORT") or "3001")
    admin_pooling_env = os.getenv("HSADMIN_NGROK_POOLING", "").strip().lower()
    admin_pooling = admin_pooling_env in {"1", "true", "yes"}
    if admin_domain and admin_pooling_env == "":
        admin_pooling = True
    enable_admin_ngrok = os.getenv("HSADMIN_NGROK", "").strip().lower() in {"1", "true", "yes"} or bool(admin_domain)
    machine_label = os.getenv("DEV_MACHINE_TAG") or os.uname().nodename
    kill_ngrok = os.getenv("KILL_NGROK_ON_START", "").strip().lower() in {"1", "true", "yes"}
    disable_ngrok = os.getenv("DISABLE_NGROK", "").strip().lower() in {"1", "true", "yes"}
    api_url = None
    app_url = None
    admin_url = None
    if kill_ngrok:
        try:
            subprocess.run(["pkill", "-f", "ngrok"], check=False)
            print("🧹 Killed existing ngrok processes (KILL_NGROK_ON_START=1).")
            log_path = "/tmp/ai-coach-ngrok.log"
            try:
                if os.path.exists(log_path):
                    open(log_path, "wb").close()
                    print("🧹 Cleared ngrok log.")
            except Exception:
                pass
            time.sleep(0.5)
        except Exception as e:
            print(f"⚠️ Failed to kill ngrok processes: {e!r}")
    if disable_ngrok:
        print("ℹ️  Skipping ngrok startup because DISABLE_NGROK is set.")
        api_url = f"http://localhost:{server_port}"
    else:
        print(f"[ngrok] requested domain={ngrok_domain or 'auto'} region={ngrok_region or 'default'} port={server_port}")
        retry_seconds = int(os.getenv("NGROK_START_RETRY_SECONDS", "60"))
        started = False
        start_deadline = time.time() + max(0, retry_seconds)
        attempt = 0
        spawned = False
        log_path = "/tmp/ai-coach-ngrok.log"
        if enable_app_ngrok or enable_admin_ngrok:
            if not ngrok_authtoken:
                print("⚠️ NGROK_AUTHTOKEN is not set; ngrok may fail with ERR_NGROK_4018.")
            api_url, app_url, admin_url = start_ngrok_with_config(
                authtoken=ngrok_authtoken,
                api_port=server_port,
                api_domain=ngrok_domain or None,
                dashboard_port=app_port if enable_app_ngrok else None,
                dashboard_domain=app_domain or None,
                admin_port=admin_port if enable_admin_ngrok else None,
                admin_domain=admin_domain or None,
                log_path=log_path,
                timeout_seconds=retry_seconds,
            )
            if api_url:
                webhook = f"{api_url}/webhooks/twilio"
                print("🌍 ngrok public URL:", api_url)
                print(f"🖥️  Machine tag: {machine_label} | Region: {ngrok_region or 'default'} | Port: {server_port}")
                if ngrok_domain:
                    print(f"🔒 Using reserved ngrok domain '{ngrok_domain}'. Remember only one machine can claim it at a time.")
                    print("   Twilio should stay pointed at:", webhook)
                else:
                    print("📌 Paste this into Twilio Sandbox → ‘When a message comes in’ (POST):")
                    print("    ", webhook)
                started = True
            if app_url:
                print("🧭 App URL:", app_url)
                if app_domain:
                    print(f"🔒 Using reserved ngrok domain '{app_domain}' for app.")
            else:
                if enable_app_ngrok:
                    print("⚠️ app ngrok not ready; continuing without app tunnel.")
            if admin_url:
                print("🧭 Admin URL:", admin_url)
                if admin_domain:
                    print(f"🔒 Using reserved ngrok domain '{admin_domain}' for admin.")
            else:
                if enable_admin_ngrok:
                    print("⚠️ admin ngrok not ready; continuing without admin tunnel.")
        else:
            while True:
                attempt += 1
                try:
                    if not spawned:
                        spawned = True
                        public_url = start_ngrok(
                            server_port,
                            ngrok_region,
                            hostname=ngrok_domain or None,
                            pooling_enabled=ngrok_pooling,
                        )
                    else:
                        public_url = _read_ngrok_tunnels(ngrok_domain or None, server_port)
                        if not public_url:
                            raise RuntimeError("ngrok tunnel not ready")
                    webhook = f"{public_url}/webhooks/twilio"
                    print("🌍 ngrok public URL:", public_url)
                    print(f"🖥️  Machine tag: {machine_label} | Region: {ngrok_region or 'default'} | Port: {server_port}")
                    if ngrok_domain:
                        print(f"🔒 Using reserved ngrok domain '{ngrok_domain}'. Remember only one machine can claim it at a time.")
                        print("   Twilio should stay pointed at:", webhook)
                    else:
                        print("📌 Paste this into Twilio Sandbox → ‘When a message comes in’ (POST):")
                        print("    ", webhook)
                    api_url = public_url
                    started = True
                    break
                except Exception as e:
                    existing_url = _read_ngrok_tunnels(ngrok_domain or None, server_port)
                    if existing_url:
                        webhook = f"{existing_url}/webhooks/twilio"
                        print("⚠️ ngrok start failed; using existing tunnel:", existing_url)
                        if ngrok_domain:
                            print(f"🔒 Using reserved ngrok domain '{ngrok_domain}'. Remember only one machine can claim it at a time.")
                            print("   Twilio should stay pointed at:", webhook)
                        api_url = existing_url
                        started = True
                        break
                    tail = _tail_ngrok_log()
                    is_domain_busy = "ERR_NGROK_334" in tail or "already online" in tail
                    if is_domain_busy and time.time() < start_deadline:
                        remaining = int(start_deadline - time.time())
                        print(f"⚠️ ngrok domain busy; retrying in 2s (remaining {remaining}s)")
                        time.sleep(2)
                        continue
                    print("⚠️ Could not start ngrok or read URL:", e)
                    if tail:
                        print("⚠️ ngrok log tail:\n" + tail)
                    break

        # Late check: ngrok can come up after the initial wait; update api_url if found.
        if not api_url:
            for _ in range(10):
                api_url = _read_ngrok_tunnels(ngrok_domain or None, server_port)
                if api_url:
                    print(f"✅ ngrok tunnel detected after startup: {api_url}")
                    break
                time.sleep(0.5)

    reports_base = (
        os.getenv("REPORTS_BASE_URL")
        or os.getenv("PUBLIC_REPORT_BASE_URL")
        or os.getenv("API_PUBLIC_BASE_URL")
        or os.getenv("PUBLIC_BASE_URL")
        or ""
    ).strip()
    if reports_base and not reports_base.startswith(("http://", "https://")):
        reports_base = f"https://{reports_base}"
    if not reports_base:
        reports_base = api_url or f"http://localhost:{server_port}"
    if not app_url and not enable_app_ngrok:
        app_url = f"http://localhost:{app_port}"
    if not admin_url and not enable_admin_ngrok:
        admin_url = f"http://localhost:{admin_port}"
    print("\n════════════════════════════════════════════════════════════════════════")
    print("📌 Mount Summary")
    print(f"API:       {api_url or 'not ready'}")
    print(f"Reports:   {reports_base.rstrip('/')}/reports")
    print(f"HSAPP:     {app_url or 'not ready'}")
    print(f"HSADMIN:   {admin_url or 'not ready'}")
    print("════════════════════════════════════════════════════════════════════════\n")

    reload_pref = os.getenv("UVICORN_RELOAD", "true").strip().lower() not in {"0", "false", "no"}
    run_server(server_port, reload=reload_pref)
