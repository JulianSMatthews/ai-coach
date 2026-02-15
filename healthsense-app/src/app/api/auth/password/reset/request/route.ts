import { NextResponse } from "next/server";

function extractUpstreamMessage(text: string): string {
  const raw = (text || "").trim();
  if (!raw) return "";
  try {
    const parsed = JSON.parse(raw) as unknown;
    if (typeof parsed === "string") return parsed;
    if (parsed && typeof parsed === "object") {
      const obj = parsed as Record<string, unknown>;
      const direct = obj.detail ?? obj.error ?? obj.message;
      if (typeof direct === "string") return direct;
    }
  } catch {}
  return raw;
}

export async function POST(request: Request) {
  const base = process.env.API_BASE_URL;
  if (!base) {
    return NextResponse.json({ error: "API_BASE_URL is not set" }, { status: 500 });
  }
  const body = await request.json().catch(() => ({}));
  let res: Response;
  try {
    res = await fetch(`${base.replace(/\/+$/, "")}/api/v1/auth/password/reset/request`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch (error) {
    const msg = error instanceof Error ? error.message : String(error);
    return NextResponse.json({ error: `Proxy request failed: ${msg}` }, { status: 502 });
  }
  const text = await res.text().catch(() => "");
  if (!res.ok) {
    return NextResponse.json(
      { error: extractUpstreamMessage(text) || "Failed to request reset code" },
      { status: res.status },
    );
  }
  if (!text.trim()) return NextResponse.json({});
  try {
    return NextResponse.json(JSON.parse(text));
  } catch {
    return NextResponse.json({ error: "Upstream returned invalid response." }, { status: 502 });
  }
}
