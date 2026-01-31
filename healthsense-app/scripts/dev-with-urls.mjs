import { spawn } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

const rootDir = path.resolve(path.dirname(new URL(import.meta.url).pathname), "..", "..");
const appDir = path.resolve(path.dirname(new URL(import.meta.url).pathname), "..");

const readEnvFile = (filePath) => {
  try {
    const raw = fs.readFileSync(filePath, "utf8");
    const env = {};
    for (const line of raw.split(/\r?\n/)) {
      const trimmed = line.trim();
      if (!trimmed || trimmed.startsWith("#")) continue;
      const idx = trimmed.indexOf("=");
      if (idx === -1) continue;
      const key = trimmed.slice(0, idx).trim();
      let value = trimmed.slice(idx + 1).trim();
      if ((value.startsWith("\"") && value.endsWith("\"")) || (value.startsWith("'") && value.endsWith("'"))) {
        value = value.slice(1, -1);
      }
      env[key] = value;
    }
    return env;
  } catch {
    return {};
  }
};

const envRoot = readEnvFile(path.join(rootDir, ".env"));
const envLocal = readEnvFile(path.join(appDir, ".env.local"));
const mergedEnv = { ...envRoot, ...envLocal, ...process.env };

const port = mergedEnv.PORT || "3000";
const localUrl = `http://localhost:${port}`;
const publicUrl =
  mergedEnv.DASHBOARD_PUBLIC_URL ||
  (mergedEnv.DASHBOARD_NGROK_DOMAIN ? `https://${mergedEnv.DASHBOARD_NGROK_DOMAIN}` : "");

console.log(`🖥️  Dashboard (local): ${localUrl}`);
if (publicUrl) {
  console.log(`🌍 Dashboard (public): ${publicUrl}`);
} else {
  console.log("🌍 Dashboard (public): not set (see backend log for auto URL)");
}
console.log("");

const child = spawn("npm", ["run", "dev"], {
  cwd: appDir,
  stdio: "inherit",
  shell: process.platform === "win32",
});

child.on("exit", (code) => {
  process.exit(code ?? 0);
});
