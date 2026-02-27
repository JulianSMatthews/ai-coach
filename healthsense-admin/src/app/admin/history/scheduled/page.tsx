import AdminNav from "@/components/AdminNav";
import { listAdminUsers, listCoachingScheduled } from "@/lib/api";

type CoachingScheduledPageProps = {
  searchParams: Promise<{ user_id?: string; only_enabled?: string; limit?: string }>;
};

export const dynamic = "force-dynamic";

function formatDate(value?: string | null) {
  if (!value) return "—";
  const dt = new Date(value);
  if (Number.isNaN(dt.getTime())) return String(value).slice(0, 19).replace("T", " ");
  return dt.toISOString().slice(0, 19).replace("T", " ");
}

function statusClass(status?: string | null) {
  const key = String(status || "").toLowerCase();
  if (key === "scheduled") return "border-[#2f8b55] bg-[#eaf7ef] text-[#14532d]";
  if (key === "missing_job" || key === "scheduled_while_disabled") return "border-[#cc9a2f] bg-[#fff6e6] text-[#825b0b]";
  return "border-[#d8d1c4] bg-[#f7f4ee] text-[#6b6257]";
}

function titleCase(value?: string | null) {
  const txt = String(value || "").trim();
  if (!txt) return "—";
  return txt.charAt(0).toUpperCase() + txt.slice(1);
}

function deliveryStateClass(value?: string | null) {
  const key = String(value || "").toLowerCase();
  if (key === "received") return "border-[#2f8b55] bg-[#eaf7ef] text-[#14532d]";
  if (key === "failed") return "border-[#c43d3d] bg-[#fdeaea] text-[#8c1d1d]";
  if (key === "attempted") return "border-[#cc9a2f] bg-[#fff6e6] text-[#825b0b]";
  return "border-[#d8d1c4] bg-[#f7f4ee] text-[#6b6257]";
}

export default async function CoachingScheduledPage({ searchParams }: CoachingScheduledPageProps) {
  const resolved = await searchParams;
  const userRaw = (resolved?.user_id || "").trim();
  const userId = userRaw ? Number(userRaw) : undefined;
  const limitRaw = (resolved?.limit || "").trim();
  const limitParsed = limitRaw ? Number(limitRaw) : 300;
  const limit = Number.isFinite(limitParsed) ? Math.max(50, Math.min(1000, Math.trunc(limitParsed))) : 300;
  const onlyEnabled = (resolved?.only_enabled || "1").trim() !== "0";

  const [{ items, summary }, users] = await Promise.all([
    listCoachingScheduled(limit, userId || undefined, onlyEnabled),
    listAdminUsers(),
  ]);

  return (
    <main className="min-h-screen bg-[#f7f4ee] px-6 py-10 text-[#1e1b16]">
      <div className="mx-auto w-full max-w-7xl space-y-6">
        <AdminNav title="Scheduled coaching" subtitle="Review user-level upcoming coaching jobs and schedule health." />

        <section className="rounded-3xl border border-[#e7e1d6] bg-white p-6">
          <h2 className="text-lg font-semibold">Filters</h2>
          <form className="mt-4 grid gap-3 md:grid-cols-4" method="get">
            <input
              name="user_id"
              defaultValue={userRaw}
              placeholder="User ID"
              list="scheduled-user-options"
              className="rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
            />
            <datalist id="scheduled-user-options">
              {users.map((u) => (
                <option
                  key={u.id}
                  value={u.id}
                  label={`${u.first_name || ""} ${u.surname || ""} ${u.phone || ""}`.trim()}
                />
              ))}
            </datalist>
            <input
              name="limit"
              defaultValue={String(limit)}
              placeholder="Limit"
              className="rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
            />
            <label className="flex items-center gap-2 rounded-xl border border-[#efe7db] px-3 py-2 text-sm">
              <input type="checkbox" name="only_enabled" value="1" defaultChecked={onlyEnabled} />
              Enabled users only
            </label>
            <button
              type="submit"
              className="rounded-full border border-[var(--accent)] bg-[var(--accent)] px-4 py-2 text-xs uppercase tracking-[0.2em] text-white"
            >
              Apply filters
            </button>
          </form>
        </section>

        <section className="grid gap-4 md:grid-cols-5">
          {[
            { label: "Users", value: summary?.users ?? 0 },
            { label: "Enabled users", value: summary?.enabled_users ?? 0 },
            { label: "Rows", value: summary?.rows ?? 0 },
            { label: "Scheduled rows", value: summary?.scheduled_rows ?? 0 },
            { label: "Missing rows", value: summary?.missing_rows ?? 0 },
          ].map((card) => (
            <article key={card.label} className="rounded-2xl border border-[#e7e1d6] bg-white p-4">
              <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">{card.label}</p>
              <p className="mt-2 text-2xl font-semibold">{card.value}</p>
            </article>
          ))}
        </section>

        <section className="rounded-3xl border border-[#e7e1d6] bg-white p-6">
          <h2 className="text-lg font-semibold">Schedule rows</h2>
          <p className="mt-2 text-sm text-[#6b6257]">Each row is one user-day schedule record (Mon-Sun).</p>
          <div className="mt-4 overflow-x-auto">
            <table className="w-full min-w-[1540px] text-left text-sm">
              <thead className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">
                <tr>
                  <th className="py-2 pr-4">User</th>
                  <th className="py-2 pr-4">Day</th>
                  <th className="py-2 pr-4">Status</th>
                  <th className="py-2 pr-4">Next run (local)</th>
                  <th className="py-2 pr-4">Next run (UTC)</th>
                  <th className="py-2 pr-4">What will be sent</th>
                  <th className="py-2 pr-4">Mode</th>
                  <th className="py-2 pr-4">Source</th>
                  <th className="py-2 pr-4">Time local</th>
                  <th className="py-2 pr-4">Latest delivery</th>
                  <th className="py-2 pr-4">Job ID</th>
                  <th className="py-2 pr-4">Trigger</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#efe7db]">
                {(items || []).map((row, idx) => {
                  const userLabel =
                    row.user_name || (row.user_id ? `User #${row.user_id}` : "Unknown user");
                  const userMeta = [row.phone || null, row.timezone || null].filter(Boolean).join(" · ");
                  return (
                    <tr key={`${row.user_id || "u"}-${row.day_key || "d"}-${idx}`}>
                      <td className="py-3 pr-4">
                        <p className="font-medium">{userLabel}</p>
                        <p className="text-xs text-[#6b6257]">{userMeta || "—"}</p>
                      </td>
                      <td className="py-3 pr-4">{titleCase(row.day_key)}</td>
                      <td className="py-3 pr-4">
                        <span className={`rounded-full border px-2 py-1 text-[11px] uppercase tracking-[0.18em] ${statusClass(row.status)}`}>
                          {String(row.status || "unknown").replaceAll("_", " ")}
                        </span>
                      </td>
                      <td className="py-3 pr-4">{formatDate(row.next_run_local)}</td>
                      <td className="py-3 pr-4">{formatDate(row.next_run_utc)}</td>
                      <td className="py-3 pr-4">
                        <p className="max-w-[320px]">{row.planned_message || "—"}</p>
                        <p className="text-xs text-[#6b6257]">
                          {row.planned_touchpoint ? `touchpoint: ${row.planned_touchpoint}` : "touchpoint: —"}
                          {row.planned_delivery ? ` · ${row.planned_delivery}` : ""}
                          {row.first_day_override ? " · first-day override" : ""}
                          {row.first_day_catchup ? " · catch-up job" : ""}
                        </p>
                        {row.first_day_sent_at ? (
                          <p className="text-xs text-[#6b6257]">first-day sent: {formatDate(row.first_day_sent_at)}</p>
                        ) : null}
                      </td>
                      <td className="py-3 pr-4">
                        {row.schedule_mode || "—"}
                        {row.fast_minutes ? ` (${row.fast_minutes}m)` : ""}
                      </td>
                      <td className="py-3 pr-4">{row.schedule_source || "—"}</td>
                      <td className="py-3 pr-4">{row.time_local || "—"}</td>
                      <td className="py-3 pr-4">
                        <div className="space-y-1">
                          <span className={`inline-flex rounded-full border px-2 py-1 text-[11px] uppercase tracking-[0.18em] ${deliveryStateClass(row.last_delivery_state)}`}>
                            {String(row.last_delivery_state || "unknown")}
                          </span>
                          <p className="text-xs text-[#6b6257]">
                            status: {row.last_delivery_status || "—"}
                            {row.last_delivery_error_code ? ` · error ${row.last_delivery_error_code}` : ""}
                          </p>
                          {row.last_delivery_error_description ? (
                            <p className="max-w-[260px] text-xs text-[#8a8176]">{row.last_delivery_error_description}</p>
                          ) : null}
                          <p className="text-xs text-[#8a8176]">
                            message: {formatDate(row.last_message_at)} · callback: {formatDate(row.last_delivery_last_callback_at)}
                          </p>
                        </div>
                      </td>
                      <td className="py-3 pr-4 font-mono text-xs text-[#6b6257]">{row.job_id || "—"}</td>
                      <td className="py-3 pr-4 font-mono text-xs text-[#6b6257]">{row.job_trigger || "—"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          {!items?.length ? (
            <p className="mt-4 text-sm text-[#6b6257]">No schedule rows found for this filter.</p>
          ) : null}
        </section>
      </div>
    </main>
  );
}
