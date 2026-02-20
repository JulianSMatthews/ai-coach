import Link from "next/link";
import AdminNav from "@/components/AdminNav";
import { listAdminUsers, listPromptHistory } from "@/lib/api";

type HistoryPageProps = {
  searchParams: Promise<{ start?: string; end?: string; user?: string; user_id?: string; touchpoint?: string }>;
};

export const dynamic = "force-dynamic";

function formatDate(value?: string | null) {
  if (!value) return "—";
  return String(value).slice(0, 19).replace("T", " ");
}

export default async function PromptHistoryPage({ searchParams }: HistoryPageProps) {
  const resolved = await searchParams;
  const start = (resolved?.start || "").trim();
  const end = (resolved?.end || "").trim();
  const touchpoint = (resolved?.touchpoint || "").trim();
  const user = (resolved?.user_id || resolved?.user || "").trim();
  const userId = user ? Number(user) : undefined;

  const rows = await listPromptHistory(100, userId || undefined, touchpoint || undefined, start || undefined, end || undefined);
  const users = await listAdminUsers();

  return (
    <main className="min-h-screen bg-[#f7f4ee] px-6 py-10 text-[#1e1b16]">
      <div className="mx-auto w-full max-w-6xl space-y-6">
        <AdminNav title="Prompt history" subtitle="Filter by date, touchpoint, or user to inspect generated prompts." />

        <section className="rounded-3xl border border-[#e7e1d6] bg-white p-6">
          <h2 className="text-lg font-semibold">Filters</h2>
          <form className="mt-4 grid gap-3 md:grid-cols-5" method="get">
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
              placeholder="Touchpoint"
              className="rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
            />
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
          <h2 className="text-lg font-semibold">History</h2>
          <p className="mt-2 text-sm text-[#6b6257]">
            Showing the most recent 100 prompts in the selected filter window.
          </p>
          <div className="mt-4 overflow-x-auto">
            <table className="w-full min-w-[960px] text-left text-sm">
              <thead className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">
                <tr>
                  <th className="py-2">Date</th>
                  <th className="py-2">Touchpoint</th>
                  <th className="py-2">User ID</th>
                  <th className="py-2">Name</th>
                  <th className="py-2">Duration</th>
                  <th className="py-2">Source</th>
                  <th className="py-2">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#efe7db]">
                {rows.map((row) => (
                  <tr key={row.id}>
                    <td className="py-3 text-[#6b6257]">{formatDate(row.created_at)}</td>
                    <td className="py-3 font-medium">{row.touchpoint || "—"}</td>
                    <td className="py-3 text-[#6b6257]">{row.user_id ? `#${row.user_id}` : "—"}</td>
                    <td className="py-3 text-[#6b6257]">{row.user_name || "—"}</td>
                    <td className="py-3 text-[#6b6257]">
                      {row.duration_ms ? `${row.duration_ms} ms` : "—"}
                    </td>
                    <td className="py-3 text-[#6b6257]">
                      {row.execution_source || "—"}
                    </td>
                    <td className="py-3">
                      <Link
                        href={`/admin/prompts/history/${row.id}`}
                        className="rounded-full border border-[#efe7db] px-3 py-1 text-xs"
                      >
                        View
                      </Link>
                    </td>
                  </tr>
                ))}
                {!rows.length ? (
                  <tr>
                    <td className="py-6 text-sm text-[#6b6257]" colSpan={7}>
                      No prompt history found for this filter.
                    </td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
        </section>
      </div>
    </main>
  );
}
