import AdminNav from "@/components/AdminNav";
import { getAdminAssessmentHealth } from "@/lib/api";

export const dynamic = "force-dynamic";

type MonitoringSearchParams = {
  days?: string;
  stale_minutes?: string;
};

function clampInt(value: string | undefined, fallback: number, min: number, max: number): number {
  const parsed = Number(value);
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

export default async function MonitoringPage({ searchParams }: { searchParams?: MonitoringSearchParams }) {
  const days = clampInt(searchParams?.days, 7, 1, 30);
  const staleMinutes = clampInt(searchParams?.stale_minutes, 30, 5, 240);

  let health: Awaited<ReturnType<typeof getAdminAssessmentHealth>> | null = null;
  let loadError: string | null = null;
  try {
    health = await getAdminAssessmentHealth({ days, stale_minutes: staleMinutes });
  } catch (error) {
    loadError = error instanceof Error ? error.message : "Failed to load monitoring data.";
  }

  const alerts = health?.alerts || [];
  const metrics = [
    {
      title: "Completion rate",
      value: health?.funnel?.completion_rate_pct != null ? `${formatNum(health?.funnel?.completion_rate_pct)}%` : "—",
      state: health?.funnel?.completion_rate_state,
      subtitle: `${health?.funnel?.completed ?? "—"} completed / ${health?.funnel?.started ?? "—"} started`,
    },
    {
      title: "Median completion",
      value:
        health?.funnel?.median_completion_minutes != null
          ? `${formatNum(health?.funnel?.median_completion_minutes)} min`
          : "—",
      state: health?.funnel?.median_completion_state,
      subtitle: `P95 ${health?.funnel?.p95_completion_minutes != null ? `${formatNum(health?.funnel?.p95_completion_minutes)} min` : "—"}`,
    },
    {
      title: "LLM p95 latency",
      value: health?.llm?.duration_ms_p95 != null ? `${Math.round(health.llm.duration_ms_p95)} ms` : "—",
      state: health?.llm?.duration_ms_state,
      subtitle: `${health?.llm?.assessor_prompts ?? 0} assessor prompts`,
    },
    {
      title: "OKR fallback rate",
      value:
        health?.llm?.okr_generation?.fallback_rate_pct != null
          ? `${formatNum(health.llm.okr_generation.fallback_rate_pct)}%`
          : "—",
      state: health?.llm?.okr_generation?.fallback_rate_state,
      subtitle: `${health?.llm?.okr_generation?.fallback ?? 0} fallback / ${health?.llm?.okr_generation?.calls ?? 0} calls`,
    },
    {
      title: "Queue backlog",
      value: health?.queue?.backlog != null ? `${health.queue.backlog}` : "—",
      state: health?.queue?.backlog_state,
      subtitle: `pending ${health?.queue?.pending ?? 0}, retry ${health?.queue?.retry ?? 0}`,
    },
    {
      title: "Twilio failure rate",
      value:
        health?.messaging?.twilio_failure_rate_pct != null
          ? `${formatNum(health.messaging.twilio_failure_rate_pct)}%`
          : "—",
      state: health?.messaging?.twilio_failure_state,
      subtitle: `${health?.messaging?.twilio_failures ?? 0} failed callbacks`,
    },
  ];

  return (
    <main className="min-h-screen bg-[#f7f4ee] px-6 py-10 text-[#1e1b16]">
      <div className="mx-auto w-full max-w-6xl space-y-6">
        <AdminNav
          title="Assessment monitoring"
          subtitle="Live operational health across funnel, LLM quality, queue, and messaging delivery."
        />

        <section className="rounded-3xl border border-[#e7e1d6] bg-white p-6">
          <div className="flex flex-wrap items-end justify-between gap-4">
            <div>
              <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Window</p>
              <p className="mt-2 text-sm text-[#6b6257]">
                {health?.window?.start_utc || "—"} → {health?.window?.end_utc || "—"}
              </p>
              <p className="mt-1 text-sm text-[#6b6257]">As of: {health?.as_of_utc || "—"}</p>
            </div>
            <form method="get" className="flex flex-wrap items-end gap-3">
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
            </div>
          ))}
        </section>

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
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="rounded-2xl border border-[#e7e1d6] bg-white p-5">
            <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Worker mode</p>
            <div className="mt-3 grid gap-2 sm:grid-cols-2">
              {[
                { label: "Worker effective", value: String(health?.worker?.worker_mode_effective ?? "—") },
                { label: "Podcast effective", value: String(health?.worker?.podcast_worker_mode_effective ?? "—") },
                { label: "Worker source", value: String(health?.worker?.worker_mode_source ?? "—") },
                { label: "Podcast source", value: String(health?.worker?.podcast_worker_mode_source ?? "—") },
              ].map((row) => (
                <div key={row.label} className="rounded-xl border border-[#efe7db] bg-[#fdfaf4] px-3 py-2">
                  <div className="text-[10px] uppercase tracking-[0.2em] text-[#6b6257]">{row.label}</div>
                  <div className="mt-1 text-sm">{row.value}</div>
                </div>
              ))}
            </div>
          </div>
        </section>

        <section className="grid gap-4 xl:grid-cols-2">
          <div className="rounded-2xl border border-[#e7e1d6] bg-white p-5">
            <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Drop-off by question</p>
            <p className="mt-2 text-sm text-[#6b6257]">
              Incomplete runs: {health?.dropoff?.incomplete_runs ?? 0} | Avg last question idx:{" "}
              {health?.dropoff?.avg_last_question_idx ?? "—"}
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

        <section className="grid gap-4 xl:grid-cols-3">
          <div className="rounded-2xl border border-[#e7e1d6] bg-white p-5">
            <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">LLM quality</p>
            <div className="mt-3 space-y-2">
              <div className="rounded-xl border border-[#efe7db] bg-[#fdfaf4] px-3 py-2 text-sm">
                p50: {health?.llm?.duration_ms_p50 != null ? `${Math.round(health.llm.duration_ms_p50)} ms` : "—"}
              </div>
              <div className="rounded-xl border border-[#efe7db] bg-[#fdfaf4] px-3 py-2 text-sm">
                p95: {health?.llm?.duration_ms_p95 != null ? `${Math.round(health.llm.duration_ms_p95)} ms` : "—"}
              </div>
              <div className="rounded-xl border border-[#efe7db] bg-[#fdfaf4] px-3 py-2 text-sm">
                slow &gt; warn: {health?.llm?.slow_over_warn ?? 0}
              </div>
              <div className="rounded-xl border border-[#efe7db] bg-[#fdfaf4] px-3 py-2 text-sm">
                slow &gt; critical: {health?.llm?.slow_over_critical ?? 0}
              </div>
            </div>
          </div>

          <div className="rounded-2xl border border-[#e7e1d6] bg-white p-5">
            <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Queue health</p>
            <div className="mt-3 space-y-2 text-sm">
              <div className="rounded-xl border border-[#efe7db] bg-[#fdfaf4] px-3 py-2">
                pending {health?.queue?.pending ?? 0}, retry {health?.queue?.retry ?? 0}, running {health?.queue?.running ?? 0}, error {health?.queue?.error ?? 0}
              </div>
              <div className="rounded-xl border border-[#efe7db] bg-[#fdfaf4] px-3 py-2">
                oldest pending age:{" "}
                {health?.queue?.oldest_pending_age_min != null
                  ? `${formatNum(health.queue.oldest_pending_age_min)} min`
                  : "—"}
              </div>
              <div className="rounded-xl border border-[#efe7db] bg-[#fdfaf4] px-3 py-2">
                error rate (1h):{" "}
                {health?.queue?.error_rate_1h_pct != null
                  ? `${formatNum(health.queue.error_rate_1h_pct)}%`
                  : "—"}
              </div>
            </div>
          </div>

          <div className="rounded-2xl border border-[#e7e1d6] bg-white p-5">
            <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Messaging delivery</p>
            <div className="mt-3 space-y-2 text-sm">
              <div className="rounded-xl border border-[#efe7db] bg-[#fdfaf4] px-3 py-2">
                outbound {health?.messaging?.outbound_messages ?? 0}, inbound {health?.messaging?.inbound_messages ?? 0}
              </div>
              <div className="rounded-xl border border-[#efe7db] bg-[#fdfaf4] px-3 py-2">
                callbacks {health?.messaging?.twilio_callbacks ?? 0}, failures {health?.messaging?.twilio_failures ?? 0}
              </div>
              <div className="rounded-xl border border-[#efe7db] bg-[#fdfaf4] px-3 py-2">
                failure rate:{" "}
                {health?.messaging?.twilio_failure_rate_pct != null
                  ? `${formatNum(health.messaging.twilio_failure_rate_pct)}%`
                  : "—"}
              </div>
            </div>
          </div>
        </section>
      </div>
    </main>
  );
}
