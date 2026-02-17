import AdminNav from "@/components/AdminNav";
import { getAdminAppEngagement, getAdminAssessmentHealth } from "@/lib/api";

export const dynamic = "force-dynamic";

type MonitoringSearchParams = {
  days?: string | string[];
  stale_minutes?: string | string[];
  tab?: string | string[];
};

function firstParam(value: string | string[] | undefined): string | undefined {
  if (Array.isArray(value)) return value[0];
  return value;
}

function clampInt(value: string | string[] | undefined, fallback: number, min: number, max: number): number {
  const raw = firstParam(value);
  if (raw == null) return fallback;
  const parsed = Number(raw);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.max(min, Math.min(max, Math.trunc(parsed)));
}

function stateBadgeClass(state?: string | null): string {
  const key = (state || "").toLowerCase();
  if (key === "critical") return "border-[#c43d3d] bg-[#fdeaea] text-[#8c1d1d]";
  if (key === "warn") return "border-[#cc9a2f] bg-[#fff6e6] text-[#825b0b]";
  if (key === "ok") return "border-[#2f8b55] bg-[#eaf7ef] text-[#14532d]";
  return "border-[#d8d1c4] bg-[#f7f4ee] text-[#6b6257]";
}

function formatNum(value: number | null | undefined, digits = 2): string {
  if (value == null || Number.isNaN(value)) return "—";
  return Number(value).toFixed(digits);
}

function barWidth(percentOfStart: number | null | undefined): string {
  if (percentOfStart == null || Number.isNaN(percentOfStart)) return "0%";
  const bounded = Math.max(0, Math.min(100, percentOfStart));
  if (bounded === 0) return "0%";
  return `${Math.max(6, bounded)}%`;
}

export default async function MonitoringPage({ searchParams }: { searchParams?: MonitoringSearchParams }) {
  const resolvedSearchParams =
    searchParams && typeof (searchParams as unknown as { then?: unknown }).then === "function"
      ? await (searchParams as unknown as Promise<MonitoringSearchParams>)
      : searchParams;
  const days = clampInt(resolvedSearchParams?.days, 7, 1, 30);
  const staleMinutes = clampInt(resolvedSearchParams?.stale_minutes, 30, 5, 240);
  const tabRaw = (firstParam(resolvedSearchParams?.tab) || "assessment").toLowerCase();
  const activeTab: "assessment" | "coaching" | "app" =
    tabRaw === "coaching" ? "coaching" : tabRaw === "app" ? "app" : "assessment";
  const assessmentTabHref = `/admin/monitoring?days=${days}&stale_minutes=${staleMinutes}&tab=assessment`;
  const coachingTabHref = `/admin/monitoring?days=${days}&stale_minutes=${staleMinutes}&tab=coaching`;
  const appTabHref = `/admin/monitoring?days=${days}&stale_minutes=${staleMinutes}&tab=app`;

  let health: Awaited<ReturnType<typeof getAdminAssessmentHealth>> | null = null;
  let appEngagement: Awaited<ReturnType<typeof getAdminAppEngagement>> | null = null;
  let loadError: string | null = null;
  const [healthRes, appRes] = await Promise.allSettled([
    getAdminAssessmentHealth({ days, stale_minutes: staleMinutes }),
    getAdminAppEngagement({ days }),
  ]);
  if (healthRes.status === "fulfilled") {
    health = healthRes.value;
  } else if (activeTab !== "app") {
    loadError = healthRes.reason instanceof Error ? healthRes.reason.message : "Failed to load monitoring data.";
  }
  if (appRes.status === "fulfilled") {
    appEngagement = appRes.value;
  } else if (activeTab === "app" && !loadError) {
    loadError = appRes.reason instanceof Error ? appRes.reason.message : "Failed to load monitoring data.";
  }

  const activeWindow =
    activeTab === "app"
      ? appEngagement?.window
      : health?.window;
  const activeAsOf = activeTab === "app" ? appEngagement?.as_of_uk : health?.as_of_utc;

  const alerts = health?.alerts || [];
  const funnelSteps = health?.funnel?.steps || [];
  const coachingFunnelSteps = health?.coaching?.day_funnel?.steps || [];
  const coachingWeekRows = health?.coaching?.week_funnel?.weeks || [];
  const coachingDayStats = (health?.coaching?.day_stats || []).filter(
    (row) => String(row?.day || "").toLowerCase() !== "kickoff",
  );
  const llmAssessment = health?.llm?.assessment || {
    prompts: health?.llm?.assessor_prompts ?? 0,
    duration_ms_p50: health?.llm?.duration_ms_p50 ?? null,
    duration_ms_p95: health?.llm?.duration_ms_p95 ?? null,
    duration_ms_state: health?.llm?.duration_ms_state,
    slow_over_warn: health?.llm?.slow_over_warn ?? 0,
    slow_over_critical: health?.llm?.slow_over_critical ?? 0,
  };
  const llmCoaching = health?.llm?.coaching || {
    prompts: 0,
    duration_ms_p50: null,
    duration_ms_p95: null,
    duration_ms_state: "unknown",
    slow_over_warn: 0,
    slow_over_critical: 0,
  };
  const llmCombined = health?.llm?.combined || {
    prompts: health?.llm?.assessor_prompts ?? 0,
    duration_ms_p50: health?.llm?.duration_ms_p50 ?? null,
    duration_ms_p95: health?.llm?.duration_ms_p95 ?? null,
    duration_ms_state: health?.llm?.duration_ms_state,
    slow_over_warn: health?.llm?.slow_over_warn ?? 0,
    slow_over_critical: health?.llm?.slow_over_critical ?? 0,
  };
  const llmPanels = [
    { title: "Assessment", data: llmAssessment, desc: "Assessment LLM prompts and latency distribution." },
    { title: "Coaching", data: llmCoaching, desc: "Coaching LLM prompts and latency distribution." },
    { title: "Combined", data: llmCombined, desc: "Assessment + coaching combined latency profile." },
  ];
  const metrics = [
    {
      title: "Completion rate",
      value: health?.funnel?.completion_rate_pct != null ? `${formatNum(health?.funnel?.completion_rate_pct)}%` : "—",
      state: health?.funnel?.completion_rate_state,
      subtitle: `${health?.funnel?.completed ?? "—"} completed / ${health?.funnel?.started ?? "—"} started`,
      description: "Share of started assessments that reached completion in the selected window.",
    },
    {
      title: "Median completion",
      value:
        health?.funnel?.median_completion_minutes != null
          ? `${formatNum(health?.funnel?.median_completion_minutes)} min`
          : "—",
      state: health?.funnel?.median_completion_state,
      subtitle: `P95 ${health?.funnel?.p95_completion_minutes != null ? `${formatNum(health?.funnel?.p95_completion_minutes)} min` : "—"}`,
      description: "Typical end-to-end completion time for finished assessments.",
    },
    {
      title: "LLM p95 latency",
      value: llmCombined.duration_ms_p95 != null ? `${Math.round(llmCombined.duration_ms_p95)} ms` : "—",
      state: llmCombined.duration_ms_state,
      subtitle: `${llmCombined.prompts ?? 0} combined prompts`,
      description: "95th percentile response time across assessment + coaching prompts.",
    },
    {
      title: "OKR fallback rate",
      value:
        health?.llm?.okr_generation?.fallback_rate_pct != null
          ? `${formatNum(health.llm.okr_generation.fallback_rate_pct)}%`
          : "—",
      state: health?.llm?.okr_generation?.fallback_rate_state,
      subtitle: `${health?.llm?.okr_generation?.fallback ?? 0} fallback / ${health?.llm?.okr_generation?.calls ?? 0} calls`,
      description: "Percentage of OKR generations that used deterministic fallback instead of LLM output.",
    },
    {
      title: "Queue backlog",
      value: health?.queue?.backlog != null ? `${health.queue.backlog}` : "—",
      state: health?.queue?.backlog_state,
      subtitle: `pending ${health?.queue?.pending ?? 0}, retry ${health?.queue?.retry ?? 0}`,
      description: "Jobs waiting to be processed (pending + retry).",
    },
    {
      title: "Twilio failure rate",
      value:
        health?.messaging?.twilio_failure_rate_pct != null
          ? `${formatNum(health.messaging.twilio_failure_rate_pct)}%`
          : "—",
      state: health?.messaging?.twilio_failure_state,
      subtitle: `${health?.messaging?.twilio_failures ?? 0} failed callbacks`,
      description: "Share of Twilio status callbacks marked failed/undelivered or with error codes.",
    },
  ];
  const coachingMetrics = [
    {
      title: "Coaching users reached",
      value: health?.coaching?.users_reached != null ? `${health.coaching.users_reached}` : "—",
      state: "unknown",
      subtitle: `${health?.coaching?.touchpoints_sent ?? 0} coaching touchpoints sent`,
      description: "Unique users who received at least one coaching touchpoint in this window.",
    },
    {
      title: "Weekly flow completion",
      value:
        health?.coaching?.day_funnel?.week_completion_rate_pct != null
          ? `${formatNum(health.coaching.day_funnel.week_completion_rate_pct)}%`
          : "—",
      state: health?.coaching?.day_funnel?.week_completion_state,
      subtitle: `${health?.coaching?.day_funnel?.completed_sunday ?? 0} reached Sunday / ${health?.coaching?.day_funnel?.started ?? 0} Monday starts`,
      description: "Monday-started coaching users who reached Sunday in the same flow.",
    },
    {
      title: "Sunday reply rate",
      value:
        health?.coaching?.day_funnel?.sunday_reply_rate_pct != null
          ? `${formatNum(health.coaching.day_funnel.sunday_reply_rate_pct)}%`
          : "—",
      state: health?.coaching?.day_funnel?.sunday_reply_state,
      subtitle: `${health?.coaching?.day_funnel?.sunday_replied ?? 0} replied / ${health?.coaching?.day_funnel?.completed_sunday ?? 0} Sunday prompts`,
      description: "Share of Sunday review prompts that received a user reply within 24 hours.",
    },
    {
      title: "Coach reply latency p95",
      value:
        health?.coaching?.response_time_minutes?.p95 != null
          ? `${Math.round(health.coaching.response_time_minutes.p95)} min`
          : "—",
      state: health?.coaching?.response_time_minutes?.state,
      subtitle: `p50 ${health?.coaching?.response_time_minutes?.p50 != null ? `${Math.round(health.coaching.response_time_minutes.p50)} min` : "—"} (${health?.coaching?.response_time_minutes?.sample_size ?? 0} samples)`,
      description: "How quickly users typically reply after coaching touchpoints (windowed to 24h).",
    },
    {
      title: "Outside 24h window",
      value:
        health?.coaching?.engagement_window?.outside_24h_rate_pct != null
          ? `${formatNum(health.coaching.engagement_window.outside_24h_rate_pct)}%`
          : "—",
      state: health?.coaching?.engagement_window?.outside_24h_state,
      subtitle: `${health?.coaching?.engagement_window?.outside_24h ?? 0} outside / ${health?.coaching?.engagement_window?.users_tracked ?? 0} tracked`,
      description: "Users whose latest inbound message is older than 24 hours (or has no inbound history).",
    },
    {
      title: "Current streak p50",
      value:
        health?.coaching?.engagement_window?.current_streak_days_p50 != null
          ? `${formatNum(health.coaching.engagement_window.current_streak_days_p50)} days`
          : "—",
      state: "unknown",
      subtitle: `p95 ${health?.coaching?.engagement_window?.current_streak_days_p95 != null ? `${formatNum(health.coaching.engagement_window.current_streak_days_p95)} days` : "—"} | max ${health?.coaching?.engagement_window?.current_streak_days_max ?? "—"} days`,
      description: "Median consecutive-day inbound streak (UK day), anchored to today.",
    },
  ];
  const appKpis = appEngagement?.top_kpis || {};
  const appDetail = appEngagement?.detail || {};
  const appOnboarding = appDetail.onboarding || {};
  const appDailyRows = appDetail.daily || [];
  const appMetrics = [
    {
      title: "Active app users",
      value: appKpis.active_app_users ?? 0,
      subtitle: `${appKpis.home_page_views ?? 0} home views`,
      description: "Unique users with at least one app event in this window.",
    },
    {
      title: "Avg home views / user",
      value: appKpis.avg_home_views_per_active_user ?? 0,
      subtitle: `${appDetail.home?.users ?? 0} users opened home`,
      description: "Average home page opens per active app user.",
    },
    {
      title: "Post-assessment results view",
      value: appKpis.post_assessment_results_view_rate_pct != null ? `${formatNum(appKpis.post_assessment_results_view_rate_pct)}%` : "—",
      subtitle: `${appKpis.post_assessment_users_viewed_results ?? 0} / ${appKpis.post_assessment_users_completed ?? 0} users`,
      description: "Users who returned to view results after completing assessment.",
    },
    {
      title: "Podcast listener rate",
      value: appKpis.podcast_listener_rate_pct != null ? `${formatNum(appKpis.podcast_listener_rate_pct)}%` : "—",
      subtitle: `${appKpis.podcast_listeners ?? 0} listeners`,
      description: "Active app users who played at least one podcast.",
    },
    {
      title: "Intro completion rate",
      value:
        appKpis.onboarding_intro_completion_rate_pct != null
          ? `${formatNum(appKpis.onboarding_intro_completion_rate_pct)}%`
          : "—",
      subtitle: `${appOnboarding.intro_completed_after_first_login_users ?? 0} / ${appOnboarding.first_login_cohort_users ?? 0} first-logins`,
      description: "First-login users who completed intro via listen or read.",
    },
    {
      title: "Coaching auto-enabled",
      value:
        appKpis.onboarding_coaching_auto_enabled_rate_pct != null
          ? `${formatNum(appKpis.onboarding_coaching_auto_enabled_rate_pct)}%`
          : "—",
      subtitle: `${appOnboarding.coaching_auto_enabled_after_first_login_users ?? 0} users`,
      description: "First-login cohort users that reached coaching auto-enable.",
    },
  ];

  return (
    <main className="min-h-screen bg-[#f7f4ee] px-6 py-10 text-[#1e1b16]">
      <div className="mx-auto w-full max-w-6xl space-y-6">
        <AdminNav
          title="Operations monitoring"
          subtitle="Assessment + coaching flow health across funnel, LLM quality, queue, and messaging delivery."
        />

        <section className="rounded-3xl border border-[#e7e1d6] bg-white p-6">
          <div className="flex flex-wrap items-end justify-between gap-4">
            <div>
              <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Window</p>
              <p className="mt-2 text-sm text-[#6b6257]">
                {activeWindow?.start_utc || "—"} → {activeWindow?.end_utc || "—"}
              </p>
              <p className="mt-1 text-sm text-[#6b6257]">As of: {activeAsOf || "—"}</p>
            </div>
            <form method="get" className="flex flex-wrap items-end gap-3">
              <input type="hidden" name="tab" value={activeTab} />
              <div>
                <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Days</label>
                <select
                  name="days"
                  defaultValue={String(days)}
                  className="mt-2 rounded-xl border border-[#efe7db] bg-white px-3 py-2 text-sm"
                >
                  <option value="1">Last 24h</option>
                  <option value="7">Last 7 days</option>
                  <option value="14">Last 14 days</option>
                  <option value="30">Last 30 days</option>
                </select>
              </div>
              <div>
                <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Stale run (min)</label>
                <input
                  type="number"
                  min={5}
                  max={240}
                  step={5}
                  name="stale_minutes"
                  defaultValue={String(staleMinutes)}
                  className="mt-2 w-32 rounded-xl border border-[#efe7db] bg-white px-3 py-2 text-sm"
                />
              </div>
              <button
                type="submit"
                className="rounded-full border border-[var(--accent)] bg-[var(--accent)] px-5 py-2 text-xs uppercase tracking-[0.2em] text-white"
              >
                Refresh
              </button>
            </form>
          </div>
          {loadError ? (
            <div className="mt-4 rounded-2xl border border-[#f3c6c6] bg-[#fff1f1] px-4 py-3 text-sm text-[#8c1d1d]">
              {loadError}
            </div>
          ) : null}
        </section>

        <section className="rounded-2xl border border-[#e7e1d6] bg-white p-4">
          <div className="flex flex-wrap gap-2">
            <a
              href={assessmentTabHref}
              className={`rounded-full border px-4 py-2 text-xs uppercase tracking-[0.2em] ${
                activeTab === "assessment"
                  ? "border-[var(--accent)] bg-[var(--accent)] text-white"
                  : "border-[#d8d1c4] bg-[#f7f4ee] text-[#6b6257]"
              }`}
            >
              Assessment
            </a>
            <a
              href={coachingTabHref}
              className={`rounded-full border px-4 py-2 text-xs uppercase tracking-[0.2em] ${
                activeTab === "coaching"
                  ? "border-[#1d6a4f] bg-[#1d6a4f] text-white"
                  : "border-[#d8d1c4] bg-[#f7f4ee] text-[#6b6257]"
              }`}
            >
              Coaching
            </a>
            <a
              href={appTabHref}
              className={`rounded-full border px-4 py-2 text-xs uppercase tracking-[0.2em] ${
                activeTab === "app"
                  ? "border-[#1d4ed8] bg-[#1d4ed8] text-white"
                  : "border-[#d8d1c4] bg-[#f7f4ee] text-[#6b6257]"
              }`}
            >
              App
            </a>
          </div>
        </section>

        {activeTab === "assessment" ? (
          <>
            <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
              {metrics.map((item) => (
                <div key={item.title} className="rounded-2xl border border-[#e7e1d6] bg-white p-5">
                  <div className="flex items-center justify-between gap-3">
                    <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">{item.title}</p>
                    <span className={`rounded-full border px-2 py-1 text-[10px] uppercase tracking-[0.2em] ${stateBadgeClass(item.state)}`}>
                      {(item.state || "unknown").toUpperCase()}
                    </span>
                  </div>
                  <div className="mt-3 text-3xl font-semibold">{item.value}</div>
                  <p className="mt-2 text-sm text-[#6b6257]">{item.subtitle}</p>
                  <p className="mt-1 text-xs text-[#8a8176]">{item.description}</p>
                </div>
              ))}
            </section>

            <section className="rounded-2xl border border-[#e7e1d6] bg-white p-5">
              <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Step-by-step funnel</p>
              <p className="mt-2 text-sm text-[#6b6257]">
                Visual conversion through each assessment stage. Width is % of started assessments.
              </p>
              {!funnelSteps.length ? (
                <p className="mt-4 text-sm text-[#8a8176]">No funnel step data in this window.</p>
              ) : (
                <div className="mt-4 space-y-3">
                  {funnelSteps.map((step, idx) => (
                    <div key={step.key || `${idx}`} className="rounded-xl border border-[#efe7db] bg-[#fdfaf4] px-3 py-3">
                      <div className="flex flex-wrap items-start justify-between gap-3">
                        <div>
                          <div className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">
                            {idx + 1}. {step.label || step.key || "step"}
                          </div>
                          <div className="mt-1 text-xs text-[#8a8176]">{step.description || "—"}</div>
                        </div>
                        <div className="text-right">
                          <div className="text-lg font-semibold">{step.count ?? 0}</div>
                          <div className="text-xs text-[#6b6257]">
                            {step.percent_of_start != null ? `${formatNum(step.percent_of_start)}% of started` : "—"}
                          </div>
                        </div>
                      </div>
                      <div className="mt-3 h-3 w-full rounded-full bg-[#ece4d8]">
                        <div
                          className="h-3 rounded-full bg-[var(--accent)]"
                          style={{ width: barWidth(step.percent_of_start) }}
                        />
                      </div>
                      <div className="mt-2 flex flex-wrap gap-4 text-xs text-[#6b6257]">
                        <span>
                          Conversion from previous:{" "}
                          {idx === 0
                            ? "—"
                            : step.conversion_pct_from_prev != null
                              ? `${formatNum(step.conversion_pct_from_prev)}%`
                              : "—"}
                        </span>
                        <span>
                          Drop-off from previous:{" "}
                          {idx === 0 ? "—" : step.dropoff_from_prev ?? 0}
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </section>
          </>
        ) : null}

        {activeTab === "coaching" ? (
          <>
            <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
              {coachingMetrics.map((item) => (
                <div key={item.title} className="rounded-2xl border border-[#e7e1d6] bg-white p-5">
                  <div className="flex items-center justify-between gap-3">
                    <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">{item.title}</p>
                    <span className={`rounded-full border px-2 py-1 text-[10px] uppercase tracking-[0.2em] ${stateBadgeClass(item.state)}`}>
                      {(item.state || "unknown").toUpperCase()}
                    </span>
                  </div>
                  <div className="mt-3 text-3xl font-semibold">{item.value}</div>
                  <p className="mt-2 text-sm text-[#6b6257]">{item.subtitle}</p>
                  <p className="mt-1 text-xs text-[#8a8176]">{item.description}</p>
                </div>
              ))}
            </section>

            <section className="rounded-2xl border border-[#e7e1d6] bg-white p-5">
              <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Coaching day flow funnel</p>
              <p className="mt-2 text-sm text-[#6b6257]">
                Monday to Sunday progression for coaching touchpoints. Width is % of Monday starters.
              </p>
              {!coachingFunnelSteps.length ? (
                <p className="mt-4 text-sm text-[#8a8176]">No coaching funnel data in this window.</p>
              ) : (
                <div className="mt-4 space-y-3">
                  {coachingFunnelSteps.map((step, idx) => (
                    <div key={step.key || `${idx}`} className="rounded-xl border border-[#efe7db] bg-[#fdfaf4] px-3 py-3">
                      <div className="flex flex-wrap items-start justify-between gap-3">
                        <div>
                          <div className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">
                            {idx + 1}. {step.label || step.key || "step"}
                          </div>
                          <div className="mt-1 text-xs text-[#8a8176]">{step.description || "—"}</div>
                        </div>
                        <div className="text-right">
                          <div className="text-lg font-semibold">{step.count ?? 0}</div>
                          <div className="text-xs text-[#6b6257]">
                            {step.percent_of_start != null ? `${formatNum(step.percent_of_start)}% of Monday starters` : "—"}
                          </div>
                        </div>
                      </div>
                      <div className="mt-3 h-3 w-full rounded-full bg-[#ece4d8]">
                        <div className="h-3 rounded-full bg-[#1d6a4f]" style={{ width: barWidth(step.percent_of_start) }} />
                      </div>
                      <div className="mt-2 flex flex-wrap gap-4 text-xs text-[#6b6257]">
                        <span>
                          Conversion from previous:{" "}
                          {idx === 0
                            ? "—"
                            : step.conversion_pct_from_prev != null
                              ? `${formatNum(step.conversion_pct_from_prev)}%`
                              : "—"}
                        </span>
                        <span>Drop-off from previous: {idx === 0 ? "—" : step.dropoff_from_prev ?? 0}</span>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </section>

            <section className="grid gap-4 xl:grid-cols-2">
              <div className="rounded-2xl border border-[#e7e1d6] bg-white p-5">
                <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Multi-week funnel</p>
                <p className="mt-1 text-xs text-[#8a8176]">
                  Per-week conversion through Monday → Sunday so you can spot week-on-week retention drift.
                </p>
                <div className="mt-3 space-y-3">
                  {!coachingWeekRows.length ? (
                    <p className="text-sm text-[#8a8176]">No week-level coaching data in this window.</p>
                  ) : (
                    coachingWeekRows.map((week) => (
                      <div key={`week-${week.week_no ?? "unknown"}`} className="rounded-xl border border-[#efe7db] bg-[#fdfaf4] px-3 py-3">
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <span className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Week {week.week_no ?? "—"}</span>
                          <span className="text-sm font-semibold">
                            {week.completion_rate_pct != null ? `${formatNum(week.completion_rate_pct)}%` : "—"} completion
                          </span>
                        </div>
                        <div className="mt-2 text-xs text-[#6b6257]">
                          Cohort {week.cohort_users ?? 0} | Sunday reached {week.completed_sunday ?? 0} | Sunday replied{" "}
                          {week.sunday_replied ?? 0}
                        </div>
                        <div className="mt-2 h-2 w-full rounded-full bg-[#ece4d8]">
                          <div
                            className="h-2 rounded-full bg-[#1d6a4f]"
                            style={{ width: barWidth(week.completion_rate_pct ?? null) }}
                          />
                        </div>
                        <div className="mt-2 text-xs text-[#8a8176]">
                          Sunday reply rate:{" "}
                          {week.sunday_reply_rate_pct != null ? `${formatNum(week.sunday_reply_rate_pct)}%` : "—"}
                        </div>
                      </div>
                    ))
                  )}
                </div>
              </div>

              <div className="rounded-2xl border border-[#e7e1d6] bg-white p-5">
                <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Day-by-day engagement</p>
                <p className="mt-1 text-xs text-[#8a8176]">
                  Sent volume, 24-hour reply rate, and media usage by coaching touchpoint day.
                </p>
                <div className="mt-3 space-y-2">
                  {!coachingDayStats.length ? (
                    <p className="text-sm text-[#8a8176]">No day-level coaching data in this window.</p>
                  ) : (
                    coachingDayStats.map((row) => (
                      <div key={`day-${row.day || "unknown"}`} className="rounded-xl border border-[#efe7db] bg-[#fdfaf4] px-3 py-2">
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <span className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">{row.day || "unknown"}</span>
                          <span className="text-sm font-semibold">{row.sent ?? 0} sent</span>
                        </div>
                        <div className="mt-1 text-xs text-[#6b6257]">
                          users {row.users ?? 0} | replies {row.replied_24h ?? 0} (
                          {row.reply_rate_pct != null ? `${formatNum(row.reply_rate_pct)}%` : "—"})
                        </div>
                        <div className="mt-1 text-xs text-[#8a8176]">
                          with audio {row.with_audio ?? 0} (
                          {row.audio_rate_pct != null ? `${formatNum(row.audio_rate_pct)}%` : "—"})
                        </div>
                      </div>
                    ))
                  )}
                </div>
              </div>
            </section>
          </>
        ) : null}

        {activeTab === "app" ? (
          <>
            <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
              {appMetrics.map((item) => (
                <div key={item.title} className="rounded-2xl border border-[#e7e1d6] bg-white p-5">
                  <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">{item.title}</p>
                  <div className="mt-3 text-3xl font-semibold">{item.value}</div>
                  <p className="mt-2 text-sm text-[#6b6257]">{item.subtitle}</p>
                  <p className="mt-1 text-xs text-[#8a8176]">{item.description}</p>
                </div>
              ))}
            </section>

            <section className="grid gap-4 xl:grid-cols-2">
              <div className="rounded-2xl border border-[#e7e1d6] bg-white p-5">
                <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Page engagement</p>
                <div className="mt-3 space-y-2 text-sm">
                  <div className="rounded-xl border border-[#efe7db] bg-[#fdfaf4] px-3 py-2">
                    Home: {appDetail.home?.views ?? 0} views · {appDetail.home?.users ?? 0} users
                  </div>
                  <div className="rounded-xl border border-[#efe7db] bg-[#fdfaf4] px-3 py-2">
                    Assessment results: {appDetail.assessment_results?.views ?? 0} views · {appDetail.assessment_results?.users ?? 0} users
                  </div>
                  <div className="rounded-xl border border-[#efe7db] bg-[#fdfaf4] px-3 py-2">
                    Library: {appDetail.library?.views ?? 0} views · {appDetail.library?.users ?? 0} users
                  </div>
                </div>
              </div>

              <div className="rounded-2xl border border-[#e7e1d6] bg-white p-5">
                <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Podcast engagement</p>
                <div className="mt-3 space-y-2 text-sm">
                  <div className="rounded-xl border border-[#efe7db] bg-[#fdfaf4] px-3 py-2">
                    Plays: {appDetail.podcasts?.plays ?? 0} · Completes: {appDetail.podcasts?.completes ?? 0}
                  </div>
                  <div className="rounded-xl border border-[#efe7db] bg-[#fdfaf4] px-3 py-2">
                    Listeners: {appDetail.podcasts?.listeners ?? 0} · Completed listeners: {appDetail.podcasts?.completed_listeners ?? 0}
                  </div>
                  <div className="rounded-xl border border-[#efe7db] bg-[#fdfaf4] px-3 py-2">
                    Library plays: {appDetail.podcasts?.library_plays ?? 0} · Assessment plays: {appDetail.podcasts?.assessment_plays ?? 0}
                  </div>
                </div>
              </div>
            </section>

            <section className="rounded-2xl border border-[#e7e1d6] bg-white p-5">
              <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Onboarding funnel</p>
              <p className="mt-2 text-sm text-[#6b6257]">
                First login to coaching auto-enable progression in the selected window.
              </p>
              <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
                <div className="rounded-xl border border-[#efe7db] bg-[#fdfaf4] px-3 py-2 text-sm">
                  First logins: {appOnboarding.first_login_cohort_users ?? 0}
                </div>
                <div className="rounded-xl border border-[#efe7db] bg-[#fdfaf4] px-3 py-2 text-sm">
                  Assessment reviewed: {appOnboarding.assessment_after_first_login_users ?? 0}
                </div>
                <div className="rounded-xl border border-[#efe7db] bg-[#fdfaf4] px-3 py-2 text-sm">
                  Intro completed: {appOnboarding.intro_completed_after_first_login_users ?? 0}
                </div>
                <div className="rounded-xl border border-[#efe7db] bg-[#fdfaf4] px-3 py-2 text-sm">
                  Coaching on: {appOnboarding.coaching_auto_enabled_after_first_login_users ?? 0}
                </div>
              </div>
              {(appOnboarding.funnel || []).length ? (
                <div className="mt-4 space-y-3">
                  {(appOnboarding.funnel || []).map((step, idx) => (
                    <div key={step.key || `${idx}`} className="rounded-xl border border-[#efe7db] bg-[#fdfaf4] px-3 py-3">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <span className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">
                          {idx + 1}. {step.label || step.key || "step"}
                        </span>
                        <span className="text-sm font-semibold">{step.count ?? 0}</span>
                      </div>
                      <div className="mt-1 text-xs text-[#6b6257]">
                        {step.percent_of_first_login != null ? `${formatNum(step.percent_of_first_login)}% of first logins` : "—"}
                      </div>
                      <div className="mt-2 h-2 w-full rounded-full bg-[#ece4d8]">
                        <div className="h-2 rounded-full bg-[#1d4ed8]" style={{ width: barWidth(step.percent_of_first_login ?? null) }} />
                      </div>
                      <div className="mt-2 text-xs text-[#8a8176]">
                        Conversion from previous:{" "}
                        {idx === 0
                          ? "—"
                          : step.conversion_pct_from_prev != null
                            ? `${formatNum(step.conversion_pct_from_prev)}%`
                            : "—"}
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="mt-3 text-sm text-[#8a8176]">No onboarding funnel data in this window.</p>
              )}
            </section>

            <section className="rounded-2xl border border-[#e7e1d6] bg-white p-5">
              <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Daily app trend</p>
              {!appDailyRows.length ? (
                <p className="mt-4 text-sm text-[#8a8176]">No app engagement events in this window.</p>
              ) : (
                <div className="mt-4 overflow-x-auto">
                  <table className="min-w-full text-left text-sm">
                    <thead className="bg-[#f7f4ee] text-xs uppercase tracking-[0.2em] text-[#6b6257]">
                      <tr>
                        <th className="px-3 py-2">Day</th>
                        <th className="px-3 py-2">Active users</th>
                        <th className="px-3 py-2">Home</th>
                        <th className="px-3 py-2">Assessment</th>
                        <th className="px-3 py-2">Library</th>
                        <th className="px-3 py-2">Plays</th>
                        <th className="px-3 py-2">Completes</th>
                      </tr>
                    </thead>
                    <tbody>
                      {appDailyRows.map((row) => (
                        <tr key={row.day} className="border-t border-[#efe7db]">
                          <td className="px-3 py-2">{row.day || "—"}</td>
                          <td className="px-3 py-2">{row.active_users ?? 0}</td>
                          <td className="px-3 py-2">{row.home_views ?? 0}</td>
                          <td className="px-3 py-2">{row.assessment_views ?? 0}</td>
                          <td className="px-3 py-2">{row.library_views ?? 0}</td>
                          <td className="px-3 py-2">{row.podcast_plays ?? 0}</td>
                          <td className="px-3 py-2">{row.podcast_completes ?? 0}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>
          </>
        ) : null}

        {activeTab !== "app" ? (
          <section className="grid gap-4 xl:grid-cols-2">
          <div className="rounded-2xl border border-[#e7e1d6] bg-white p-5">
            <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Active alerts</p>
            {!alerts.length ? (
              <p className="mt-3 text-sm text-[#2f8b55]">No warn/critical alerts in the selected window.</p>
            ) : (
              <div className="mt-3 space-y-2">
                {alerts.map((alert, idx) => (
                  <div key={`${alert.metric}-${idx}`} className="rounded-xl border border-[#efe7db] bg-[#fdfaf4] px-3 py-2">
                    <div className="flex items-center justify-between gap-3">
                      <span className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">{alert.metric || "metric"}</span>
                      <span className={`rounded-full border px-2 py-1 text-[10px] uppercase tracking-[0.2em] ${stateBadgeClass(alert.state)}`}>
                        {(alert.state || "unknown").toUpperCase()}
                      </span>
                    </div>
                    <p className="mt-1 text-sm text-[#6b6257]">
                      value={alert.value ?? "—"} | warn={alert.warn ?? "—"} | critical={alert.critical ?? "—"}
                    </p>
                    <p className="mt-1 text-xs text-[#8a8176]">
                      Triggered because this metric crossed configured warning/critical thresholds.
                    </p>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="rounded-2xl border border-[#e7e1d6] bg-white p-5">
            <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Worker mode</p>
            <div className="mt-3 grid gap-2 sm:grid-cols-2">
              {[
                {
                  label: "Worker effective",
                  value: String(health?.worker?.worker_mode_effective ?? "—"),
                  desc: "Whether prompt jobs are currently routed through the worker service.",
                },
                {
                  label: "Podcast effective",
                  value: String(health?.worker?.podcast_worker_mode_effective ?? "—"),
                  desc: "Whether podcast/audio tasks are currently routed through the worker service.",
                },
                {
                  label: "Worker source",
                  value: String(health?.worker?.worker_mode_source ?? "—"),
                  desc: "Where worker mode came from: admin override or environment variable.",
                },
                {
                  label: "Podcast source",
                  value: String(health?.worker?.podcast_worker_mode_source ?? "—"),
                  desc: "Where podcast mode came from: admin override, env, or disabled by worker mode.",
                },
              ].map((row) => (
                <div key={row.label} className="rounded-xl border border-[#efe7db] bg-[#fdfaf4] px-3 py-2">
                  <div className="text-[10px] uppercase tracking-[0.2em] text-[#6b6257]">{row.label}</div>
                  <div className="mt-1 text-sm">{row.value}</div>
                  <div className="mt-1 text-xs text-[#8a8176]">{row.desc}</div>
                </div>
              ))}
            </div>
          </div>
          </section>
        ) : null}

        {activeTab === "assessment" ? (
          <section className="grid gap-4 xl:grid-cols-2">
            <div className="rounded-2xl border border-[#e7e1d6] bg-white p-5">
              <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Drop-off by question</p>
              <p className="mt-2 text-sm text-[#6b6257]">
                Incomplete runs: {health?.dropoff?.incomplete_runs ?? 0} | Avg last question idx:{" "}
                {health?.dropoff?.avg_last_question_idx ?? "—"}
              </p>
              <p className="mt-1 text-xs text-[#8a8176]">
                Shows where incomplete assessments most commonly stop by question number.
              </p>
              <div className="mt-3 space-y-2">
                {(health?.dropoff?.question_idx_top || []).length ? (
                  (health?.dropoff?.question_idx_top || []).map((row, idx) => (
                    <div key={`${row.question_idx}-${idx}`} className="flex items-center justify-between rounded-xl border border-[#efe7db] bg-[#fdfaf4] px-3 py-2">
                      <span className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Q{row.question_idx ?? "—"}</span>
                      <span className="text-sm font-semibold">{row.count ?? 0}</span>
                    </div>
                  ))
                ) : (
                  <p className="text-sm text-[#8a8176]">No drop-off data in this window.</p>
                )}
              </div>
            </div>

            <div className="rounded-2xl border border-[#e7e1d6] bg-white p-5">
              <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Drop-off by pillar/concept</p>
              <p className="mt-1 text-xs text-[#8a8176]">
                Last recorded pillar/concept for incomplete runs, highlighting friction points.
              </p>
              <div className="mt-3 space-y-2">
                {(health?.dropoff?.points_top || []).length ? (
                  (health?.dropoff?.points_top || []).map((row, idx) => (
                    <div key={`${row.label}-${idx}`} className="flex items-center justify-between rounded-xl border border-[#efe7db] bg-[#fdfaf4] px-3 py-2">
                      <span className="text-xs uppercase tracking-[0.12em] text-[#6b6257]">{row.label || "unknown"}</span>
                      <span className="text-sm font-semibold">{row.count ?? 0}</span>
                    </div>
                  ))
                ) : (
                  <p className="text-sm text-[#8a8176]">No drop-off point data in this window.</p>
                )}
              </div>
            </div>
          </section>
        ) : null}

        {activeTab !== "app" ? (
          <section className="grid gap-4 xl:grid-cols-3">
          <div className="rounded-2xl border border-[#e7e1d6] bg-white p-5">
            <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">LLM quality</p>
            <div className="mt-3 space-y-3">
              {llmPanels.map((panel) => (
                <div key={panel.title} className="rounded-xl border border-[#efe7db] bg-[#fdfaf4] px-3 py-2 text-sm">
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">{panel.title}</span>
                    <span className={`rounded-full border px-2 py-1 text-[10px] uppercase tracking-[0.2em] ${stateBadgeClass(panel.data.duration_ms_state)}`}>
                      {(panel.data.duration_ms_state || "unknown").toUpperCase()}
                    </span>
                  </div>
                  <div className="mt-2 text-xs text-[#6b6257]">{panel.data.prompts ?? 0} prompts</div>
                  <div className="mt-1">p50: {panel.data.duration_ms_p50 != null ? `${Math.round(panel.data.duration_ms_p50)} ms` : "—"}</div>
                  <div className="mt-1">p95: {panel.data.duration_ms_p95 != null ? `${Math.round(panel.data.duration_ms_p95)} ms` : "—"}</div>
                  <div className="mt-1">slow &gt; warn: {panel.data.slow_over_warn ?? 0}</div>
                  <div className="mt-1">slow &gt; critical: {panel.data.slow_over_critical ?? 0}</div>
                  <div className="mt-1 text-xs text-[#8a8176]">{panel.desc}</div>
                </div>
              ))}
            </div>
          </div>

          <div className="rounded-2xl border border-[#e7e1d6] bg-white p-5">
            <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Queue health</p>
            <div className="mt-3 space-y-2 text-sm">
              <div className="rounded-xl border border-[#efe7db] bg-[#fdfaf4] px-3 py-2">
                pending {health?.queue?.pending ?? 0}, retry {health?.queue?.retry ?? 0}, running {health?.queue?.running ?? 0}, error {health?.queue?.error ?? 0}
                <div className="mt-1 text-xs text-[#8a8176]">Current job counts by lifecycle state.</div>
              </div>
              <div className="rounded-xl border border-[#efe7db] bg-[#fdfaf4] px-3 py-2">
                oldest pending age:{" "}
                {health?.queue?.oldest_pending_age_min != null
                  ? `${formatNum(health.queue.oldest_pending_age_min)} min`
                  : "—"}
                <div className="mt-1 text-xs text-[#8a8176]">Age of the oldest unprocessed pending/retry job.</div>
              </div>
              <div className="rounded-xl border border-[#efe7db] bg-[#fdfaf4] px-3 py-2">
                error rate (1h):{" "}
                {health?.queue?.error_rate_1h_pct != null
                  ? `${formatNum(health.queue.error_rate_1h_pct)}%`
                  : "—"}
                <div className="mt-1 text-xs text-[#8a8176]">Share of recently processed jobs that ended in error.</div>
              </div>
            </div>
          </div>

          <div className="rounded-2xl border border-[#e7e1d6] bg-white p-5">
            <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Messaging delivery</p>
            <div className="mt-3 space-y-2 text-sm">
              <div className="rounded-xl border border-[#efe7db] bg-[#fdfaf4] px-3 py-2">
                outbound {health?.messaging?.outbound_messages ?? 0}, inbound {health?.messaging?.inbound_messages ?? 0}
                <div className="mt-1 text-xs text-[#8a8176]">Message volume captured in logs for this time window.</div>
              </div>
              <div className="rounded-xl border border-[#efe7db] bg-[#fdfaf4] px-3 py-2">
                callbacks {health?.messaging?.twilio_callbacks ?? 0}, failures {health?.messaging?.twilio_failures ?? 0}
                <div className="mt-1 text-xs text-[#8a8176]">Delivery callbacks received from Twilio and those marked failed.</div>
              </div>
              <div className="rounded-xl border border-[#efe7db] bg-[#fdfaf4] px-3 py-2">
                failure rate:{" "}
                {health?.messaging?.twilio_failure_rate_pct != null
                  ? `${formatNum(health.messaging.twilio_failure_rate_pct)}%`
                  : "—"}
                <div className="mt-1 text-xs text-[#8a8176]">Failure percentage from Twilio callback outcomes.</div>
              </div>
            </div>
          </div>
          </section>
        ) : null}
      </div>
    </main>
  );
}
