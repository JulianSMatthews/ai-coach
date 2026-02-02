import AdminNav from "@/components/AdminNav";
import { listLibraryContent } from "@/lib/api";

type PageProps = {
  searchParams: Promise<{ q?: string; pillar?: string; concept?: string; status?: string; source?: string }>;
};

export const dynamic = "force-dynamic";

const formatDate = (value?: string | null) => {
  if (!value) return "—";
  try {
    const dt = new Date(value);
    if (Number.isNaN(dt.getTime())) return "—";
    return dt.toLocaleDateString("en-GB", {
      day: "2-digit",
      month: "2-digit",
      year: "2-digit",
      timeZone: "Europe/London",
    });
  } catch {
    return "—";
  }
};

export default async function LibraryPage({ searchParams }: PageProps) {
  const params = await searchParams;
  const q = (params.q || "").trim();
  const pillar = (params.pillar || "").trim();
  const concept = (params.concept || "").trim();
  const status = (params.status || "").trim();
  const source = (params.source || "").trim();

  const items = await listLibraryContent({
    q: q || undefined,
    pillar: pillar || undefined,
    concept: concept || undefined,
    status: status || undefined,
    source: source || undefined,
    limit: 200,
  });

  return (
    <main className="min-h-screen bg-[#f7f4ee] px-6 py-10 text-[#1e1b16]">
      <div className="mx-auto w-full max-w-6xl space-y-6">
        <AdminNav title="Library content" subtitle="Generate, store, and publish content by pillar." />

        <section className="rounded-3xl border border-[#e7e1d6] bg-white p-6">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="text-lg font-semibold">Content library</h2>
              <p className="text-sm text-[#6b6257]">Generate content from content templates and publish to the app.</p>
            </div>
            <form method="get" className="flex flex-wrap items-center gap-2 text-sm">
              <input
                name="q"
                defaultValue={q}
                placeholder="Search title or text"
                className="rounded-full border border-[#efe7db] px-3 py-2 text-sm"
              />
              <input
                name="pillar"
                defaultValue={pillar}
                placeholder="pillar"
                className="rounded-full border border-[#efe7db] px-3 py-2 text-sm"
              />
              <input
                name="concept"
                defaultValue={concept}
                placeholder="concept"
                className="rounded-full border border-[#efe7db] px-3 py-2 text-sm"
              />
              <input
                name="source"
                defaultValue={source}
                placeholder="source"
                className="rounded-full border border-[#efe7db] px-3 py-2 text-sm"
              />
              <select
                name="status"
                defaultValue={status}
                className="rounded-full border border-[#efe7db] px-3 py-2 text-sm"
              >
                <option value="">Any status</option>
                <option value="draft">Draft</option>
                <option value="published">Published</option>
              </select>
              <button className="rounded-full border border-[#efe7db] px-4 py-2 text-xs uppercase tracking-[0.2em]">
                Filter
              </button>
              <a
                href="/admin/library/templates"
                className="rounded-full border border-[#efe7db] px-4 py-2 text-xs uppercase tracking-[0.2em]"
              >
                Templates
              </a>
              <a
                href="/admin/library/generator"
                className="rounded-full border border-[var(--accent)] bg-[var(--accent)] px-4 py-2 text-xs uppercase tracking-[0.2em] text-white"
              >
                Generate
              </a>
              <a
                href="/admin/library/content/new"
                className="rounded-full border border-[#efe7db] px-4 py-2 text-xs uppercase tracking-[0.2em]"
              >
                New content
              </a>
              <a
                href="/admin/library/settings"
                className="rounded-full border border-[#efe7db] px-4 py-2 text-xs uppercase tracking-[0.2em]"
              >
                Settings
              </a>
            </form>
          </div>

          <div className="mt-4 overflow-x-auto">
            <table className="w-full min-w-[900px] text-left text-sm">
              <thead className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">
                <tr>
                  <th className="py-2 pr-4">ID</th>
                  <th className="py-2 pr-4">Title</th>
                  <th className="py-2 pr-4">Pillar</th>
                  <th className="py-2 pr-4">Concept</th>
                  <th className="py-2 pr-4">Status</th>
                  <th className="py-2 pr-4">Source</th>
                  <th className="py-2 pr-4">Created</th>
                  <th className="py-2 pr-4">Preview</th>
                  <th className="py-2 pr-4">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#efe7db]">
                {items.map((row) => (
                  <tr key={row.id}>
                    <td className="py-3 pr-4 text-[#6b6257]">#{row.id}</td>
                    <td className="py-3 pr-4">{row.title || "—"}</td>
                    <td className="py-3 pr-4 text-[#6b6257]">{row.pillar_key || "—"}</td>
                    <td className="py-3 pr-4 text-[#6b6257]">{row.concept_code || "—"}</td>
                    <td className="py-3 pr-4 text-[#6b6257]">{row.status || "—"}</td>
                    <td className="py-3 pr-4 text-[#6b6257]">{row.source_type || "—"}</td>
                    <td className="py-3 pr-4 text-[#6b6257]">{formatDate(row.created_at)}</td>
                    <td className="py-3 pr-4 text-[#6b6257]">{row.text_preview || "—"}</td>
                    <td className="py-3 pr-4">
                      <a
                        className="rounded-full border border-[#efe7db] px-3 py-1 text-xs uppercase tracking-[0.2em]"
                        href={`/admin/library/content/${row.id}`}
                      >
                        Open
                      </a>
                    </td>
                  </tr>
                ))}
                {!items.length ? (
                  <tr>
                    <td colSpan={9} className="py-6 text-sm text-[#6b6257]">
                      No content yet. Generate and save content above.
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
