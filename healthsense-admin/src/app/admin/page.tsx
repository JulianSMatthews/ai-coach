import Link from "next/link";
import AdminNav from "@/components/AdminNav";
import {
  getAdminAppEngagement,
  getAdminAssessmentHealth,
  getAdminCoachingTodayDrilldown,
  getAdminProfile,
  getAdminStats,
  getAdminUsageSummary,
} from "@/lib/api";

export const dynamic = "force-dynamic";

function stateChipClass(state?: string | null): string {
  const key = String(state || "").toLowerCase();
  if (key === "critical") return "border-[#c43d3d] bg-[#fdeaea] text-[#8c1d1d]";
  if (key === "warn") return "border-[#cc9a2f] bg-[#fff6e6] text-[#825b0b]";
  if (key === "ok") return "border-[#2f8b55] bg-[#eaf7ef] text-[#14532d]";
  return "border-[#d8d1c4] bg-[#f7f4ee] text-[#6b6257]";
}

function stateTileClass(state?: string | null): string {
  const key = String(state || "").toLowerCase();
  if (key === "critical") return "rounded-xl border border-[#c43d3d] bg-[#fdeaea] px-3 py-2";
  if (key === "warn") return "rounded-xl border border-[#cc9a2f] bg-[#fff6e6] px-3 py-2";
  if (key === "ok") return "rounded-xl border border-[#2f8b55] bg-[#eaf7ef] px-3 py-2";
  return "rounded-xl bg-[#f7f4ee] px-3 py-2";
}

export default async function AdminHome() {
  const profile = await getAdminProfile();
  const name = profile.user?.display_name || "Admin";
  let stats: Awaited<ReturnType<typeof getAdminStats>> | null = null;
  try {
    stats = await getAdminStats();
  } catch {
    stats = null;
  }
  let usage: Awaited<ReturnType<typeof getAdminUsageSummary>> | null = null;
  try {
    usage = await getAdminUsageSummary({ days: 7 });
  } catch {
    usage = null;
  }
  let health: Awaited<ReturnType<typeof getAdminAssessmentHealth>> | null = null;
  try {
    health = await getAdminAssessmentHealth({ days: 7, stale_minutes: 30 });
  } catch {
    health = null;
  }
  let appEngagement: Awaited<ReturnType<typeof getAdminAppEngagement>> | null = null;
  try {
    appEngagement = await getAdminAppEngagement({ days: 7 });
  } catch {
    appEngagement = null;
  }
  let giaToday: Awaited<ReturnType<typeof getAdminCoachingTodayDrilldown>> | null = null;
  try {
    giaToday = await getAdminCoachingTodayDrilldown();
  } catch {
    giaToday = null;
  }
  const appKpis = appEngagement?.top_kpis || {};
  const giaRatio = giaToday?.ratio || {};
  const giaTodayRatio = giaRatio.display || "—";
  const giaFailed = Number(giaRatio.refresh_failed ?? 0) || 0;
  const giaQueued = Number(giaRatio.refresh_queued_or_running ?? 0) || 0;
  const giaReadinessState = giaToday ? (giaFailed > 0 ? "warn" : "ok") : "unknown";

  return (
    <main className="min-h-screen bg-[#f7f4ee] px-6 py-10 text-[#1e1b16]">
      <div className="mx-auto w-full max-w-5xl space-y-6">
        <AdminNav title={`Welcome, ${name}`} subtitle="Use the shortcuts below to manage user ops, prompts, and app content." />

        <section className="grid gap-4 lg:grid-cols-3">
          {[
            {
              title: "User Ops",
              desc: "Total users, new today, and new this week.",
              rows: [
                { label: "Total", value: stats?.users?.total ?? "—" },
                { label: "Today", value: stats?.users?.today ?? "—" },
                { label: "This week", value: stats?.users?.week ?? "—" },
              ],
            },
              {
                title: "Assessments",
                desc: "Completed assessments across the programme.",
                rows: [
                  { label: "Total", value: stats?.assessments?.total ?? "—" },
                  { label: "Today", value: stats?.assessments?.today ?? "—" },
                  { label: "This week", value: stats?.assessments?.week ?? "—" },
                ],
              },
              {
                title: "User app activity",
                desc: "Current app actions and today's Gia readiness.",
                rows: [
                  { label: "Active users", value: appKpis.active_app_users ?? "—", href: "/admin/monitoring?tab=app" },
                  { label: "Check-ins", value: appKpis.daily_check_in_users ?? "—", href: "/admin/monitoring?tab=app" },
                  { label: "Gia ready today", value: giaTodayRatio, href: "/admin/monitoring/coaching-today" },
                ],
              },
          ].map((item) => (
            <div key={item.title} className="rounded-2xl border border-[#efe7db] bg-white p-5">
              <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">{item.title}</p>
              <p className="mt-2 text-sm text-[#6b6257]">{item.desc}</p>
              <div className="mt-4 space-y-3">
                {item.rows.map((row) => (
                  <div key={row.label} className="flex items-center justify-between rounded-xl bg-[#f7f4ee] px-3 py-2">
                    <span className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">{row.label}</span>
                    {"href" in row && row.href ? (
                      <Link href={row.href} className="text-lg font-semibold text-[#1d6a4f] underline-offset-2 hover:underline">
                        {row.value}
                      </Link>
                    ) : (
                      <span className="text-lg font-semibold">{row.value}</span>
                    )}
                  </div>
                ))}
              </div>
            </div>
          ))}
        </section>

        <section className="grid gap-4 lg:grid-cols-2 xl:grid-cols-6">
          <div className="rounded-2xl border border-[#efe7db] bg-white p-5 xl:col-span-2">
            <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Combined costs</p>
            <p className="mt-2 text-sm text-[#6b6257]">Estimated total across TTS, LLM, and WhatsApp (last 7 days).</p>
            <div className="mt-4 rounded-xl bg-[#f7f4ee] px-4 py-3">
              <span className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Total</span>
              <div className="mt-2 text-3xl font-semibold">
                {usage?.combined_cost_gbp != null ? `£${usage.combined_cost_gbp}` : "—"}
              </div>
            </div>
          </div>
          <div className="rounded-2xl border border-[#efe7db] bg-white p-5 xl:col-span-2">
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Assessment monitoring</p>
                <p className="mt-2 text-sm text-[#6b6257]">
                  Live quality signals from funnel, LLM, queue, and delivery.
                </p>
              </div>
              <Link
                href="/admin/monitoring"
                className="rounded-full border border-[var(--accent)] px-3 py-1 text-xs uppercase tracking-[0.2em] text-[var(--accent)]"
              >
                Open
              </Link>
            </div>
            <div className="mt-4 grid gap-2 sm:grid-cols-2">
              <div className="rounded-xl bg-[#f7f4ee] px-3 py-2">
                <span className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Completion rate</span>
                <div className="mt-1 text-xl font-semibold">
                  {health?.funnel?.completion_rate_pct != null ? `${health.funnel.completion_rate_pct}%` : "—"}
                </div>
              </div>
              <div className="rounded-xl bg-[#f7f4ee] px-3 py-2">
                <span className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">LLM p95</span>
                <div className="mt-1 text-xl font-semibold">
                  {health?.llm?.duration_ms_p95 != null ? `${Math.round(health.llm.duration_ms_p95)} ms` : "—"}
                </div>
              </div>
              <div className="rounded-xl bg-[#f7f4ee] px-3 py-2">
                <span className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">OKR fallback</span>
                <div className="mt-1 text-xl font-semibold">
                  {health?.llm?.okr_generation?.fallback_rate_pct != null
                    ? `${health.llm.okr_generation.fallback_rate_pct}%`
                    : "—"}
                </div>
              </div>
              <div className="rounded-xl bg-[#f7f4ee] px-3 py-2">
                <span className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Active alerts</span>
                <div className="mt-1 text-xl font-semibold">{health?.alerts?.length ?? "—"}</div>
              </div>
            </div>
          </div>
            <div className="rounded-2xl border border-[#efe7db] bg-white p-5 xl:col-span-2">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Gia readiness monitoring</p>
                  <p className="mt-2 text-sm text-[#6b6257]">
                    Today&apos;s tracker records, refresh jobs, and Gia message readiness.
                  </p>
                </div>
                <Link
                  href="/admin/monitoring/coaching-today"
                  className="rounded-full border border-[#1d6a4f] px-3 py-1 text-xs uppercase tracking-[0.2em] text-[#1d6a4f]"
                >
                  Open
                </Link>
              </div>
              <div className="mt-4 grid gap-2 sm:grid-cols-2">
                <div className="rounded-xl bg-[#f7f4ee] px-3 py-2">
                  <span className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Daily records</span>
                  <div className="mt-1 text-xl font-semibold">{giaRatio.tracked_today ?? "—"}</div>
                </div>
                <div className="rounded-xl bg-[#f7f4ee] px-3 py-2">
                  <span className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Queued/running</span>
                  <div className="mt-1 text-xl font-semibold">{giaQueued}</div>
                </div>
                <div className="rounded-xl bg-[#f7f4ee] px-3 py-2">
                  <span className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Gia ready</span>
                  <div className="mt-1 text-xl font-semibold">{giaRatio.gia_ready ?? "—"}</div>
                </div>
                <div className={stateTileClass(giaReadinessState)}>
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Failed</span>
                    <span className={`rounded-full border px-2 py-0.5 text-[10px] uppercase tracking-[0.2em] ${stateChipClass(giaReadinessState)}`}>
                      {String(giaReadinessState || "unknown").toUpperCase()}
                    </span>
                  </div>
                  <div className="mt-1 text-xl font-semibold">{giaFailed}</div>
                </div>
                <div className="rounded-xl bg-[#f7f4ee] px-3 py-2">
                  <span className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Ratio</span>
                  <div className="mt-1 text-xl font-semibold">{giaTodayRatio}</div>
                </div>
                <div className="rounded-xl bg-[#f7f4ee] px-3 py-2">
                  <span className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Job states</span>
                  <div className="mt-1 text-sm font-semibold">
                    {Object.entries(giaToday?.job_status_counts || {}).length
                      ? Object.entries(giaToday?.job_status_counts || {})
                          .map(([key, value]) => `${key} ${value}`)
                          .join(" · ")
                      : "—"}
                  </div>
                </div>
              </div>
            </div>
            <div className="rounded-2xl border border-[#efe7db] bg-white p-5 xl:col-span-3">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">User app monitoring</p>
                  <p className="mt-2 text-sm text-[#6b6257]">
                    Daily check-ins, plan views, education, Gia messages, biometrics, and urine tests.
                  </p>
                </div>
              <Link
                href="/admin/monitoring?tab=app"
                className="rounded-full border border-[#1d4ed8] px-3 py-1 text-xs uppercase tracking-[0.2em] text-[#1d4ed8]"
              >
                Open
              </Link>
            </div>
            <div className="mt-4 grid gap-2 sm:grid-cols-2">
                <div className="rounded-xl bg-[#f7f4ee] px-3 py-2">
                  <span className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Active users</span>
                  <div className="mt-1 text-xl font-semibold">{appKpis.active_app_users ?? "—"}</div>
                </div>
                <div className="rounded-xl bg-[#f7f4ee] px-3 py-2">
                  <span className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Daily check-ins</span>
                  <div className="mt-1 text-xl font-semibold">{appKpis.daily_check_in_users ?? "—"}</div>
                </div>
                <div className="rounded-xl bg-[#f7f4ee] px-3 py-2">
                  <span className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Plan views</span>
                  <div className="mt-1 text-xl font-semibold">{appKpis.daily_plan_views ?? "—"}</div>
                </div>
                <div className="rounded-xl bg-[#f7f4ee] px-3 py-2">
                  <span className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Education views</span>
                  <div className="mt-1 text-xl font-semibold">{appKpis.education_views ?? "—"}</div>
                </div>
                <div className="rounded-xl bg-[#f7f4ee] px-3 py-2">
                  <span className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Gia messages</span>
                  <div className="mt-1 text-xl font-semibold">{appKpis.gia_message_views ?? "—"}</div>
                </div>
                <div className="rounded-xl bg-[#f7f4ee] px-3 py-2">
                  <span className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Urine captures</span>
                  <div className="mt-1 text-xl font-semibold">{appKpis.urine_captures ?? "—"}</div>
                </div>
              </div>
            </div>
          <div className="rounded-2xl border border-[#efe7db] bg-white p-5 xl:col-span-3">
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Infrastructure monitoring</p>
                <p className="mt-2 text-sm text-[#6b6257]">
                  Render API/worker/DB CPU, memory, connections, and disk health.
                </p>
              </div>
              <Link
                href="/admin/monitoring?tab=infra"
                className="rounded-full border border-[#111827] px-3 py-1 text-xs uppercase tracking-[0.2em] text-[#111827]"
              >
                Open
              </Link>
            </div>
            <div className="mt-4 grid gap-2 sm:grid-cols-2">
              <div className="rounded-xl bg-[#f7f4ee] px-3 py-2">
                <span className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">API CPU p95</span>
                <div className="mt-1 text-xl font-semibold">
                  {health?.infra?.api?.cpu?.p95 != null ? `${health.infra.api.cpu.p95} ${health?.infra?.api?.cpu?.unit || ""}`.trim() : "—"}
                </div>
              </div>
              <div className="rounded-xl bg-[#f7f4ee] px-3 py-2">
                <span className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Worker CPU p95</span>
                <div className="mt-1 text-xl font-semibold">
                  {health?.infra?.workers?.cpu?.p95 != null
                    ? `${health.infra.workers.cpu.p95} ${health?.infra?.workers?.cpu?.unit || ""}`.trim()
                    : "—"}
                </div>
              </div>
              <div className="rounded-xl bg-[#f7f4ee] px-3 py-2">
                <span className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">DB connections p95</span>
                <div className="mt-1 text-xl font-semibold">
                  {health?.infra?.database?.active_connections?.p95 != null ? `${health.infra.database.active_connections.p95}` : "—"}
                </div>
              </div>
              <div className="rounded-xl bg-[#f7f4ee] px-3 py-2">
                <span className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">DB disk p95</span>
                <div className="mt-1 text-xl font-semibold">
                  {health?.infra?.database?.disk_usage_pct?.p95 != null ? `${health.infra.database.disk_usage_pct.p95}%` : "—"}
                </div>
              </div>
            </div>
          </div>
        </section>
      </div>
    </main>
  );
}
