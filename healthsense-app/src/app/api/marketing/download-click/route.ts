import { NextResponse } from "next/server";

function clean(value: unknown, maxLength: number): string | undefined {
  const token = String(value || "").trim();
  return token ? token.slice(0, maxLength) : undefined;
}

export async function POST(request: Request) {
  const publicHost = clean(request.headers.get("x-forwarded-host") || request.headers.get("host"), 255)
    ?.split(",")[0]
    .trim()
    .split(":")[0]
    .toLowerCase();
  if (publicHost !== "coachsense.ai" && publicHost !== "www.coachsense.ai") {
    return NextResponse.json({ ok: true, recorded: false });
  }
  const apiBase = String(process.env.API_BASE_URL || "").trim().replace(/\/+$/, "");
  const adminToken = String(process.env.ADMIN_API_TOKEN || "").trim();
  const adminUserId = String(process.env.ADMIN_USER_ID || "").trim();
  if (!apiBase || !adminToken || !adminUserId) {
    return NextResponse.json({ error: "Download tracking is not configured." }, { status: 503 });
  }
  let submitted: Record<string, unknown> = {};
  try {
    const parsed = await request.json();
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) submitted = parsed as Record<string, unknown>;
  } catch {
    submitted = {};
  }
  const payload = {
    source: clean(submitted.source, 64) || "website",
    campaign: clean(submitted.campaign, 120),
    landing_url: clean(submitted.landing_url, 2000),
    destination_url: clean(submitted.destination_url, 2000),
    button_location: clean(submitted.button_location, 120),
    public_host: publicHost,
    user_agent: clean(request.headers.get("user-agent"), 1200),
  };
  try {
    const upstream = await fetch(`${apiBase}/api/v1/public/marketing/download-click`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Admin-Token": adminToken,
        "X-Admin-User-Id": adminUserId,
      },
      body: JSON.stringify(payload),
      cache: "no-store",
    });
    const data = await upstream.json().catch(() => ({ ok: upstream.ok }));
    return NextResponse.json(data, { status: upstream.status });
  } catch {
    return NextResponse.json({ error: "Unable to record download click." }, { status: 502 });
  }
}
