import type { CapacitorConfig } from "@capacitor/cli";

const DEFAULT_SERVER_URL = "https://app.coachsense.ai";
const serverUrl = String(process.env.CAP_SERVER_URL || DEFAULT_SERVER_URL).trim() || DEFAULT_SERVER_URL;

const config: CapacitorConfig = {
  appId: "coach.healthsense.app",
  appName: "HealthSense",
  webDir: "capacitor-web",
  appendUserAgent: " HealthSenseIOS/1.0",
  backgroundColor: "#f6f1e7",
  ios: {
    contentInset: "never",
    scrollEnabled: true,
    preferredContentMode: "mobile",
  },
  server: {
    url: serverUrl,
    cleartext: serverUrl.startsWith("http://"),
    errorPath: "error.html",
  },
};

export default config;
