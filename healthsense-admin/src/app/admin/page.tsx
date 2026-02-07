import AdminNav from "@/components/AdminNav";
import { getAdminProfile, getAdminStats, getAdminUsageWeekly } from "@/lib/api";

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
  let usage: Awaited<ReturnType<typeof getAdminUsageWeekly>> | null = null;
  try {
    usage = await getAdminUsageWeekly();
  } catch {
    usage = null;
  }

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

        <section className="grid gap-4 lg:grid-cols-2">
          {[
            {
              title: "Reporting analysis",
              desc: "Weekly flow audio usage (estimated, last 7 days).",
              data: usage?.weekly_flow,
            },
            {
              title: "All audio usage",
              desc: "Total TTS usage across all sources (last 7 days).",
              data: usage?.total_tts,
            },
            {
              title: "LLM usage (weekly flow)",
              desc: "Estimated tokens for weekly flow prompts (last 7 days).",
              data: usage?.llm_weekly,
            },
            {
              title: "WhatsApp messages",
              desc: "Total WhatsApp messages sent (last 7 days).",
              data: usage?.whatsapp_total,
            },
          ].map((item) => (
            <div key={item.title} className="rounded-2xl border border-[#efe7db] bg-white p-5">
              <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">{item.title}</p>
              <p className="mt-2 text-sm text-[#6b6257]">{item.desc}</p>
              <div className="mt-4 space-y-3">
                {("events" in (item.data || {})) && (
                  <>
                    {[
                      { label: "Audio events", value: item.data?.events ?? "—" },
                      { label: "Minutes (est)", value: item.data?.minutes_est ?? "—" },
                      { label: "Cost (est)", value: item.data?.cost_est_gbp != null ? `£${item.data.cost_est_gbp}` : "—" },
                      { label: "Chars", value: item.data?.chars ?? "—" },
                    ].map((row) => (
                      <div key={row.label} className="flex items-center justify-between rounded-xl bg-[#f7f4ee] px-3 py-2">
                        <span className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">{row.label}</span>
                        <span className="text-lg font-semibold">{row.value}</span>
                      </div>
                    ))}
                  </>
                )}
                {("tokens_in" in (item.data || {})) && (
                  <>
                    {[
                      { label: "Tokens in", value: item.data?.tokens_in ?? "—" },
                      { label: "Tokens out", value: item.data?.tokens_out ?? "—" },
                      { label: "Cost (est)", value: item.data?.cost_est_gbp != null ? `£${item.data.cost_est_gbp}` : "—" },
                    ].map((row) => (
                      <div key={row.label} className="flex items-center justify-between rounded-xl bg-[#f7f4ee] px-3 py-2">
                        <span className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">{row.label}</span>
                        <span className="text-lg font-semibold">{row.value}</span>
                      </div>
                    ))}
                  </>
                )}
                {("messages" in (item.data || {})) && (
                  <>
                    {[
                      { label: "Messages", value: item.data?.messages ?? "—" },
                      { label: "Cost (est)", value: item.data?.cost_est_gbp != null ? `£${item.data.cost_est_gbp}` : "—" },
                    ].map((row) => (
                      <div key={row.label} className="flex items-center justify-between rounded-xl bg-[#f7f4ee] px-3 py-2">
                        <span className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">{row.label}</span>
                        <span className="text-lg font-semibold">{row.value}</span>
                      </div>
                    ))}
                  </>
                )}
              </div>
              {item.data?.rate_gbp_per_1m_chars ? (
                <p className="mt-3 text-xs text-[#6b6257]">
                  Rate: £{item.data.rate_gbp_per_1m_chars} / 1M chars ({item.data.rate_source || "env"}).
                </p>
              ) : item.data?.rate_gbp_per_1m_input_tokens || item.data?.rate_gbp_per_1m_output_tokens ? (
                <p className="mt-3 text-xs text-[#6b6257]">
                  Rate: £{item.data?.rate_gbp_per_1m_input_tokens || "—"} in / £{item.data?.rate_gbp_per_1m_output_tokens || "—"} out (1M tokens).
                </p>
              ) : item.data?.rate_gbp_per_message ? (
                <p className="mt-3 text-xs text-[#6b6257]">
                  Rate: £{item.data?.rate_gbp_per_message} per message ({item.data?.rate_source || "env"}).
                </p>
              ) : (
                <p className="mt-3 text-xs text-[#6b6257]">Rate not configured yet.</p>
              )}
            </div>
          ))}
        </section>
      </div>
    </main>
  );
}
