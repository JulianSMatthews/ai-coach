import Link from "next/link";
import AdminNav from "@/components/AdminNav";
import {
  getAdminAppEngagement,
  getAdminMarketingFunnel,
  getAdminProfile,
  getAdminStats,
  getAdminUsageSummary,
} from "@/lib/api";

export const dynamic = "force-dynamic";

type DashboardRow = {
  label: string;
  value: string | number;
  href?: string;
};

function DashboardCard({ title, description, rows }: { title: string; description: string; rows: DashboardRow[] }) {
  return (
    <div className="rounded-2xl border border-[#efe7db] bg-white p-5">
      <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">{title}</p>
      <p className="mt-2 min-h-10 text-sm text-[#6b6257]">{description}</p>
      <div className="mt-4 space-y-3">
        {rows.map((row) => (
          <div key={row.label} className="flex items-center justify-between gap-3 rounded-xl bg-[#f7f4ee] px-3 py-2">
            <span className="text-xs uppercase tracking-[0.16em] text-[#6b6257]">{row.label}</span>
            {row.href ? (
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
  );
}

export default async function AdminHome() {
  const profile = await getAdminProfile();
  const name = profile.user?.display_name || "Admin";

  const [statsResult, usageResult, engagementResult, acquisitionResult] = await Promise.allSettled([
    getAdminStats(),
    getAdminUsageSummary({ days: 7 }),
    getAdminAppEngagement({ days: 7 }),
    getAdminMarketingFunnel({ days: 7 }),
  ]);
  const stats = statsResult.status === "fulfilled" ? statsResult.value : null;
  const usage = usageResult.status === "fulfilled" ? usageResult.value : null;
  const appEngagement = engagementResult.status === "fulfilled" ? engagementResult.value : null;
  const acquisition = acquisitionResult.status === "fulfilled" ? acquisitionResult.value : null;
  const estimatedSevenDayCost = usage
    ? Number(usage.llm_total?.cost_est_gbp || 0) +
      Number(usage.total_tts?.cost_est_gbp || 0) +
      Number(usage.avatar_total?.cost_est_gbp || 0)
    : null;

  const appKpis = appEngagement?.top_kpis || {};
  const todayKey = String(appEngagement?.as_of_uk || "").slice(0, 10);
  const todayApp = (appEngagement?.detail?.daily || []).find((row) => row.day === todayKey);
  const storeDownloadsConnected = acquisition?.acquisition?.confirmed_store_downloads_status === "connected";

  const cards = [
    {
      title: "Users",
      description: "CoachSense app accounts and recent account creation.",
      rows: [
        { label: "Total", value: stats?.users?.total ?? "—", href: "/admin/users" },
        { label: "New today", value: stats?.users?.today ?? "—", href: "/admin/users" },
        { label: "New · 7 days", value: stats?.users?.week ?? "—", href: "/admin/users" },
      ],
    },
    {
      title: "App acquisition",
      description: "Website interest and movement into the app over the last 7 days.",
      rows: [
        {
          label: "Website views",
          value: acquisition?.acquisition?.coachsense_ai_homepage_views ?? "—",
          href: "/admin/reporting?tab=marketing",
        },
        {
          label: storeDownloadsConnected ? "Store downloads" : "Download clicks",
          value: storeDownloadsConnected
            ? (acquisition?.acquisition?.confirmed_store_downloads ?? "—")
            : (acquisition?.acquisition?.download_button_clicks ?? "—"),
          href: "/admin/reporting?tab=marketing",
        },
        {
          label: "First activations",
          value: acquisition?.acquisition?.first_app_activations ?? "—",
          href: "/admin/reporting?tab=marketing",
        },
      ],
    },
    {
      title: "Today",
      description: "Distinct users active and completing the app's core activities today.",
      rows: [
        { label: "Active users", value: todayApp?.active_users ?? 0, href: "/admin/monitoring?tab=app" },
        { label: "Check-ins", value: todayApp?.check_in_completions ?? 0, href: "/admin/monitoring?tab=app" },
        { label: "Lessons", value: todayApp?.lesson_completions ?? 0, href: "/admin/monitoring?tab=app" },
      ],
    },
    {
      title: "Last 7 days",
      description: "App reach and completed core activities across the reporting week.",
      rows: [
        { label: "Active users", value: appKpis.active_app_users ?? "—", href: "/admin/monitoring?tab=app" },
        { label: "Check-ins", value: appKpis.daily_check_in_completions ?? 0, href: "/admin/monitoring?tab=app" },
        { label: "Lessons", value: appKpis.education_lesson_completions ?? 0, href: "/admin/monitoring?tab=app" },
      ],
    },
  ];

  return (
    <main className="min-h-screen bg-[#f7f4ee] px-6 py-10 text-[#1e1b16]">
      <div className="mx-auto w-full max-w-6xl space-y-6">
        <AdminNav
          title={`Welcome, ${name}`}
          subtitle="A concise view of app acquisition, users, and completed CoachSense activity."
        />

        <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          {cards.map((card) => (
            <DashboardCard key={card.title} title={card.title} description={card.description} rows={card.rows} />
          ))}
        </section>

        <section className="rounded-2xl border border-[#efe7db] bg-white p-5">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Estimated platform usage</p>
              <p className="mt-2 text-sm text-[#6b6257]">
                Read-only 7-day estimate for recorded LLM, TTS, and avatar usage. Provider invoices remain authoritative.
              </p>
            </div>
            <span className="text-3xl font-semibold">
              {estimatedSevenDayCost != null ? `£${estimatedSevenDayCost.toFixed(4)}` : "—"}
            </span>
          </div>
        </section>
      </div>
    </main>
  );
}
