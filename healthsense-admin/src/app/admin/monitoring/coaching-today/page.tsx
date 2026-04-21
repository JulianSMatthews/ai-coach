import Link from "next/link";
import AdminNav from "@/components/AdminNav";
import { getAdminCoachingTodayDrilldown } from "@/lib/api";

export const dynamic = "force-dynamic";
type CoachingTodayPageProps = {
  searchParams: Promise<{ category?: string }>;
};

function formatDateTime(value?: string | null) {
  if (!value) return "—";
  return String(value).slice(0, 19).replace("T", " ");
}

function deliveryBadgeClass(value?: string | null) {
  const key = String(value || "").toLowerCase();
  if (key === "received" || key === "read" || key === "replied" || key === "succeeded" || key === "ready") {
    return "border-[#2f8b55] bg-[#eaf7ef] text-[#14532d]";
  }
  if (key === "failed" || key === "error") return "border-[#c43d3d] bg-[#fdeaea] text-[#8c1d1d]";
  if (key === "pending" || key === "attempted" || key === "queued" || key === "running") {
    return "border-[#cc9a2f] bg-[#fff6e6] text-[#825b0b]";
  }
  return "border-[#d8d1c4] bg-[#f7f4ee] text-[#6b6257]";
}

function previewText(value?: string | null) {
  const text = String(value || "").trim();
  if (!text) return "—";
  const cleaned = text.replace(/\s+/g, " ");
  return cleaned.length > 140 ? `${cleaned.slice(0, 140)}…` : cleaned;
}

export default async function CoachingTodayDrilldownPage({ searchParams }: CoachingTodayPageProps) {
  const resolved = await searchParams;
  const selectedCategory = String(resolved?.category || "").trim();
  const data = await getAdminCoachingTodayDrilldown();
  const categories = data?.categories || [];
  const ratio = data?.ratio?.display || "—";
  const dayLabel = String(data?.day_key || "today");
  const dateFilter = String(data?.day_start_uk || "").slice(0, 10);

  return (
    <main className="min-h-screen bg-[#f7f4ee] px-6 py-10 text-[#1e1b16]">
      <div className="mx-auto w-full max-w-7xl space-y-6">
        <AdminNav
          title={`Gia Readiness Today (${dayLabel})`}
          subtitle="User-level breakdown for today ratio: Daily records : Refresh queued/running : Gia ready : Refresh failed."
        />

        <section className="rounded-3xl border border-[#e7e1d6] bg-white p-6">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Readiness ratio</p>
              <p className="mt-2 text-3xl font-semibold">{ratio}</p>
              <p className="mt-2 text-sm text-[#6b6257]">
                Score date: {data?.score_date || "—"} · Mode: {data?.mode || "current"}
              </p>
            </div>
            <p className="text-sm text-[#6b6257]">As of {formatDateTime(data?.as_of_utc)}</p>
          </div>
        </section>

        {categories.map((category) => {
          const users = category.users || [];
          const categoryKey = String(category.key || "").trim();
          const isSelected = Boolean(categoryKey) && selectedCategory === categoryKey;
          return (
            <section key={category.key || category.label} className="rounded-3xl border border-[#e7e1d6] bg-white p-6">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <h2 className="text-lg font-semibold">{category.label || "Category"}</h2>
                  <p className="mt-1 text-sm text-[#6b6257]">{category.description || "—"}</p>
                </div>
                <div className="flex items-center gap-2">
                  <div className="rounded-xl bg-[#f7f4ee] px-3 py-2">
                    <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Total</p>
                    <p className="text-2xl font-semibold">{category.total ?? 0}</p>
                  </div>
                </div>
              </div>

              {categoryKey ? (
                <div className="mt-4 flex flex-wrap items-center gap-3">
                  <Link
                    href={
                      isSelected
                        ? "/admin/monitoring/coaching-today"
                        : `/admin/monitoring/coaching-today?category=${encodeURIComponent(categoryKey)}`
                    }
                    className="rounded-full border border-[#1d6a4f] px-3 py-1 text-sm text-[#1d6a4f]"
                  >
                    {isSelected ? "Hide users" : "Click to view users"}
                  </Link>
                </div>
              ) : null}

              {isSelected ? (!users.length ? (
                <p className="mt-4 text-sm text-[#6b6257]">No users in this category today.</p>
              ) : (
                <div className="mt-4 overflow-x-auto">
                  <table className="min-w-full text-sm">
                    <thead>
                        <tr className="border-b border-[#efe7db] text-left text-xs uppercase tracking-[0.2em] text-[#6b6257]">
                          <th className="px-3 py-2">User</th>
                          <th className="px-3 py-2">Daily records</th>
                          <th className="px-3 py-2">Refresh state</th>
                          <th className="px-3 py-2">Readiness</th>
                          <th className="px-3 py-2">Actions</th>
                        </tr>
                    </thead>
                    <tbody>
                        {users.map((user) => {
                          const uid = Number(user.user_id || 0);
                          const refreshState = String(user.refresh_status || user.latest_refresh_job?.status || "none");
                          const readinessState = user.gia_ready ? "ready" : refreshState;
                          return (
                            <tr key={`${category.key}-${uid}`} className="border-b border-[#f1ebdf] align-top">
                              <td className="px-3 py-3">
                                <div className="font-medium">{user.user_name || `User #${uid}`}</div>
                                <div className="text-xs text-[#6b6257]">{user.phone || "—"}</div>
                                <div className="text-xs text-[#8a8176]">ID {uid}</div>
                              </td>
                              <td className="px-3 py-3">
                                <div className="text-sm font-semibold">{user.tracker_entries_today ?? 0} entries today</div>
                                <div className="mt-1 text-xs text-[#6b6257]">Last entry: {formatDateTime(user.last_tracker_entry_at)}</div>
                                <div className="mt-1 text-xs text-[#8a8176]">{user.has_today_entry ? "Today check-in exists" : "No today check-in"}</div>
                              </td>
                              <td className="px-3 py-3">
                                <span className={`rounded-full border px-2 py-1 text-[10px] uppercase tracking-[0.2em] ${deliveryBadgeClass(refreshState)}`}>
                                  {refreshState}
                                </span>
                                <div className="mt-2 text-xs text-[#6b6257]">Plan date: {user.refresh_plan_date || "—"}</div>
                                <div className="text-xs text-[#6b6257]">Updated: {formatDateTime(user.refresh_updated_at)}</div>
                                {user.latest_refresh_job?.id ? (
                                  <div className="mt-2 text-xs text-[#8a8176]">
                                    Job #{user.latest_refresh_job.id} · {formatDateTime(user.latest_refresh_job.updated_at)}
                                  </div>
                                ) : null}
                                {user.latest_refresh_job?.error ? (
                                  <div className="mt-2 max-w-xs text-xs text-[#8c1d1d]">{previewText(user.latest_refresh_job.error)}</div>
                                ) : null}
                              </td>
                              <td className="px-3 py-3">
                                <span className={`rounded-full border px-2 py-1 text-[10px] uppercase tracking-[0.2em] ${deliveryBadgeClass(readinessState)}`}>
                                  {user.gia_ready ? "Gia ready" : "Gia not ready"}
                                </span>
                                <div className="mt-2 text-xs text-[#6b6257]">Habits: {user.habits_ready ? "ready" : "not ready"}</div>
                                <div className="text-xs text-[#6b6257]">Insight: {user.insight_ready ? "ready" : "not ready"}</div>
                              </td>
                              <td className="px-3 py-3">
                                <div className="flex flex-col gap-2">
                                  <Link
                                    href={`/admin/users/${uid}`}
                                    className="rounded-full border border-[#1d6a4f] px-3 py-1 text-center text-xs uppercase tracking-[0.16em] text-[#1d6a4f]"
                                  >
                                    User
                                  </Link>
                                  <Link
                                    href={`/admin/history/touchpoints?user_id=${uid}${dateFilter ? `&start=${dateFilter}&end=${dateFilter}` : ""}`}
                                    className="rounded-full border border-[#efe7db] px-3 py-1 text-center text-xs uppercase tracking-[0.16em]"
                                  >
                                    Touchpoints
                                  </Link>
                              </div>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )) : null}
            </section>
          );
        })}
      </div>
    </main>
  );
}
