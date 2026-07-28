import { NextResponse } from "next/server";

function clean(value: unknown, maxLength: number): string | undefined {
  const token = String(value || "").trim();
  return token ? token.slice(0, maxLength) : undefined;
}

function firstForwardedValue(value: string | null, maxLength: number): string | undefined {
  return clean(String(value || "").split(",")[0], maxLength);
}

export async function POST(request: Request) {
  const publicHost = firstForwardedValue(
    request.headers.get("x-forwarded-host") || request.headers.get("host"),
    255,
  )
    ?.split(":")[0]
    .toLowerCase();
  if (publicHost !== "coachsense.ai" && publicHost !== "www.coachsense.ai") {
    return NextResponse.json({ ok: true, recorded: false });
  }
  const apiBase = String(process.env.API_BASE_URL || "").trim().replace(/\/+$/, "");
  const adminToken = String(process.env.ADMIN_API_TOKEN || "").trim();
  const adminUserId = String(process.env.ADMIN_USER_ID || "").trim();
  if (!apiBase || !adminToken || !adminUserId) {
    return NextResponse.json({ error: "Landing view tracking is not configured." }, { status: 503 });
  }

  let submitted: Record<string, unknown> = {};
  try {
    const parsed = await request.json();
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
      submitted = parsed as Record<string, unknown>;
    }
  } catch {
    submitted = {};
  }

  const payload = {
    source: clean(submitted.source, 64) || "website",
    campaign: clean(submitted.campaign, 120),
    utm: submitted.utm && typeof submitted.utm === "object" ? submitted.utm : undefined,
    meta: submitted.meta && typeof submitted.meta === "object" ? submitted.meta : undefined,
    landing_path: clean(submitted.landing_path, 2000) || "/",
    referrer_url: clean(submitted.referrer_url, 2000) || clean(request.headers.get("referer"), 2000),
    user_agent: clean(request.headers.get("user-agent"), 1200),
    client_ip: firstForwardedValue(request.headers.get("x-forwarded-for"), 64),
    is_test: submitted.is_test === true,
  };

  try {
    const upstream = await fetch(`${apiBase}/api/v1/public/marketing/landing-view`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Admin-Token": adminToken,
        "X-Admin-User-Id": adminUserId,
      },
      body: JSON.stringify(payload),
      cache: "no-store",
    });
    if (!upstream.ok) {
      return NextResponse.json({ error: "Unable to record landing view." }, { status: upstream.status });
    }
    const data = await upstream.json().catch(() => ({ ok: true }));
    return NextResponse.json(data);
  } catch {
    return NextResponse.json({ error: "Unable to record landing view." }, { status: 502 });
  }
}
