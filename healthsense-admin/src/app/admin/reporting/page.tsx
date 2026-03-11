import AdminNav from "@/components/AdminNav";
import FetchRatesButton from "@/components/FetchRatesButton";
import CopyValueField from "@/components/CopyValueField";
import {
  fetchUsageSettings,
  getAdminMarketingFunnel,
  getAdminPromptCosts,
  getAdminUsageSummary,
  getUsageSettings,
  listAdminUsers,
  type UsageSettings,
  updateUsageSettings,
} from "@/lib/api";
import { revalidatePath } from "next/cache";

export const dynamic = "force-dynamic";

async function saveUsageSettingsAction(formData: FormData) {
  "use server";
  const toNumber = (value: FormDataEntryValue | null) => {
    if (value == null) return null;
    const raw = typeof value === "string" ? value.trim() : "";
    if (!raw) return null;
    const parsed = Number(raw);
    return Number.isFinite(parsed) ? parsed : null;
  };
  const miniInput = toNumber(formData.get("llm_gbp_per_1m_input_tokens_gpt_5_mini"));
  const miniOutput = toNumber(formData.get("llm_gbp_per_1m_output_tokens_gpt_5_mini"));
  const gpt51Input = toNumber(formData.get("llm_gbp_per_1m_input_tokens_gpt_5_1"));
  const gpt51Output = toNumber(formData.get("llm_gbp_per_1m_output_tokens_gpt_5_1"));
  const modelRates: Record<string, { input?: number; output?: number }> = {};
  if (miniInput != null || miniOutput != null) {
    modelRates["gpt-5-mini"] = {};
    if (miniInput != null) modelRates["gpt-5-mini"].input = miniInput;
    if (miniOutput != null) modelRates["gpt-5-mini"].output = miniOutput;
  }
  if (gpt51Input != null || gpt51Output != null) {
    modelRates["gpt-5.1"] = {};
    if (gpt51Input != null) modelRates["gpt-5.1"].input = gpt51Input;
    if (gpt51Output != null) modelRates["gpt-5.1"].output = gpt51Output;
  }
  const payload: UsageSettings = {
    tts_gbp_per_1m_chars: toNumber(formData.get("tts_gbp_per_1m_chars")),
    tts_chars_per_min: toNumber(formData.get("tts_chars_per_min")),
    llm_model_rates: Object.keys(modelRates).length ? modelRates : null,
    wa_gbp_per_message: toNumber(formData.get("wa_gbp_per_message")),
    wa_gbp_per_media_message: toNumber(formData.get("wa_gbp_per_media_message")),
    wa_gbp_per_template_message: toNumber(formData.get("wa_gbp_per_template_message")),
  };
  await updateUsageSettings(payload);
  revalidatePath("/admin/reporting");
}

async function fetchUsageSettingsAction() {
  "use server";
  await fetchUsageSettings();
  revalidatePath("/admin/reporting");
}

type ReportingSearchParams = {
  period?: string;
  start?: string;
  end?: string;
  user_id?: string;
  source?: string;
  campaign?: string;
};

export default async function ReportingPage({
  searchParams,
}: {
  searchParams: Promise<ReportingSearchParams>;
}) {
  const resolvedSearchParams = (await searchParams) || {};
  const apiBase = process.env.API_BASE_URL || process.env.NEXT_PUBLIC_API_BASE_URL || "";
  const period = typeof resolvedSearchParams?.period === "string" ? resolvedSearchParams.period : "7";
  const start = typeof resolvedSearchParams?.start === "string" ? resolvedSearchParams.start : undefined;
  const end = typeof resolvedSearchParams?.end === "string" ? resolvedSearchParams.end : undefined;
  const userIdRaw = typeof resolvedSearchParams?.user_id === "string" ? resolvedSearchParams.user_id : "";
  const sourceRaw = typeof resolvedSearchParams?.source === "string" ? resolvedSearchParams.source : "";
  const campaignRaw = typeof resolvedSearchParams?.campaign === "string" ? resolvedSearchParams.campaign : "";
  const userId = userIdRaw ? Number(userIdRaw) : undefined;
  const days = period === "custom" ? undefined : Number(period || 7);

  const [settings, usage, marketing, promptCosts, users] = await Promise.all([
    getUsageSettings(),
    getAdminUsageSummary({
      days: Number.isFinite(days) ? days : 7,
      start: period === "custom" ? start : undefined,
      end: period === "custom" ? end : undefined,
      user_id: Number.isFinite(userId) ? userId : undefined,
    }),
    getAdminMarketingFunnel({
      days: Number.isFinite(days) ? days : 7,
      start: period === "custom" ? start : undefined,
      end: period === "custom" ? end : undefined,
      user_id: Number.isFinite(userId) ? userId : undefined,
      source: sourceRaw || undefined,
      campaign: campaignRaw || undefined,
    }),
    getAdminPromptCosts({
      days: Number.isFinite(days) ? days : 7,
      start: period === "custom" ? start : undefined,
      end: period === "custom" ? end : undefined,
      user_id: Number.isFinite(userId) ? userId : undefined,
      limit: 50,
    }),
    listAdminUsers(),
  ]);
  const meta = (() => {
    if (!settings?.meta) return null;
    if (typeof settings.meta === "string") {
      try {
        return JSON.parse(settings.meta);
      } catch {
        return null;
      }
    }
    return settings.meta;
  })();
  const fetchedAt = typeof meta?.fetched_at === "string" ? meta.fetched_at : null;
  const fx = typeof meta?.fx_usd_to_gbp === "number" ? meta.fx_usd_to_gbp : null;
  const fxSourceRaw = meta?.fx_source;
  const fxSourceLabel = typeof fxSourceRaw === "string" ? fxSourceRaw : "default";
  const warnings = Array.isArray(meta?.warnings) ? meta.warnings : [];
  const status = typeof meta?.status === "string" ? meta.status : null;
  const updatedKeys = Array.isArray(meta?.updated_keys) ? meta.updated_keys : [];
  const sources =
    meta?.sources && typeof meta.sources === "object"
      ? (meta.sources as Record<string, unknown>)
      : null;
  const ttsSource =
    sources?.tts && typeof sources.tts === "object" ? (sources.tts as Record<string, unknown>) : null;
  const llmSource =
    sources?.llm && typeof sources.llm === "object" ? (sources.llm as Record<string, unknown>) : null;
  const waSource =
    sources?.whatsapp && typeof sources.whatsapp === "object"
      ? (sources.whatsapp as Record<string, unknown>)
      : null;
  const ttsProvider = typeof ttsSource?.provider === "string" ? ttsSource.provider : null;
  const llmProvider = typeof llmSource?.provider === "string" ? llmSource.provider : null;
  const waProvider = typeof waSource?.provider === "string" ? waSource.provider : null;
  const providerLine = [ttsProvider ? `TTS: ${ttsProvider}` : null, llmProvider ? `LLM: ${llmProvider}` : null, waProvider ? `WhatsApp: ${waProvider}` : null]
    .filter(Boolean)
    .join(" · ");
  const modelRates = settings?.llm_model_rates || {};
  const llmMiniInput = modelRates["gpt-5-mini"]?.input ?? "";
  const llmMiniOutput = modelRates["gpt-5-mini"]?.output ?? "";
  const llm51Input = modelRates["gpt-5.1"]?.input ?? "";
  const llm51Output = modelRates["gpt-5.1"]?.output ?? "";
  const appBaseRaw = (
    process.env.NEXT_PUBLIC_HSAPP_BASE_URL ||
    process.env.HSAPP_PUBLIC_URL ||
    process.env.NEXT_PUBLIC_APP_BASE_URL ||
    process.env.APP_BASE_URL ||
    "https://app.healthsense.coach"
  ).trim();
  const appBase =
    (appBaseRaw.startsWith("http://") || appBaseRaw.startsWith("https://") ? appBaseRaw : `https://${appBaseRaw}`)
      .replace(/\/+$/, "");
  const leadStartKey = (process.env.PUBLIC_LEAD_START_KEY || "").trim();
  const campaignToken = (campaignRaw || "assessment_launch").trim();
  const metaLaunchUrl =
    `${appBase}/ig/start?` +
    (leadStartKey ? `k=${encodeURIComponent(leadStartKey)}&` : "") +
    `source=instagram&campaign=${encodeURIComponent(campaignToken)}` +
    `&utm_source=instagram&utm_medium=paid_social&utm_campaign=${encodeURIComponent(campaignToken)}` +
    "&campaign_id={{campaign.id}}&adset_id={{adset.id}}&ad_id={{ad.id}}&placement={{placement}}&site_source_name={{site_source_name}}";

  return (
    <main className="min-h-screen bg-[#f7f4ee] px-6 py-10 text-[#1e1b16]">
      <div className="mx-auto w-full max-w-5xl space-y-6">
        <AdminNav
          title="Reporting"
          subtitle="Two sections: Marketing and Cost Analysis."
        />

        <section className="rounded-3xl border border-[#e7e1d6] bg-white p-6">
          <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Sections</p>
          <div className="mt-3 flex flex-wrap gap-3">
            <a
              href="#reporting-marketing"
              className="rounded-full border border-[var(--accent)] bg-[var(--accent)] px-4 py-2 text-xs uppercase tracking-[0.2em] text-white"
            >
              Marketing
            </a>
            <a
              href="#reporting-cost-analysis"
              className="rounded-full border border-[#efe7db] bg-[#fdfaf4] px-4 py-2 text-xs uppercase tracking-[0.2em] text-[#3c332b]"
            >
              Cost Analysis
            </a>
          </div>
        </section>

        <section id="reporting-marketing" className="rounded-3xl border border-[#e7e1d6] bg-white p-6">
          <div className="flex flex-wrap items-end justify-between gap-4">
            <div>
              <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Marketing</p>
              <p className="mt-2 text-sm text-[#6b6257]">
                Window: {marketing?.window?.start_utc ?? "—"} → {marketing?.window?.end_utc ?? "—"}
              </p>
            </div>
            <div className="rounded-2xl border border-[#efe7db] bg-[#fdfaf4] px-4 py-3">
              <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Key rates</p>
              <p className="mt-1 text-sm text-[#3c332b]">
                Landing → Lead: {marketing?.funnel?.landing_to_lead_pct ?? "—"}%
              </p>
              <p className="text-sm text-[#3c332b]">
                Lead → Complete: {marketing?.funnel?.lead_to_complete_pct ?? marketing?.funnel?.start_to_complete_pct ?? "—"}%
              </p>
              <p className="text-sm text-[#3c332b]">
                Complete → Claimed: {marketing?.funnel?.complete_to_claim_pct ?? "—"}%
              </p>
              <p className="text-sm text-[#3c332b]">
                Claimed → Results viewed: {marketing?.funnel?.claim_to_results_view_pct ?? "—"}%
              </p>
            </div>
          </div>
          <form method="get" className="mt-4 flex flex-wrap items-end gap-3">
            <div>
              <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Period</label>
              <select
                name="period"
                defaultValue={period}
                className="mt-2 w-full rounded-xl border border-[#efe7db] bg-white px-3 py-2 text-sm"
              >
                <option value="7">Last 7 days</option>
                <option value="14">Last 14 days</option>
                <option value="30">Last 30 days</option>
                <option value="90">Last 90 days</option>
                <option value="custom">Custom</option>
              </select>
            </div>
            <div>
              <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Start</label>
              <input
                type="date"
                name="start"
                defaultValue={start || ""}
                className="mt-2 w-full rounded-xl border border-[#efe7db] bg-white px-3 py-2 text-sm"
              />
            </div>
            <div>
              <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">End</label>
              <input
                type="date"
                name="end"
                defaultValue={end || ""}
                className="mt-2 w-full rounded-xl border border-[#efe7db] bg-white px-3 py-2 text-sm"
              />
            </div>
            <div>
              <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">User</label>
              <select
                name="user_id"
                defaultValue={userIdRaw}
                className="mt-2 w-full rounded-xl border border-[#efe7db] bg-white px-3 py-2 text-sm"
              >
                <option value="">All users</option>
                {(users || []).map((user) => {
                  const label =
                    user.display_name ||
                    [user.first_name, user.surname].filter(Boolean).join(" ") ||
                    user.phone ||
                    `User ${user.id}`;
                  return (
                    <option key={user.id} value={String(user.id)}>
                      {label} (#{user.id})
                    </option>
                  );
                })}
              </select>
            </div>
            <div>
              <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Source</label>
              <input
                type="text"
                name="source"
                defaultValue={sourceRaw}
                placeholder="instagram"
                className="mt-2 w-full rounded-xl border border-[#efe7db] bg-white px-3 py-2 text-sm"
              />
            </div>
            <div>
              <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Campaign</label>
              <input
                type="text"
                name="campaign"
                defaultValue={campaignRaw}
                placeholder="assessment_launch"
                className="mt-2 w-full rounded-xl border border-[#efe7db] bg-white px-3 py-2 text-sm"
              />
            </div>
            <button
              type="submit"
              className="rounded-full border border-[var(--accent)] bg-[var(--accent)] px-5 py-2 text-xs uppercase tracking-[0.2em] text-white"
            >
              Run marketing report
            </button>
          </form>
          <p className="mt-2 text-sm text-[#6b6257]">
            Filters: source {sourceRaw || "all"} · campaign {campaignRaw || "all"}
          </p>
          <div className="mt-4 rounded-2xl border border-[#efe7db] bg-[#fdfaf4] p-4">
            <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Meta URL</p>
            <p className="mt-1 text-sm text-[#6b6257]">
              Use this as the destination URL in Meta ads.
            </p>
            <div className="mt-3">
              <CopyValueField value={metaLaunchUrl} />
            </div>
          </div>

          <div className="mt-4 grid gap-4 lg:grid-cols-3 xl:grid-cols-6">
            {(marketing?.funnel?.steps || []).map((step) => (
              <div key={step.key || step.label} className="rounded-2xl border border-[#efe7db] bg-[#fdfaf4] p-4">
                <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">{step.label || step.key}</p>
                <p className="mt-2 text-2xl font-semibold">{step.count ?? 0}</p>
                <p className="mt-1 text-xs text-[#8a8176]">
                  {step.percent_of_start != null ? `${step.percent_of_start}% of landing views` : "—"}
                </p>
                <p className="mt-1 text-xs text-[#8a8176]">
                  {step.conversion_pct_from_prev != null
                    ? `${step.conversion_pct_from_prev}% from previous`
                    : "Start stage"}
                </p>
              </div>
            ))}
          </div>

          <div className="mt-4 grid gap-4 lg:grid-cols-2">
            <details className="rounded-2xl border border-[#efe7db] bg-white" open>
              <summary className="cursor-pointer px-4 py-3 text-sm font-medium text-[#3c332b]">
                Breakdown by source ({marketing?.breakdown?.by_source?.length ?? 0})
              </summary>
              <div className="overflow-x-auto border-t border-[#efe7db]">
                <table className="min-w-full text-left text-sm">
                  <thead className="bg-[#f7f4ee] text-xs uppercase tracking-[0.2em] text-[#6b6257]">
                    <tr>
                      <th className="px-4 py-3">Source</th>
                      <th className="px-4 py-3">Landing views</th>
                      <th className="px-4 py-3">Leads</th>
                      <th className="px-4 py-3">Completed</th>
                      <th className="px-4 py-3">Claimed</th>
                      <th className="px-4 py-3">Viewed</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(marketing?.breakdown?.by_source || []).map((row) => (
                      <tr key={row.key} className="border-t border-[#efe7db]">
                        <td className="px-4 py-3">{row.key || "unknown"}</td>
                        <td className="px-4 py-3">
                          {row.landing_views ?? 0}
                          <span className="ml-2 text-xs text-[#8a8176]">({row.landing_to_lead_pct ?? "—"}%)</span>
                        </td>
                        <td className="px-4 py-3">{row.leads ?? 0}</td>
                        <td className="px-4 py-3">
                          {row.assessment_completed ?? 0}
                          <span className="ml-2 text-xs text-[#8a8176]">({row.lead_to_complete_pct ?? row.start_to_complete_pct ?? "—"}%)</span>
                        </td>
                        <td className="px-4 py-3">
                          {row.identity_claimed ?? 0}
                          <span className="ml-2 text-xs text-[#8a8176]">({row.claim_rate_pct ?? "—"}%)</span>
                        </td>
                        <td className="px-4 py-3">
                          {row.results_viewed ?? 0}
                          <span className="ml-2 text-xs text-[#8a8176]">({row.results_view_rate_pct ?? "—"}%)</span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </details>

            <details className="rounded-2xl border border-[#efe7db] bg-white" open>
              <summary className="cursor-pointer px-4 py-3 text-sm font-medium text-[#3c332b]">
                Top campaigns ({marketing?.breakdown?.by_campaign?.length ?? 0})
              </summary>
              <div className="overflow-x-auto border-t border-[#efe7db]">
                <table className="min-w-full text-left text-sm">
                  <thead className="bg-[#f7f4ee] text-xs uppercase tracking-[0.2em] text-[#6b6257]">
                    <tr>
                      <th className="px-4 py-3">Campaign</th>
                      <th className="px-4 py-3">Landing views</th>
                      <th className="px-4 py-3">Leads</th>
                      <th className="px-4 py-3">Started</th>
                      <th className="px-4 py-3">Completed</th>
                      <th className="px-4 py-3">Viewed</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(marketing?.breakdown?.by_campaign || []).map((row) => (
                      <tr key={row.key} className="border-t border-[#efe7db]">
                        <td className="px-4 py-3">{row.key || "(none)"}</td>
                        <td className="px-4 py-3">{row.landing_views ?? 0}</td>
                        <td className="px-4 py-3">{row.leads ?? 0}</td>
                        <td className="px-4 py-3">{row.assessment_started ?? 0}</td>
                        <td className="px-4 py-3">{row.assessment_completed ?? 0}</td>
                        <td className="px-4 py-3">{row.results_viewed ?? 0}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </details>
          </div>
        </section>

        <section id="reporting-cost-analysis" className="rounded-3xl border border-[#e7e1d6] bg-white p-6">
          <div className="flex flex-wrap items-end justify-between gap-4">
            <div>
              <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Cost analysis overview</p>
              <p className="mt-2 text-sm text-[#6b6257]">
                Window: {usage?.window?.start_utc ?? "—"} → {usage?.window?.end_utc ?? "—"}
              </p>
              {usage?.user ? (
                <p className="mt-1 text-sm text-[#6b6257]">
                  User: {usage.user.display_name || usage.user.phone || usage.user.id}
                </p>
              ) : null}
            </div>
            <form method="get" className="flex flex-wrap items-end gap-3">
              <div>
                <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Period</label>
                <select
                  name="period"
                  defaultValue={period}
                  className="mt-2 w-full rounded-xl border border-[#efe7db] bg-white px-3 py-2 text-sm"
                >
                  <option value="7">Last 7 days</option>
                  <option value="14">Last 14 days</option>
                  <option value="30">Last 30 days</option>
                  <option value="90">Last 90 days</option>
                  <option value="custom">Custom</option>
                </select>
              </div>
              <div>
                <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Start</label>
                <input
                  type="date"
                  name="start"
                  defaultValue={start || ""}
                  className="mt-2 w-full rounded-xl border border-[#efe7db] bg-white px-3 py-2 text-sm"
                />
              </div>
              <div>
                <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">End</label>
                <input
                  type="date"
                  name="end"
                  defaultValue={end || ""}
                  className="mt-2 w-full rounded-xl border border-[#efe7db] bg-white px-3 py-2 text-sm"
                />
              </div>
              <div>
                <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">User</label>
                <select
                  name="user_id"
                  defaultValue={userIdRaw}
                  className="mt-2 w-full rounded-xl border border-[#efe7db] bg-white px-3 py-2 text-sm"
                >
                  <option value="">All users</option>
                  {(users || []).map((user) => {
                    const label =
                      user.display_name ||
                      [user.first_name, user.surname].filter(Boolean).join(" ") ||
                      user.phone ||
                      `User ${user.id}`;
                    return (
                      <option key={user.id} value={String(user.id)}>
                        {label} (#{user.id})
                      </option>
                    );
                  })}
                </select>
              </div>
              <button
                type="submit"
                className="rounded-full border border-[var(--accent)] bg-[var(--accent)] px-5 py-2 text-xs uppercase tracking-[0.2em] text-white"
              >
                Run cost analysis
              </button>
            </form>
          </div>
          <div className="mt-4 grid gap-4 lg:grid-cols-4">
            {[
              {
                title: "TTS",
                rows: [
                  { label: "Events", value: usage?.total_tts?.events ?? "—" },
                  { label: "Minutes (est)", value: usage?.total_tts?.minutes_est ?? "—" },
                  { label: "Cost (est)", value: usage?.total_tts?.cost_est_gbp != null ? `£${usage.total_tts.cost_est_gbp}` : "—" },
                ],
              },
              {
                title: "LLM",
                rows: [
                  { label: "Tokens in", value: usage?.llm_total?.tokens_in ?? "—" },
                  { label: "Tokens out", value: usage?.llm_total?.tokens_out ?? "—" },
                  { label: "Cost (est)", value: usage?.llm_total?.cost_est_gbp != null ? `£${usage.llm_total.cost_est_gbp}` : "—" },
                ],
              },
              {
                title: "WhatsApp",
                rows: [
                  { label: "Messages", value: usage?.whatsapp_total?.messages ?? "—" },
                  { label: "Cost (est)", value: usage?.whatsapp_total?.cost_est_gbp != null ? `£${usage.whatsapp_total.cost_est_gbp}` : "—" },
                ],
              },
              {
                title: "Combined",
                rows: [
                  {
                    label: "Total cost (est)",
                    value: usage?.combined_cost_gbp != null ? `£${usage.combined_cost_gbp}` : "—",
                  },
                ],
              },
            ].map((card) => (
              <div key={card.title} className="rounded-2xl border border-[#efe7db] bg-[#fdfaf4] p-4">
                <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">{card.title}</p>
                <div className="mt-3 space-y-2">
                  {card.rows.map((row) => (
                    <div key={row.label} className="flex items-center justify-between rounded-xl bg-white px-3 py-2">
                      <span className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">{row.label}</span>
                      <span className="text-lg font-semibold">{row.value}</span>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </section>

        <section className="rounded-3xl border border-[#e7e1d6] bg-white p-6">
          <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Cost analysis · Prompt cost breakdown</p>
          <p className="mt-2 text-sm text-[#6b6257]">
            Drill into LLM prompt costs for the selected user and period.
          </p>
          {!promptCosts?.rows?.length ? (
            <p className="mt-4 text-sm text-[#8a8176]">No LLM prompt costs found in this window.</p>
          ) : (
            <div className="mt-4 space-y-4">
              <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-[#efe7db] bg-[#fdfaf4] px-4 py-3">
                <div>
                  <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Total prompt cost (est)</p>
                  <p className="mt-1 text-lg font-semibold">
                    £{promptCosts.total_cost_gbp ?? "—"}
                  </p>
                </div>
                <p className="text-xs text-[#8a8176]">
                  Showing top {promptCosts.limit ?? 50} prompts by cost
                  {Number.isFinite(userId) ? "" : " (all users)"}.
                </p>
              </div>
              <details className="rounded-2xl border border-[#efe7db] bg-white">
                <summary className="cursor-pointer px-4 py-3 text-sm font-medium text-[#3c332b]">
                  Show prompt transactions ({promptCosts.rows.length})
                </summary>
                <div className="overflow-x-auto border-t border-[#efe7db]">
                  <table className="min-w-full text-left text-sm">
                    <thead className="bg-[#f7f4ee] text-xs uppercase tracking-[0.2em] text-[#6b6257]">
                      <tr>
                        <th className="px-4 py-3">Prompt</th>
                        <th className="px-4 py-3">Tokens In</th>
                        <th className="px-4 py-3">Tokens Out</th>
                        <th className="px-4 py-3">Rates (GBP/1M)</th>
                        <th className="px-4 py-3">Cost (est)</th>
                        <th className="px-4 py-3">Working</th>
                      </tr>
                    </thead>
                    <tbody>
                      {promptCosts.rows.map((row) => (
                        <tr key={row.prompt_id} className="border-t border-[#efe7db]">
                          <td className="px-4 py-3 align-top">
                            <div className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">
                              {row.touchpoint || "prompt"} · {row.model || "model"}
                              {row.user_id ? ` · user ${row.user_id}` : ""}
                            </div>
                            <div className="mt-2 text-sm text-[#1e1b16]">
                              {row.prompt_title || row.task_label || row.prompt_variant || row.touchpoint || "Prompt"}
                            </div>
                            {apiBase && row.prompt_id ? (
                              <a
                                href={`${apiBase}/admin/prompts/history/${row.prompt_id}`}
                                className="mt-2 inline-flex text-xs uppercase tracking-[0.2em] text-[var(--accent)]"
                                target="_blank"
                                rel="noreferrer"
                              >
                                View log
                              </a>
                            ) : null}
                          </td>
                          <td className="px-4 py-3 align-top">{Math.round(row.tokens_in || 0)}</td>
                          <td className="px-4 py-3 align-top">{Math.round(row.tokens_out || 0)}</td>
                          <td className="px-4 py-3 align-top">
                            <div>In: £{row.rate_in ?? "—"}</div>
                            <div>Out: £{row.rate_out ?? "—"}</div>
                          </td>
                          <td className="px-4 py-3 align-top">
                            £{row.cost_est_gbp ?? "—"}
                          </td>
                          <td className="px-4 py-3 align-top text-xs text-[#6b6257]">
                            {row.working || "—"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </details>
            </div>
          )}
        </section>

        <section className="rounded-3xl border border-[#e7e1d6] bg-white p-6">
          <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Cost analysis · Cost assumptions</p>
          <p className="mt-2 text-sm text-[#6b6257]">
            These values override environment defaults. Leave blank to use env rates.
          </p>
          <div className="mt-4 rounded-2xl border border-[#efe7db] bg-[#fdfaf4] p-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Provider rates</p>
                <p className="mt-1 text-sm text-[#6b6257]">
                  {fetchedAt ? `Last fetched: ${fetchedAt}` : "Not fetched yet"}
                </p>
                {fx ? (
                  <p className="mt-1 text-xs text-[#8a8176]">FX USD-&gt;GBP: {fx} ({fxSourceLabel})</p>
                ) : null}
                {providerLine ? <p className="mt-1 text-xs text-[#8a8176]">{providerLine}</p> : null}
                {status === "failed" ? (
                  <p className="mt-2 text-xs text-[#a24f3c]">Fetch failed — no provider rates updated.</p>
                ) : status === "partial" ? (
                  <p className="mt-2 text-xs text-[#8a8176]">
                    Partial update: {updatedKeys.length ? updatedKeys.join(", ") : "some rates"}.
                  </p>
                ) : null}
                {warnings.length ? (
                  <p className="mt-2 text-xs text-[#a24f3c]">Warnings: {warnings.join(", ")}</p>
                ) : null}
              </div>
              <FetchRatesButton action={fetchUsageSettingsAction} />
            </div>
          </div>
          <form action={saveUsageSettingsAction} className="mt-6 grid gap-4 lg:grid-cols-2">
            <div>
              <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">TTS £ / 1M chars</label>
              <input
                name="tts_gbp_per_1m_chars"
                defaultValue={settings.tts_gbp_per_1m_chars ?? ""}
                className="mt-2 w-full rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
              />
            </div>
            <div>
              <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">TTS chars per min</label>
              <input
                name="tts_chars_per_min"
                defaultValue={settings.tts_chars_per_min ?? ""}
                className="mt-2 w-full rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
              />
            </div>
            <div>
              <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">LLM (gpt-5-mini) £ / 1M input tokens</label>
              <input
                name="llm_gbp_per_1m_input_tokens_gpt_5_mini"
                defaultValue={llmMiniInput}
                className="mt-2 w-full rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
              />
            </div>
            <div>
              <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">LLM (gpt-5-mini) £ / 1M output tokens</label>
              <input
                name="llm_gbp_per_1m_output_tokens_gpt_5_mini"
                defaultValue={llmMiniOutput}
                className="mt-2 w-full rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
              />
            </div>
            <div>
              <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">LLM (gpt-5.1) £ / 1M input tokens</label>
              <input
                name="llm_gbp_per_1m_input_tokens_gpt_5_1"
                defaultValue={llm51Input}
                className="mt-2 w-full rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
              />
            </div>
            <div>
              <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">LLM (gpt-5.1) £ / 1M output tokens</label>
              <input
                name="llm_gbp_per_1m_output_tokens_gpt_5_1"
                defaultValue={llm51Output}
                className="mt-2 w-full rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
              />
            </div>
            <div>
              <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">WhatsApp £ / message</label>
              <input
                name="wa_gbp_per_message"
                defaultValue={settings.wa_gbp_per_message ?? ""}
                className="mt-2 w-full rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
              />
            </div>
            <div>
              <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">WhatsApp £ / media message</label>
              <input
                name="wa_gbp_per_media_message"
                defaultValue={settings.wa_gbp_per_media_message ?? ""}
                className="mt-2 w-full rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
              />
            </div>
            <div>
              <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">WhatsApp £ / template message</label>
              <input
                name="wa_gbp_per_template_message"
                defaultValue={settings.wa_gbp_per_template_message ?? ""}
                className="mt-2 w-full rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
              />
            </div>
            <div className="lg:col-span-2">
              <p className="text-xs text-[#8a8176]">
                These two model rates are saved and used directly for per-transaction prompt costing.
              </p>
            </div>
            <div className="flex items-end">
              <button
                type="submit"
                className="rounded-full border border-[var(--accent)] bg-[var(--accent)] px-6 py-2 text-xs uppercase tracking-[0.2em] text-white"
              >
                Save rates
              </button>
            </div>
          </form>
        </section>
      </div>
    </main>
  );
}
