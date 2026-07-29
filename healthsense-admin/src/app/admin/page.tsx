import Link from "next/link";
import AdminNav from "@/components/AdminNav";
import {
  getAdminAppEngagement,
  getAdminAssessmentHealth,
  getAdminMarketingFunnel,
  getAdminProfile,
  getAdminStats,
  getAdminUsageSummary,
} from "@/lib/api";

export const dynamic = "force-dynamic";

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
  let acquisition: Awaited<ReturnType<typeof getAdminMarketingFunnel>> | null = null;
  try {
    acquisition = await getAdminMarketingFunnel({ days: 7 });
  } catch {
    acquisition = null;
  }
  const appKpis = appEngagement?.top_kpis || {};
  const todayKey = String(appEngagement?.as_of_uk || "").slice(0, 10);
  const todayApp = (appEngagement?.detail?.daily || []).find((row) => row.day === todayKey);
  const checkInsToday = todayApp?.check_in_completions ?? 0;
  const checkInsSevenDays = appKpis.daily_check_in_completions ?? 0;
  const lessonsToday = todayApp?.lesson_completions ?? 0;
  const lessonsSevenDays = appKpis.education_lesson_completions ?? 0;

  return (
    <main className="min-h-screen bg-[#f7f4ee] px-6 py-10 text-[#1e1b16]">
      <div className="mx-auto w-full max-w-5xl space-y-6">
        <AdminNav title={`Welcome, ${name}`} subtitle="Monitor CoachSense app acquisition, activation, usage, operations, and content." />

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
                title: "App acquisition",
                desc: "Website-to-app activity during the last 7 days.",
                rows: [
                  {
                    label: "Website views",
                    value: acquisition?.acquisition?.coachsense_ai_homepage_views ?? "—",
                    href: "/admin/reporting?tab=marketing",
                  },
                  {
                    label: "Download clicks",
                    value: acquisition?.acquisition?.download_button_clicks ?? "—",
                    href: "/admin/reporting?tab=marketing",
                  },
                  {
                    label: "App activations",
                    value: acquisition?.acquisition?.first_app_activations ?? "—",
                    href: "/admin/reporting?tab=marketing",
                  },
                ],
              },
              {
                title: "User app activity",
                desc: "Completed user activity today and over the last 7 days.",
                rows: [
                  { label: "Active users", value: appKpis.active_app_users ?? "—", href: "/admin/monitoring?tab=app" },
                  { label: "Check-ins today", value: checkInsToday, href: "/admin/monitoring?tab=app" },
                  { label: "Lessons today", value: lessonsToday, href: "/admin/monitoring?tab=app" },
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
                <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">App acquisition</p>
                <p className="mt-2 text-sm text-[#6b6257]">
                  Website interest, store intent, and first app use in the last 7 days.
                </p>
              </div>
              <Link
                href="/admin/reporting?tab=marketing"
                className="rounded-full border border-[var(--accent)] px-3 py-1 text-xs uppercase tracking-[0.2em] text-[var(--accent)]"
              >
                Open
              </Link>
            </div>
            <div className="mt-4 grid gap-2 sm:grid-cols-2">
              <div className="rounded-xl bg-[#f7f4ee] px-3 py-2">
                <span className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Website views</span>
                <div className="mt-1 text-xl font-semibold">
                  {acquisition?.acquisition?.coachsense_ai_homepage_views ?? "—"}
                </div>
              </div>
              <div className="rounded-xl bg-[#f7f4ee] px-3 py-2">
                <span className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Download clicks</span>
                <div className="mt-1 text-xl font-semibold">
                  {acquisition?.acquisition?.download_button_clicks ?? "—"}
                </div>
              </div>
              <div className="rounded-xl bg-[#f7f4ee] px-3 py-2">
                <span className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">First activations</span>
                <div className="mt-1 text-xl font-semibold">
                  {acquisition?.acquisition?.first_app_activations ?? "—"}
                </div>
              </div>
              <div className="rounded-xl bg-[#f7f4ee] px-3 py-2">
                <span className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Store downloads</span>
                <div className="mt-1 text-xl font-semibold">
                  {acquisition?.acquisition?.confirmed_store_downloads ?? "—"}
                </div>
                <div className="mt-1 text-xs text-[#8a8176]">
                  {acquisition?.acquisition?.confirmed_store_downloads_status === "connected"
                    ? "Apple and Google reporting"
                    : "Awaiting store connections"}
                </div>
              </div>
            </div>
          </div>
            <div className="rounded-2xl border border-[#efe7db] bg-white p-5 xl:col-span-2">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Completed activity</p>
                  <p className="mt-2 text-sm text-[#6b6257]">Distinct completed check-ins and lessons.</p>
                </div>
                <Link
                  href="/admin/monitoring?tab=app"
                  className="rounded-full border border-[#1d6a4f] px-3 py-1 text-xs uppercase tracking-[0.2em] text-[#1d6a4f]"
                >
                  Open
                </Link>
              </div>
              <div className="mt-4 grid gap-2 sm:grid-cols-2">
                <div className="rounded-xl bg-[#f7f4ee] px-3 py-2">
                  <span className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Check-ins today</span>
                  <div className="mt-1 text-xl font-semibold">{checkInsToday}</div>
                </div>
                <div className="rounded-xl bg-[#f7f4ee] px-3 py-2">
                  <span className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Check-ins · 7 days</span>
                  <div className="mt-1 text-xl font-semibold">{checkInsSevenDays}</div>
                </div>
                <div className="rounded-xl bg-[#f7f4ee] px-3 py-2">
                  <span className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Lessons today</span>
                  <div className="mt-1 text-xl font-semibold">{lessonsToday}</div>
                </div>
                <div className="rounded-xl bg-[#f7f4ee] px-3 py-2">
                  <span className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Lessons · 7 days</span>
                  <div className="mt-1 text-xl font-semibold">{lessonsSevenDays}</div>
                </div>
              </div>
            </div>
            <div className="rounded-2xl border border-[#efe7db] bg-white p-5 xl:col-span-3">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">User app monitoring</p>
                  <p className="mt-2 text-sm text-[#6b6257]">
                    Check-ins, lessons, plans, education, and biometrics.
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
                  <span className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Check-ins · 7 days</span>
                  <div className="mt-1 text-xl font-semibold">{checkInsSevenDays}</div>
                </div>
                <div className="rounded-xl bg-[#f7f4ee] px-3 py-2">
                  <span className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Plan views</span>
                  <div className="mt-1 text-xl font-semibold">{appKpis.daily_plan_views ?? "—"}</div>
                </div>
                <div className="rounded-xl bg-[#f7f4ee] px-3 py-2">
                  <span className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Lessons · 7 days</span>
                  <div className="mt-1 text-xl font-semibold">{lessonsSevenDays}</div>
                </div>
                <div className="rounded-xl bg-[#f7f4ee] px-3 py-2">
                  <span className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Education views</span>
                  <div className="mt-1 text-xl font-semibold">{appKpis.education_views ?? "—"}</div>
                </div>
                <div className="rounded-xl bg-[#f7f4ee] px-3 py-2">
                  <span className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Biometrics opens</span>
                  <div className="mt-1 text-xl font-semibold">{appKpis.biometrics_opens ?? "—"}</div>
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
