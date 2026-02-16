import Link from "next/link";
import AdminNav from "@/components/AdminNav";
import { getAdminAppEngagement, getAdminAssessmentHealth, getAdminProfile, getAdminStats, getAdminUsageSummary } from "@/lib/api";

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
  const appKpis = appEngagement?.top_kpis || {};

  return (
    <main className="min-h-screen bg-[#f7f4ee] px-6 py-10 text-[#1e1b16]">
      <div className="mx-auto w-full max-w-5xl space-y-6">
        <AdminNav title={`Welcome, ${name}`} subtitle="Use the shortcuts below to manage users, prompts, and library content." />

        <section className="grid gap-4 lg:grid-cols-3">
          {[
            {
              title: "Users",
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
              title: "Coaching interactions",
              desc: "WhatsApp + in-app coaching touchpoints.",
              rows: [
                { label: "Total", value: stats?.interactions?.total ?? "—" },
                { label: "Today", value: stats?.interactions?.today ?? "—" },
                { label: "This week", value: stats?.interactions?.week ?? "—" },
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
                    <span className="text-lg font-semibold">{row.value}</span>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </section>

        <section className="grid gap-4 lg:grid-cols-2 xl:grid-cols-4">
          <div className="rounded-2xl border border-[#efe7db] bg-white p-5">
            <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Combined costs</p>
            <p className="mt-2 text-sm text-[#6b6257]">Estimated total across TTS, LLM, and WhatsApp (last 7 days).</p>
            <div className="mt-4 rounded-xl bg-[#f7f4ee] px-4 py-3">
              <span className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Total</span>
              <div className="mt-2 text-3xl font-semibold">
                {usage?.combined_cost_gbp != null ? `£${usage.combined_cost_gbp}` : "—"}
              </div>
            </div>
          </div>
          <div className="rounded-2xl border border-[#efe7db] bg-white p-5">
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
          <div className="rounded-2xl border border-[#efe7db] bg-white p-5">
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Coaching monitoring</p>
                <p className="mt-2 text-sm text-[#6b6257]">
                  Weekly flow completion, reply behavior, and coaching reach.
                </p>
              </div>
              <Link
                href="/admin/monitoring?tab=coaching"
                className="rounded-full border border-[#1d6a4f] px-3 py-1 text-xs uppercase tracking-[0.2em] text-[#1d6a4f]"
              >
                Open
              </Link>
            </div>
            <div className="mt-4 grid gap-2 sm:grid-cols-2">
              <div className="rounded-xl bg-[#f7f4ee] px-3 py-2">
                <span className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Users reached</span>
                <div className="mt-1 text-xl font-semibold">{health?.coaching?.users_reached ?? "—"}</div>
              </div>
              <div className="rounded-xl bg-[#f7f4ee] px-3 py-2">
                <span className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Week completion</span>
                <div className="mt-1 text-xl font-semibold">
                  {health?.coaching?.day_funnel?.week_completion_rate_pct != null
                    ? `${health.coaching.day_funnel.week_completion_rate_pct}%`
                    : "—"}
                </div>
              </div>
              <div className="rounded-xl bg-[#f7f4ee] px-3 py-2">
                <span className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Sunday reply</span>
                <div className="mt-1 text-xl font-semibold">
                  {health?.coaching?.day_funnel?.sunday_reply_rate_pct != null
                    ? `${health.coaching.day_funnel.sunday_reply_rate_pct}%`
                    : "—"}
                </div>
              </div>
              <div className="rounded-xl bg-[#f7f4ee] px-3 py-2">
                <span className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Outside 24h</span>
                <div className="mt-1 text-xl font-semibold">
                  {health?.coaching?.engagement_window?.outside_24h_rate_pct != null
                    ? `${health.coaching.engagement_window.outside_24h_rate_pct}%`
                    : "—"}
                </div>
              </div>
              <div className="rounded-xl bg-[#f7f4ee] px-3 py-2">
                <span className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Streak p50</span>
                <div className="mt-1 text-xl font-semibold">
                  {health?.coaching?.engagement_window?.current_streak_days_p50 != null
                    ? `${health.coaching.engagement_window.current_streak_days_p50} days`
                    : "—"}
                </div>
              </div>
              <div className="rounded-xl bg-[#f7f4ee] px-3 py-2">
                <span className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Reply p95</span>
                <div className="mt-1 text-xl font-semibold">
                  {health?.coaching?.response_time_minutes?.p95 != null
                    ? `${Math.round(health.coaching.response_time_minutes.p95)} min`
                    : "—"}
                </div>
              </div>
            </div>
          </div>
          <div className="rounded-2xl border border-[#efe7db] bg-white p-5">
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">App monitoring</p>
                <p className="mt-2 text-sm text-[#6b6257]">
                  Home usage, assessment return behavior, and podcast engagement.
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
                <span className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Home views</span>
                <div className="mt-1 text-xl font-semibold">{appKpis.home_page_views ?? "—"}</div>
              </div>
              <div className="rounded-xl bg-[#f7f4ee] px-3 py-2">
                <span className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Results view rate</span>
                <div className="mt-1 text-xl font-semibold">
                  {appKpis.post_assessment_results_view_rate_pct != null
                    ? `${appKpis.post_assessment_results_view_rate_pct}%`
                    : "—"}
                </div>
              </div>
              <div className="rounded-xl bg-[#f7f4ee] px-3 py-2">
                <span className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Podcast listener rate</span>
                <div className="mt-1 text-xl font-semibold">
                  {appKpis.podcast_listener_rate_pct != null
                    ? `${appKpis.podcast_listener_rate_pct}%`
                    : "—"}
                </div>
              </div>
            </div>
          </div>
        </section>
      </div>
    </main>
  );
}
