# run.py
import subprocess, time, json, os, sys, urllib.request, webbrowser
import uvicorn

TWILIO_SANDBOX_URL = (
    "https://console.twilio.com/us1/develop/sms/try-it-out/whatsapp-learn"
    "?frameUrl=%2Fconsole%2Fsms%2Fwhatsapp%2Fsandbox"
)

def start_ngrok(port: int = 8000) -> str:
    # Start ngrok in the background (requires `brew install ngrok/ngrok/ngrok` and authtoken configured)
    subprocess.Popen(["ngrok", "http", str(port)], stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
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

def copy_to_clipboard(text: str):
    try:
        subprocess.run(["pbcopy"], input=text.encode("utf-8"), check=False)
        return True
    except Exception:
        return False

if __name__ == "__main__":
    try:
        public_url = start_ngrok(8000)
        webhook = f"{public_url}/webhooks/twilio"
        print("🌍 ngrok public URL:", public_url)
        print("📌 Paste this into Twilio Sandbox → ‘When a message comes in’ (POST):")
        print("    ", webhook)

        if copy_to_clipboard(webhook):
            print("📋 Copied webhook to clipboard.")

        try:
            webbrowser.open(TWILIO_SANDBOX_URL)
            print("🔗 Opened Twilio Sandbox settings in your browser.")
        except Exception:
            print("ℹ️ If the browser didn’t open, visit this page manually:")
            print("   ", TWILIO_SANDBOX_URL)
    except Exception as e:
        print("⚠️ Could not start ngrok or read URL:", e)

    # Run FastAPI with reload for dev
    uvicorn.run("app.api:app", host="0.0.0.0", port=8000, reload=True)
