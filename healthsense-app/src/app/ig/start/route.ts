import { NextResponse } from "next/server";

function getBaseUrl() {
  const base = process.env.API_BASE_URL;
  if (!base) {
    throw new Error("API_BASE_URL is not set");
  }
  return base.replace(/\/+$/, "");
}

function toBool(value: string | null | undefined): boolean {
  const token = String(value || "").trim().toLowerCase();
  return token === "1" || token === "true" || token === "yes" || token === "on";
}

function cleanValue(value: string | null | undefined, maxLen = 255): string | undefined {
  const raw = String(value || "").trim();
  if (!raw) return undefined;
  return raw.slice(0, maxLen);
}

function firstToken(value: string | null | undefined, maxLen = 64): string | undefined {
  const raw = cleanValue(value, 512);
  if (!raw) return undefined;
  const token = raw.split(",")[0]?.trim();
  if (!token) return undefined;
  return token.slice(0, maxLen);
}

function normalizeIntroAvatarParam(value: string | null | undefined): "1" | "0" | undefined {
  const raw = String(value || "").trim().toLowerCase();
  if (!raw) return undefined;
  if (raw === "0" || raw === "false" || raw === "no" || raw === "off") return "0";
  if (raw === "1" || raw === "true" || raw === "yes" || raw === "on") return "1";
  return undefined;
}

function buildLandingPath(url: URL): string {
  const params = new URLSearchParams(url.searchParams);
  params.delete("k");
  const qs = params.toString();
  const path = `${url.pathname}${qs ? `?${qs}` : ""}`;
  return path.slice(0, 2000);
}

function getPublicOrigin(request: Request): string {
  const reqUrl = new URL(request.url);
  const forwardedHostRaw = request.headers.get("x-forwarded-host") || request.headers.get("host") || "";
  const forwardedProtoRaw = request.headers.get("x-forwarded-proto") || reqUrl.protocol.replace(":", "");
  const host = forwardedHostRaw.split(",")[0]?.trim();
  const protoToken = forwardedProtoRaw.split(",")[0]?.trim().toLowerCase();
  const proto = protoToken === "http" || protoToken === "https" ? protoToken : reqUrl.protocol.replace(":", "");
  if (!host) {
    return reqUrl.origin;
  }
  return `${proto}://${host}`;
}

function isMetaAnalyserUserAgent(value: string | null | undefined): boolean {
  const ua = String(value || "").trim().toLowerCase();
  if (!ua) return false;
  return [
    "facebookexternalhit",
    "facebot",
    "meta-externalagent",
    "meta-externalfetcher",
  ].some((token) => ua.includes(token));
}

export async function GET(request: Request) {
  const reqUrl = new URL(request.url);
  const origin = getPublicOrigin(request);
  const fallback = new URL("/login", origin);
  try {
    if (isMetaAnalyserUserAgent(request.headers.get("user-agent"))) {
      return NextResponse.redirect(fallback);
    }
    const base = getBaseUrl();
    const leadKey = (reqUrl.searchParams.get("k") || "").trim();
    const campaign = (reqUrl.searchParams.get("campaign") || reqUrl.searchParams.get("utm_campaign") || "").trim();
    const source = (reqUrl.searchParams.get("source") || reqUrl.searchParams.get("utm_source") || "instagram").trim();

    const utm: Record<string, string> = {};
    ["utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content"].forEach((key) => {
      const value = (reqUrl.searchParams.get(key) || "").trim();
      if (value) utm[key] = value;
    });

    const meta: Record<string, string> = {};
    const captureMeta = (targetKey: string, queryKeys: string[]) => {
      for (const key of queryKeys) {
        const value = cleanValue(reqUrl.searchParams.get(key), 255);
        if (value) {
          meta[targetKey] = value;
          return;
        }
      }
    };
    captureMeta("fbclid", ["fbclid"]);
    captureMeta("gclid", ["gclid"]);
    captureMeta("msclkid", ["msclkid"]);
    captureMeta("ttclid", ["ttclid"]);
    captureMeta("campaign_id", ["campaign_id", "meta_campaign_id"]);
    captureMeta("adset_id", ["adset_id", "meta_adset_id"]);
    captureMeta("ad_id", ["ad_id", "meta_ad_id"]);
    captureMeta("creative_id", ["creative_id", "meta_creative_id"]);
    captureMeta("placement", ["placement"]);

    const passThroughKeys = [
      "ad_name",
      "adset_name",
      "campaign_name",
      "site_source_name",
      "platform",
    ];
    passThroughKeys.forEach((key) => {
      const value = cleanValue(reqUrl.searchParams.get(key), 255);
      if (value) meta[key] = value;
    });

    const payload = {
      lead_key: leadKey || undefined,
      defer_create: true,
      is_test: toBool(reqUrl.searchParams.get("test")) || toBool(reqUrl.searchParams.get("is_test")),
      source,
      campaign: campaign || undefined,
      utm,
      meta: Object.keys(meta).length ? meta : undefined,
      landing_path: buildLandingPath(reqUrl),
      referrer_url: cleanValue(request.headers.get("referer"), 2000),
      client_ip: firstToken(request.headers.get("x-forwarded-for"), 64),
      user_agent: cleanValue(request.headers.get("user-agent"), 1200),
    };

    const upstream = await fetch(`${base}/api/v1/public/assessment/lead-start`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      cache: "no-store",
    });
    const text = await upstream.text().catch(() => "");
    if (!upstream.ok || !text.trim()) {
      const fail = new URL("/login", origin);
      fail.searchParams.set("lead", "failed");
      return NextResponse.redirect(fail);
    }

    let data: Record<string, unknown>;
    try {
      data = JSON.parse(text) as Record<string, unknown>;
    } catch {
      const fail = new URL("/login", origin);
      fail.searchParams.set("lead", "invalid");
      return NextResponse.redirect(fail);
    }

    const sessionToken = String(data.session_token || "").trim();
    const userId = String(data.user_id || "").trim();
    const deferred = toBool(String(data.deferred || ""));
    const leadToken = String(data.lead_token || "").trim();
    const firstQuestion = cleanValue(String(data.first_question || ""), 1200);
    const nextPathRaw = String(data.next_path || "").trim();
    const introAvatarParam = normalizeIntroAvatarParam(reqUrl.searchParams.get("intro_avatar"));
    const ttlSecondsRaw = Number(data.session_ttl_seconds || 0);
    const ttlSeconds = Number.isFinite(ttlSecondsRaw) && ttlSecondsRaw > 0 ? Math.floor(ttlSecondsRaw) : 60 * 60 * 3;
    if (deferred) {
      const nextPath =
        nextPathRaw.startsWith("/") && !nextPathRaw.startsWith("//")
          ? nextPathRaw
          : "/assessment/lead/chat?autostart=1&lead=1";
      if (!leadToken) {
        const fail = new URL("/login", origin);
        fail.searchParams.set("lead", "missing");
        return NextResponse.redirect(fail);
      }
      const redirectUrl = new URL(nextPath, origin);
      redirectUrl.searchParams.set("lt", leadToken);
      if (introAvatarParam) {
        redirectUrl.searchParams.set("intro_avatar", introAvatarParam);
      }
      if (toBool(reqUrl.searchParams.get("debug"))) {
        redirectUrl.searchParams.set("lead_debug", "1");
      }
      const response = NextResponse.redirect(redirectUrl);
      response.cookies.set("hs_session", "", {
        httpOnly: true,
        sameSite: "lax",
        path: "/",
        maxAge: 0,
        secure: process.env.NODE_ENV === "production",
      });
      response.cookies.set("hs_user_id", "", {
        httpOnly: false,
        sameSite: "lax",
        path: "/",
        maxAge: 0,
        secure: process.env.NODE_ENV === "production",
      });
      response.cookies.set("hs_lead_token", leadToken, {
        httpOnly: true,
        sameSite: "lax",
        path: "/",
        maxAge: ttlSeconds,
        secure: process.env.NODE_ENV === "production",
      });
      response.cookies.set("hs_lead_q1", firstQuestion || "", {
        httpOnly: true,
        sameSite: "lax",
        path: "/",
        maxAge: ttlSeconds,
        secure: process.env.NODE_ENV === "production",
      });
      return response;
    }

    const nextPath = nextPathRaw.startsWith("/") && !nextPathRaw.startsWith("//") ? nextPathRaw : `/assessment/${userId}/chat?autostart=1&lead=1`;
    if (!sessionToken || !userId) {
      const fail = new URL("/login", origin);
      fail.searchParams.set("lead", "missing");
      return NextResponse.redirect(fail);
    }

    const redirectUrl = new URL(nextPath, origin);
    if (introAvatarParam) {
      redirectUrl.searchParams.set("intro_avatar", introAvatarParam);
    }
    if (toBool(reqUrl.searchParams.get("debug"))) {
      redirectUrl.searchParams.set("lead_debug", "1");
    }
    const response = NextResponse.redirect(redirectUrl);
    response.cookies.set("hs_session", sessionToken, {
      httpOnly: true,
      sameSite: "lax",
      path: "/",
      maxAge: ttlSeconds,
      secure: process.env.NODE_ENV === "production",
    });
    response.cookies.set("hs_user_id", userId, {
      httpOnly: false,
      sameSite: "lax",
      path: "/",
      maxAge: ttlSeconds,
      secure: process.env.NODE_ENV === "production",
    });
    return response;
  } catch {
    return NextResponse.redirect(fallback);
  }
}
