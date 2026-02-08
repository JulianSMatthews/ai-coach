import AdminNav from "@/components/AdminNav";
import FetchRatesButton from "@/components/FetchRatesButton";
import { fetchUsageSettings, getAdminUsageSummary, getUsageSettings, updateUsageSettings } from "@/lib/api";
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
  const payload = {
    tts_gbp_per_1m_chars: toNumber(formData.get("tts_gbp_per_1m_chars")),
    tts_chars_per_min: toNumber(formData.get("tts_chars_per_min")),
    llm_gbp_per_1m_input_tokens: toNumber(formData.get("llm_gbp_per_1m_input_tokens")),
    llm_gbp_per_1m_output_tokens: toNumber(formData.get("llm_gbp_per_1m_output_tokens")),
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
};

export default async function ReportingPage({ searchParams }: { searchParams?: ReportingSearchParams }) {
  const period = typeof searchParams?.period === "string" ? searchParams.period : "7";
  const start = typeof searchParams?.start === "string" ? searchParams.start : undefined;
  const end = typeof searchParams?.end === "string" ? searchParams.end : undefined;
  const userIdRaw = typeof searchParams?.user_id === "string" ? searchParams.user_id : "";
  const userId = userIdRaw ? Number(userIdRaw) : undefined;
  const days = period === "custom" ? undefined : Number(period || 7);

  const [settings, usage] = await Promise.all([
    getUsageSettings(),
    getAdminUsageSummary({
      days: Number.isFinite(days) ? days : 7,
      start: period === "custom" ? start : undefined,
      end: period === "custom" ? end : undefined,
      user_id: Number.isFinite(userId) ? userId : undefined,
    }),
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
    meta?.sources && typeof meta.sources === "object" ? (meta.sources as Record<string, any>) : null;
  const ttsProvider = typeof sources?.tts?.provider === "string" ? sources.tts.provider : null;
  const llmProvider = typeof sources?.llm?.provider === "string" ? sources.llm.provider : null;
  const waProvider =
    typeof sources?.whatsapp?.provider === "string" ? sources.whatsapp.provider : null;
  const providerLine = [ttsProvider ? `TTS: ${ttsProvider}` : null, llmProvider ? `LLM: ${llmProvider}` : null, waProvider ? `WhatsApp: ${waProvider}` : null]
    .filter(Boolean)
    .join(" · ");

  return (
    <main className="min-h-screen bg-[#f7f4ee] px-6 py-10 text-[#1e1b16]">
      <div className="mx-auto w-full max-w-5xl space-y-6">
        <AdminNav
          title="Reporting & costs"
          subtitle="Review weekly usage and update cost assumptions."
        />

        <section className="rounded-3xl border border-[#e7e1d6] bg-white p-6">
          <div className="flex flex-wrap items-end justify-between gap-4">
            <div>
              <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Usage summary</p>
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
                <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">User ID</label>
                <input
                  name="user_id"
                  defaultValue={userIdRaw}
                  placeholder="All users"
                  className="mt-2 w-full rounded-xl border border-[#efe7db] bg-white px-3 py-2 text-sm"
                />
              </div>
              <button
                type="submit"
                className="rounded-full border border-[var(--accent)] bg-[var(--accent)] px-5 py-2 text-xs uppercase tracking-[0.2em] text-white"
              >
                Run
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
          <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Cost assumptions</p>
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
              <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">LLM £ / 1M input tokens</label>
              <input
                name="llm_gbp_per_1m_input_tokens"
                defaultValue={settings.llm_gbp_per_1m_input_tokens ?? ""}
                className="mt-2 w-full rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
              />
            </div>
            <div>
              <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">LLM £ / 1M output tokens</label>
              <input
                name="llm_gbp_per_1m_output_tokens"
                defaultValue={settings.llm_gbp_per_1m_output_tokens ?? ""}
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
