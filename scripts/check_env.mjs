#!/usr/bin/env node
/*
Environment check for frontend deploys.
Usage: node scripts/check_env.mjs --service hsapp|hsadmin
*/

const args = process.argv.slice(2);
const serviceIdx = args.indexOf("--service");
const service = serviceIdx >= 0 ? args[serviceIdx + 1] : "hsapp";
const warnOptional = args.includes("--warn-optional");

const REQUIRED = {
  hsapp: [
    ["API_BASE_URL"],
    ["ADMIN_API_TOKEN"],
    ["ADMIN_USER_ID"],
  ],
  hsadmin: [
    ["API_BASE_URL"],
    ["ADMIN_API_TOKEN"],
    ["ADMIN_USER_ID"],
  ],
};

const OPTIONAL = {
  hsapp: ["NEXT_PUBLIC_DEFAULT_USER_ID"],
  hsadmin: ["NEXT_PUBLIC_HSAPP_BASE_URL", "NEXT_PUBLIC_APP_BASE_URL"],
};

function isSet(key) {
  const v = process.env[key];
  return typeof v === "string" && v.trim().length > 0;
}

function missingGroups(groups) {
  const missing = [];
  for (const group of groups) {
    if (group.some(isSet)) continue;
    missing.push(group.length === 1 ? group[0] : group.join(" | "));
  }
  return missing;
}

if (!REQUIRED[service]) {
  console.error("[env-check] Unknown service:", service);
  process.exit(2);
}

const missing = missingGroups(REQUIRED[service]);
if (missing.length) {
  console.error("[env-check] Missing required environment variables:");
  for (const item of missing) {
    console.error("  -", item);
  }
  process.exit(1);
}

if (warnOptional && OPTIONAL[service]) {
  const optionalMissing = OPTIONAL[service].filter((key) => !isSet(key));
  if (optionalMissing.length) {
    console.log("[env-check] Optional vars missing:");
    for (const key of optionalMissing) {
      console.log("  -", key);
    }
  }
}

console.log("[env-check] OK");
