import AdminNav from "@/components/AdminNav";
import ContentGeneratorClient from "./ContentGeneratorClient";
import { listContentGenerations, listContentPromptTemplates } from "@/lib/api";

type PageProps = {
  searchParams: Promise<{
    touchpoint?: string;
    user_id?: string;
    start?: string;
    end?: string;
  }>;
};

export const dynamic = "force-dynamic";

const formatDateTime = (value?: string | null) => {
  if (!value) return "—";
  try {
    const dt = new Date(value);
    if (Number.isNaN(dt.getTime())) return "—";
    return dt.toLocaleString("en-GB", {
      day: "2-digit",
      month: "2-digit",
      year: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      timeZone: "Europe/London",
    });
  } catch {
    return "—";
  }
};

export default async function ContentGeneratorPage({ searchParams }: PageProps) {
  const params = await searchParams;
  const touchpoint = (params.touchpoint || "").trim();
  const user_id = (params.user_id || "").trim();
  const start = (params.start || "").trim();
  const end = (params.end || "").trim();

  const templates = await listContentPromptTemplates();

  const items = await listContentGenerations({
    touchpoint: touchpoint || undefined,
    user_id: user_id || undefined,
    start: start || undefined,
    end: end || undefined,
    limit: 100,
  });

  return (
    <main className="min-h-screen bg-[#f7f4ee] px-6 py-10 text-[#1e1b16]">
      <div className="mx-auto w-full max-w-6xl space-y-6">
        <AdminNav title="Content generator" subtitle="Generate and store prompt outputs for review." />

        <section className="rounded-3xl border border-[#e7e1d6] bg-white p-6">
          <ContentGeneratorClient templates={templates} />
        </section>

        <section className="rounded-3xl border border-[#e7e1d6] bg-white p-6">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h2 className="text-lg font-semibold">Generation history</h2>
            <form method="get" className="flex flex-wrap items-center gap-2 text-sm">
              <input
                name="touchpoint"
                defaultValue={touchpoint}
                placeholder="Touchpoint"
                className="rounded-full border border-[#efe7db] px-3 py-2 text-sm"
              />
              <input
                name="user_id"
                defaultValue={user_id}
                placeholder="User id"
                className="rounded-full border border-[#efe7db] px-3 py-2 text-sm"
              />
              <input
                name="start"
                type="date"
                defaultValue={start}
                className="rounded-full border border-[#efe7db] px-3 py-2 text-sm"
              />
              <input
                name="end"
                type="date"
                defaultValue={end}
                className="rounded-full border border-[#efe7db] px-3 py-2 text-sm"
              />
              <button className="rounded-full border border-[#efe7db] px-4 py-2 text-xs uppercase tracking-[0.2em]">
                Filter
              </button>
            </form>
          </div>

          <div className="mt-4 overflow-x-auto">
            <table className="w-full min-w-[900px] text-left text-sm">
              <thead className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">
                <tr>
                  <th className="py-2 pr-4">ID</th>
                  <th className="py-2 pr-4">Created</th>
                  <th className="py-2 pr-4">Touchpoint</th>
                  <th className="py-2 pr-4">User</th>
                  <th className="py-2 pr-4">Model</th>
                  <th className="py-2 pr-4">Status</th>
                  <th className="py-2">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#efe7db]">
                {items.map((row) => (
                  <tr key={row.id}>
                    <td className="py-3 pr-4 text-[#6b6257]">#{row.id}</td>
                    <td className="py-3 pr-4 text-[#6b6257]">{formatDateTime(row.created_at)}</td>
                    <td className="py-3 pr-4">{row.touchpoint || "—"}</td>
                    <td className="py-3 pr-4 text-[#6b6257]">
                      {row.user_name || (row.user_id ? `#${row.user_id}` : "—")}
                    </td>
                    <td className="py-3 pr-4 text-[#6b6257]">{row.model_override || "default"}</td>
                    <td className="py-3 pr-4 text-[#6b6257]">{row.status || "—"}</td>
                    <td className="py-3">
                      <a
                        href={`/admin/prompts/generator/${row.id}`}
                        className="rounded-full border border-[#efe7db] px-3 py-1 text-xs"
                      >
                        View
                      </a>
                    </td>
                  </tr>
                ))}
                {!items.length ? (
                  <tr>
                    <td colSpan={7} className="py-6 text-sm text-[#6b6257]">
                      No generations found yet.
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
