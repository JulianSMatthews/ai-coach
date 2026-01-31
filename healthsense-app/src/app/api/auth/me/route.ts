import { NextResponse } from "next/server";
import { headers } from "next/headers";

export async function GET() {
  const base = process.env.API_BASE_URL;
  if (!base) {
    return NextResponse.json({ error: "API_BASE_URL is not set" }, { status: 500 });
  }
  const cookieHeader = (await headers()).get("cookie") || "";
  const match = cookieHeader.match(/(?:^|; )hs_session=([^;]+)/);
  const session = match ? match[1] : null;
  if (!session) {
    return NextResponse.json({ error: "No session" }, { status: 401 });
  }
  const res = await fetch(`${base.replace(/\/+$/, "")}/api/v1/auth/me`, {
    headers: { "X-Session-Token": session },
  });
  const text = await res.text();
  if (!res.ok) {
    return NextResponse.json({ error: text || "Failed to fetch profile" }, { status: res.status });
  }
  return NextResponse.json(JSON.parse(text));
}
