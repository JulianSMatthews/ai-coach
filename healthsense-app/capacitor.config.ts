import type { CapacitorConfig } from "@capacitor/cli";

const DEFAULT_SERVER_URL = "https://app.coachsense.ai";
const serverUrl = String(process.env.CAP_SERVER_URL || DEFAULT_SERVER_URL).trim() || DEFAULT_SERVER_URL;
const APP_VERSION = "1.1";

const config: CapacitorConfig = {
  // Keep this ID stable so future Android builds and the existing iOS listing
  // share the same application identity.
  appId: "coach.healthsense.app",
  appName: "CoachSense",
  webDir: "capacitor-web",
  backgroundColor: "#f6f1e7",
  android: {
    appendUserAgent: ` CoachSenseAndroid/${APP_VERSION}`,
  },
  ios: {
    appendUserAgent: ` CoachSenseIOS/${APP_VERSION}`,
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
