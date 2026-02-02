import AdminNav from "@/components/AdminNav";
import { getScriptRun, getScriptRunLog } from "@/lib/api";

type ScriptRunPageProps = {
  params: Promise<{ runId: string }>;
};

export const dynamic = "force-dynamic";

export default async function ScriptRunPage({ params }: ScriptRunPageProps) {
  const resolved = await params;
  const runId = Number(resolved.runId);
  const run = await getScriptRun(runId);
  const log = await getScriptRunLog(runId, 120000);

  return (
    <main className="min-h-screen bg-[#f7f4ee] px-6 py-10 text-[#1e1b16]">
      <div className="mx-auto w-full max-w-5xl space-y-6">
        <AdminNav title={`Run #${runId}`} subtitle="Script output and status." />

        <section className="rounded-3xl border border-[#e7e1d6] bg-white p-6">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <a
              className="rounded-full border border-[var(--accent)] px-3 py-1 text-xs uppercase tracking-[0.2em] text-[var(--accent)]"
              href="/admin/scripts"
            >
              Back to scripts
            </a>
            <p className="text-xs text-[#6b6257]">Refresh this page to update status and log output.</p>
          </div>
          <div className="grid gap-4 md:grid-cols-3">
            <div>
              <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Type</p>
              <p className="mt-1 text-sm capitalize">{run.kind}</p>
            </div>
            <div>
              <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Status</p>
              <p className="mt-1 text-sm capitalize">{run.status}</p>
            </div>
            <div>
              <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Exit code</p>
              <p className="mt-1 text-sm">{run.exit_code ?? "—"}</p>
            </div>
            <div>
              <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Started</p>
              <p className="mt-1 text-sm">{run.started_at || "—"}</p>
            </div>
            <div>
              <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Finished</p>
              <p className="mt-1 text-sm">{run.finished_at || "—"}</p>
            </div>
            <div>
              <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">PID</p>
              <p className="mt-1 text-sm">{run.pid ?? "—"}</p>
            </div>
          </div>
        </section>

        <section className="rounded-3xl border border-[#e7e1d6] bg-white p-6">
          <h2 className="text-lg font-semibold">Log output</h2>
          <p className="mt-2 text-sm text-[#6b6257]">Tail of the log file from this run.</p>
          <pre className="mt-4 max-h-[70vh] overflow-auto rounded-2xl border border-[#efe7db] bg-[#faf6ef] p-4 text-xs text-[#3c332b]">
            {log.log || "No log output yet."}
          </pre>
        </section>
      </div>
    </main>
  );
}
