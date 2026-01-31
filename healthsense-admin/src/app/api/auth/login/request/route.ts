import { NextResponse } from "next/server";

export async function POST(request: Request) {
  const base = process.env.API_BASE_URL;
  if (!base) {
    return NextResponse.json({ error: "API_BASE_URL is not set" }, { status: 500 });
  }
  const body = await request.json().catch(() => ({}));
  const res = await fetch(`${base.replace(/\/+$/, "")}/api/v1/auth/login/request`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const text = await res.text();
  if (!res.ok) {
    return NextResponse.json({ error: text || "Failed to request OTP" }, { status: res.status });
  }
  return NextResponse.json(JSON.parse(text));
}
