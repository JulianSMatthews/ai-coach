import Link from "next/link";
import AdminNav from "@/components/AdminNav";
import PromoteAllCard from "./PromoteAllCard";
import { listPromptTemplates, listPromptVersions } from "@/lib/api";

type TemplatesPageProps = {
  searchParams: Promise<{ q?: string; state?: string }>;
};

export const dynamic = "force-dynamic";

export default async function TemplatesPage({ searchParams }: TemplatesPageProps) {
  const resolvedSearchParams = await searchParams;
  const query = (resolvedSearchParams?.q || "").trim();
  const state = (resolvedSearchParams?.state || "develop").trim();
  const templates = await listPromptTemplates(state || "develop", query || undefined);
  const versionLogs = await listPromptVersions(12);

  return (
    <main className="min-h-screen bg-[#f7f4ee] px-6 py-10 text-[#1e1b16]">
      <div className="mx-auto w-full max-w-6xl space-y-6">
        <AdminNav title="Prompt templates" subtitle="Edit develop templates and promote to beta or live." />

        <section className="rounded-3xl border border-[#e7e1d6] bg-white p-6">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h2 className="text-lg font-semibold">Templates</h2>
            <form method="get" className="flex flex-wrap items-center gap-2">
              <input
                name="q"
                defaultValue={query}
                placeholder="Search touchpoint"
                className="rounded-full border border-[#efe7db] px-3 py-2 text-sm"
              />
              <select
                name="state"
                defaultValue={state || "develop"}
                className="rounded-full border border-[#efe7db] px-3 py-2 text-sm"
              >
                <option value="develop">Develop</option>
                <option value="beta">Beta</option>
                <option value="live">Live</option>
              </select>
              <button
                type="submit"
                className="rounded-full border border-[#efe7db] px-4 py-2 text-xs uppercase tracking-[0.2em]"
              >
                Filter
              </button>
              <Link
                className="rounded-full border border-[var(--accent)] bg-[var(--accent)] px-4 py-2 text-xs uppercase tracking-[0.2em] text-white"
                href="/admin/prompts/templates/new"
              >
                New template
              </Link>
              <Link
                className="rounded-full border border-[#efe7db] px-4 py-2 text-xs uppercase tracking-[0.2em]"
                href="/admin/prompts/test"
              >
                Test prompt
              </Link>
              <Link
                className="rounded-full border border-[#efe7db] px-4 py-2 text-xs uppercase tracking-[0.2em]"
                href="/admin/prompts/settings"
              >
                Settings
              </Link>
              <Link
                className="rounded-full border border-[#efe7db] px-4 py-2 text-xs uppercase tracking-[0.2em]"
                href="/admin/prompts/history"
              >
                History
              </Link>
            </form>
          </div>

          <div className="mt-4 overflow-x-auto">
            <table className="w-full min-w-[860px] text-left text-sm">
              <thead className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">
                <tr>
                  <th className="py-2">Touchpoint</th>
                  <th className="py-2">State</th>
                  <th className="py-2">Version</th>
                  <th className="py-2">Active</th>
                  <th className="py-2">Updated</th>
                  <th className="py-2">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#efe7db]">
                {templates.map((row) => (
                  <tr key={row.id}>
                    <td className="py-3 font-medium">{row.touchpoint}</td>
                    <td className="py-3 text-[#6b6257]">{row.state || "—"}</td>
                    <td className="py-3 text-[#6b6257]">{row.version ?? "—"}</td>
                    <td className="py-3 text-[#6b6257]">{row.is_active ? "yes" : "no"}</td>
                    <td className="py-3 text-[#6b6257]">
                      {row.updated_at ? String(row.updated_at).slice(0, 19).replace("T", " ") : "—"}
                    </td>
                    <td className="py-3">
                      <Link
                        className="rounded-full border border-[#efe7db] px-3 py-1 text-xs"
                        href={`/admin/prompts/templates/${row.id}`}
                      >
                        Open
                      </Link>
                    </td>
                  </tr>
                ))}
                {!templates.length ? (
                  <tr>
                    <td className="py-6 text-sm text-[#6b6257]" colSpan={6}>
                      No templates found.
                    </td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
        </section>

        <PromoteAllCard />

        <section className="rounded-3xl border border-[#e7e1d6] bg-white p-6">
          <h2 className="text-lg font-semibold">Version history</h2>
          <p className="mt-2 text-sm text-[#6b6257]">Latest promote-all actions.</p>
          <div className="mt-4 overflow-x-auto">
            <table className="w-full min-w-[520px] text-left text-sm">
              <thead className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">
                <tr>
                  <th className="py-2">When</th>
                  <th className="py-2">Version</th>
                  <th className="py-2">Path</th>
                  <th className="py-2">Note</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#efe7db]">
                {versionLogs.map((log) => (
                  <tr key={log.id}>
                    <td className="py-3 text-[#6b6257]">
                      {log.created_at ? String(log.created_at).slice(0, 19).replace("T", " ") : "—"}
                    </td>
                    <td className="py-3 text-[#6b6257]">{log.version ?? "—"}</td>
                    <td className="py-3 text-[#6b6257]">
                      {log.from_state} → {log.to_state}
                    </td>
                    <td className="py-3 text-[#6b6257]">{log.note || "—"}</td>
                  </tr>
                ))}
                {!versionLogs.length ? (
                  <tr>
                    <td className="py-6 text-sm text-[#6b6257]" colSpan={4}>
                      No version history yet.
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
