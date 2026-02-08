import AdminNav from "@/components/AdminNav";
import { getAdminProfile, getAdminStats, getAdminUsageSummary } from "@/lib/api";

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
        </section>
      </div>
    </main>
  );
}
