import Link from "next/link";
import AdminNav from "@/components/AdminNav";
import { listKbSnippets } from "@/lib/api";

type KbPageProps = {
  searchParams: Promise<{ q?: string; pillar?: string; concept?: string }>;
};

export const dynamic = "force-dynamic";

const PILLAR_OPTIONS = ["", "nutrition", "training", "resilience", "recovery", "goals"];

export default async function KbPage({ searchParams }: KbPageProps) {
  const resolvedSearchParams = await searchParams;
  const query = (resolvedSearchParams?.q || "").trim();
  const pillar = (resolvedSearchParams?.pillar || "").trim();
  const concept = (resolvedSearchParams?.concept || "").trim();
  const snippets = await listKbSnippets({
    q: query || undefined,
    pillar: pillar || undefined,
    concept: concept || undefined,
  });

  return (
    <main className="min-h-screen bg-[#f7f4ee] px-6 py-10 text-[#1e1b16]">
      <div className="mx-auto w-full max-w-6xl space-y-6">
        <AdminNav title="Knowledge base" subtitle="Curate snippets used in assessment prompts." />

        <section className="rounded-3xl border border-[#e7e1d6] bg-white p-6">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h2 className="text-lg font-semibold">Snippets</h2>
            <form method="get" className="flex flex-wrap items-center gap-2">
              <input
                name="q"
                defaultValue={query}
                placeholder="Search title or text"
                className="rounded-full border border-[#efe7db] px-3 py-2 text-sm"
              />
              <select
                name="pillar"
                defaultValue={pillar}
                className="rounded-full border border-[#efe7db] px-3 py-2 text-sm"
              >
                {PILLAR_OPTIONS.map((opt) => (
                  <option key={opt || "all"} value={opt}>
                    {opt ? opt.charAt(0).toUpperCase() + opt.slice(1) : "All pillars"}
                  </option>
                ))}
              </select>
              <input
                name="concept"
                defaultValue={concept}
                placeholder="Concept code"
                className="rounded-full border border-[#efe7db] px-3 py-2 text-sm"
              />
              <button
                type="submit"
                className="rounded-full border border-[#efe7db] px-4 py-2 text-xs uppercase tracking-[0.2em]"
              >
                Filter
              </button>
              <Link
                className="rounded-full border border-[var(--accent)] bg-[var(--accent)] px-4 py-2 text-xs uppercase tracking-[0.2em] text-white"
                href="/admin/kb/new"
              >
                New snippet
              </Link>
            </form>
          </div>

          <div className="mt-4 overflow-x-auto">
            <table className="w-full min-w-[1200px] text-left text-sm">
              <thead className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">
                <tr>
                  <th className="py-2 pr-6 whitespace-nowrap">Pillar</th>
                  <th className="py-2 pr-6 whitespace-nowrap">Concept</th>
                  <th className="py-2 pr-6 whitespace-nowrap">Title</th>
                  <th className="py-2 pr-6 whitespace-nowrap">Tags</th>
                  <th className="py-2 pr-6 whitespace-nowrap">Preview</th>
                  <th className="py-2 pr-6 whitespace-nowrap">Created</th>
                  <th className="py-2 whitespace-nowrap">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#efe7db]">
                {snippets.map((row) => (
                  <tr key={row.id}>
                    <td className="py-3 pr-6 whitespace-nowrap text-[#6b6257]">{row.pillar_key || "—"}</td>
                    <td className="py-3 pr-6 whitespace-nowrap text-[#6b6257]">{row.concept_code || "—"}</td>
                    <td className="py-3 pr-6 font-medium">{row.title || "Untitled"}</td>
                    <td className="py-3 pr-6 text-[#6b6257]">
                      {(row.tags || []).length ? row.tags?.join(", ") : "—"}
                    </td>
                    <td className="py-3 pr-6 text-[#6b6257]">{row.text_preview || "—"}</td>
                    <td className="py-3 pr-6 whitespace-nowrap text-[#6b6257]">
                      {row.created_at ? String(row.created_at).slice(0, 10) : "—"}
                    </td>
                    <td className="py-3 whitespace-nowrap">
                      <Link
                        className="rounded-full border border-[#efe7db] px-3 py-1 text-xs"
                        href={`/admin/kb/${row.id}`}
                      >
                        Edit
                      </Link>
                    </td>
                  </tr>
                ))}
                {!snippets.length ? (
                  <tr>
                    <td className="py-6 text-sm text-[#6b6257]" colSpan={7}>
                      No snippets found.
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
