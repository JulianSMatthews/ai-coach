# run.py
import subprocess, time, json, os, sys, urllib.request
from typing import Optional
try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None  # type: ignore
import uvicorn

if load_dotenv is not None:
    load_dotenv(override=True)

def start_ngrok(port: int = 8000, region: Optional[str] = None, hostname: Optional[str] = None) -> str:
    # Start ngrok in the background (requires `brew install ngrok/ngrok/ngrok` and authtoken configured)
    cmd = ["ngrok", "http"]
    # ngrok auto-selects region when using reserved domains; only add flag when no hostname provided
    if region and not hostname:
        cmd.extend(["--region", region])
    if hostname:
        # ngrok v3 uses --domain; older binaries accept --hostname
        flag = "--domain" if "--domain" in subprocess.getoutput("ngrok help http") else "--hostname"
        cmd.extend([flag, hostname])
    cmd.append(str(port))
    print(f"[ngrok] launching command: {' '.join(cmd)}")
    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    # Wait for ngrok to boot and publish its API
    for _ in range(40):
        try:
            with urllib.request.urlopen("http://127.0.0.1:4040/api/tunnels") as r:
                data = json.load(r)
            tunnels = data.get("tunnels", [])
            https = next((t for t in tunnels if t.get("public_url","").startswith("https://")), None)
            if https:
                return https["public_url"]
        except Exception:
            time.sleep(0.5)
    raise RuntimeError("ngrok did not start or no public tunnel found")

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
    server_port = int(os.getenv("DEV_SERVER_PORT") or os.getenv("NGROK_PORT") or 8000)
    ngrok_region = os.getenv("NGROK_REGION")
    ngrok_domain = (os.getenv("NGROK_DOMAIN") or "").strip()
    machine_label = os.getenv("DEV_MACHINE_TAG") or os.uname().nodename
    disable_ngrok = os.getenv("DISABLE_NGROK", "").strip().lower() in {"1", "true", "yes"}
    if disable_ngrok:
        print("ℹ️  Skipping ngrok startup because DISABLE_NGROK is set.")
    else:
        print(f"[ngrok] requested domain={ngrok_domain or 'auto'} region={ngrok_region or 'default'} port={server_port}")
        try:
            public_url = start_ngrok(server_port, ngrok_region, hostname=ngrok_domain or None)
            webhook = f"{public_url}/webhooks/twilio"
            print("🌍 ngrok public URL:", public_url)
            print(f"🖥️  Machine tag: {machine_label} | Region: {ngrok_region or 'default'} | Port: {server_port}")
            if ngrok_domain:
                print(f"🔒 Using reserved ngrok domain '{ngrok_domain}'. Remember only one machine can claim it at a time.")
                print("   Twilio should stay pointed at:", webhook)
            else:
                print("📌 Paste this into Twilio Sandbox → ‘When a message comes in’ (POST):")
                print("    ", webhook)
        except Exception as e:
            print("⚠️ Could not start ngrok or read URL:", e)

    reload_pref = os.getenv("UVICORN_RELOAD", "true").strip().lower() not in {"0", "false", "no"}
    run_server(server_port, reload=reload_pref)
