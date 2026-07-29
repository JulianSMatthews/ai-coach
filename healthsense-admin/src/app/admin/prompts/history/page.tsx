import AdminNav from "@/components/AdminNav";
import { listAdminUsers, listBackgroundJobHistory } from "@/lib/api";

type HistoryPageProps = {
  searchParams: Promise<{ start?: string; end?: string; user?: string; user_id?: string; touchpoint?: string; window?: string }>;
};

export const dynamic = "force-dynamic";

const HISTORY_WINDOW_OPTIONS = [
  { value: "3h", label: "Last 3 hours", hours: 3 },
  { value: "6h", label: "Last 6 hours", hours: 6 },
  { value: "12h", label: "Last 12 hours", hours: 12 },
  { value: "24h", label: "Last 24 hours", hours: 24 },
  { value: "7d", label: "Last 7 days", hours: 7 * 24 },
  { value: "14d", label: "Last 14 days", hours: 14 * 24 },
  { value: "30d", label: "Last 30 days", hours: 30 * 24 },
] as const;

function formatDate(value?: string | null) {
  if (!value) return "—";
  return String(value).slice(0, 19).replace("T", " ");
}

type HistoryRow = Awaited<ReturnType<typeof listBackgroundJobHistory>>["items"][number];

function HistoryTable({ rows, emptyMessage }: { rows: HistoryRow[]; emptyMessage: string }) {
  return (
    <div className="mt-4 overflow-x-auto">
      <table className="w-full min-w-[1040px] text-left text-sm">
        <thead className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">
          <tr>
            <th className="py-2">Date</th>
            <th className="py-2">Job</th>
            <th className="py-2">User ID</th>
            <th className="py-2">Name</th>
            <th className="py-2">Duration</th>
            <th className="py-2">Status</th>
            <th className="py-2">Attempts</th>
            <th className="py-2">Error</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-[#efe7db]">
          {rows.map((row) => (
            <tr key={row.id}>
              <td className="py-3 text-[#6b6257]">{formatDate(row.created_at)}</td>
              <td className="py-3 font-medium">{row.kind || "—"}</td>
              <td className="py-3 text-[#6b6257]">{row.user_id != null ? `#${row.user_id}` : "Not recorded"}</td>
              <td className="py-3 text-[#6b6257]">{row.user_name || "—"}</td>
              <td className="py-3 text-[#6b6257]">{row.duration_ms != null ? `${row.duration_ms} ms` : "—"}</td>
              <td className="py-3 text-[#6b6257]">{row.status || "—"}</td>
              <td className="py-3 text-[#6b6257]">{row.attempts ?? 0}</td>
              <td className="max-w-[18rem] py-3 text-[#6b6257]">{row.error || "—"}</td>
            </tr>
          ))}
          {!rows.length ? (
            <tr>
              <td className="py-6 text-sm text-[#6b6257]" colSpan={8}>{emptyMessage}</td>
            </tr>
          ) : null}
        </tbody>
      </table>
    </div>
  );
}

export default async function PromptHistoryPage({ searchParams }: HistoryPageProps) {
  const resolved = await searchParams;
  const start = (resolved?.start || "").trim();
  const end = (resolved?.end || "").trim();
  const touchpoint = (resolved?.touchpoint || "").trim();
  const user = (resolved?.user_id || resolved?.user || "").trim();
  const userId = user ? Number(user) : undefined;
  const requestedWindow = (resolved?.window || "7d").trim().toLowerCase();
  const windowSelection = HISTORY_WINDOW_OPTIONS.find((option) => option.value === requestedWindow) || HISTORY_WINDOW_OPTIONS[4];
  const windowHours = start || end ? undefined : windowSelection.hours;

  const [history, users] = await Promise.all([
    listBackgroundJobHistory(100, userId || undefined, touchpoint || undefined, start || undefined, end || undefined, windowHours),
    listAdminUsers(),
  ]);
  const rows = history.items || [];
  const jobKinds = history.kinds || [];

  return (
    <main className="min-h-screen bg-[#f7f4ee] px-6 py-10 text-[#1e1b16]">
      <div className="mx-auto w-full max-w-6xl space-y-6">
        <AdminNav title="Service history" subtitle="Review jobs processed through the background service." />

        <section className="rounded-3xl border border-[#e7e1d6] bg-white p-6">
          <h2 className="text-lg font-semibold">Filters</h2>
          <form className="mt-4 grid gap-3 md:grid-cols-6" method="get">
            <select
              name="window"
              defaultValue={windowSelection.value}
              className="rounded-xl border border-[#efe7db] bg-white px-3 py-2 text-sm"
              aria-label="History window"
            >
              {HISTORY_WINDOW_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>{option.label}</option>
              ))}
            </select>
            <input
              type="date"
              name="start"
              defaultValue={start}
              className="rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
            />
            <input
              type="date"
              name="end"
              defaultValue={end}
              className="rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
            />
            <input
              name="touchpoint"
              defaultValue={touchpoint}
              placeholder="Job kind"
              list="touchpoint-options"
              className="rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
            />
            <datalist id="touchpoint-options">
              {jobKinds.map((tp) => (
                <option key={tp} value={tp} />
              ))}
            </datalist>
            <input
              name="user_id"
              defaultValue={user}
              placeholder="User ID"
              list="user-options"
              className="rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
            />
            <datalist id="user-options">
              {users.map((u) => (
                <option
                  key={u.id}
                  value={u.id}
                  label={`${u.first_name || ""} ${u.surname || ""} ${u.phone || ""}`.trim()}
                />
              ))}
            </datalist>
            <button
              type="submit"
              className="rounded-full border border-[var(--accent)] bg-[var(--accent)] px-4 py-2 text-xs uppercase tracking-[0.2em] text-white"
            >
              Apply filters
            </button>
          </form>
        </section>

        <section className="rounded-3xl border border-[#e7e1d6] bg-white p-6">
          <h2 className="text-lg font-semibold">Background Jobs</h2>
          <p className="mt-2 text-sm text-[#6b6257]">
            Jobs from the background_jobs table for {start || end ? "the custom date range" : windowSelection.label.toLowerCase()}.
            {" "}Showing {rows.length} of the latest 100 records.
          </p>
          <HistoryTable rows={rows} emptyMessage="No background jobs found for this filter." />
        </section>
      </div>
    </main>
  );
}
