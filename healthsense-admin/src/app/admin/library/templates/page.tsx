import Link from "next/link";
import AdminNav from "@/components/AdminNav";
import { listContentPromptTemplates } from "@/lib/api";

type TemplatesPageProps = {
  searchParams: Promise<{ q?: string; pillar?: string; concept?: string }>;
};

export const dynamic = "force-dynamic";

export default async function ContentTemplatesPage({ searchParams }: TemplatesPageProps) {
  const params = await searchParams;
  const query = (params?.q || "").trim();
  const pillar = (params?.pillar || "").trim();
  const concept = (params?.concept || "").trim();
  const templates = await listContentPromptTemplates(undefined, query || undefined, pillar || undefined, concept || undefined);

  return (
    <main className="min-h-screen bg-[#f7f4ee] px-6 py-10 text-[#1e1b16]">
      <div className="mx-auto w-full max-w-6xl space-y-6">
        <AdminNav title="Content templates" subtitle="Manage content prompt templates for the library generator." />

        <section className="rounded-3xl border border-[#e7e1d6] bg-white p-6">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h2 className="text-lg font-semibold">Templates</h2>
            <form method="get" className="flex flex-wrap items-center gap-2">
              <input
                name="q"
                defaultValue={query}
                placeholder="Search key or label"
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
              <button className="rounded-full border border-[#efe7db] px-4 py-2 text-xs uppercase tracking-[0.2em]">
                Filter
              </button>
              <Link
                className="rounded-full border border-[#0f766e] bg-[#0f766e] px-4 py-2 text-xs uppercase tracking-[0.2em] text-white"
                href="/admin/library/templates/new"
              >
                New template
              </Link>
              <Link
                className="rounded-full border border-[#efe7db] px-4 py-2 text-xs uppercase tracking-[0.2em]"
                href="/admin/library/settings"
              >
                Settings
              </Link>
              <Link
                className="rounded-full border border-[#efe7db] px-4 py-2 text-xs uppercase tracking-[0.2em]"
                href="/admin/library"
              >
                Back to library
              </Link>
            </form>
          </div>

          <div className="mt-4 overflow-x-auto">
            <table className="w-full min-w-[900px] text-left text-sm">
              <thead className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">
                <tr>
                  <th className="py-2">Key</th>
                  <th className="py-2">Label</th>
                  <th className="py-2">Pillar</th>
                  <th className="py-2">Concept</th>
                  <th className="py-2">Version</th>
                  <th className="py-2">Active</th>
                  <th className="py-2">Updated</th>
                  <th className="py-2">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#efe7db]">
                {templates.map((row) => (
                  <tr key={row.id}>
                    <td className="py-3 font-medium">{row.template_key}</td>
                    <td className="py-3 text-[#6b6257]">{row.label || "—"}</td>
                    <td className="py-3 text-[#6b6257]">{row.pillar_key || "—"}</td>
                    <td className="py-3 text-[#6b6257]">{row.concept_code || "—"}</td>
                    <td className="py-3 text-[#6b6257]">{row.version ?? "—"}</td>
                    <td className="py-3 text-[#6b6257]">{row.is_active ? "yes" : "no"}</td>
                    <td className="py-3 text-[#6b6257]">
                      {row.updated_at ? String(row.updated_at).slice(0, 19).replace("T", " ") : "—"}
                    </td>
                    <td className="py-3">
                      <Link
                        className="rounded-full border border-[#efe7db] px-3 py-1 text-xs"
                        href={`/admin/library/templates/${row.id}`}
                      >
                        Open
                      </Link>
                    </td>
                  </tr>
                ))}
                {!templates.length ? (
                  <tr>
                    <td className="py-6 text-sm text-[#6b6257]" colSpan={8}>
                      No content templates found.
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
