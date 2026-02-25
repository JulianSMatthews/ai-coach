import Link from "next/link";
import AdminNav from "@/components/AdminNav";

export const dynamic = "force-dynamic";

export default function HistoryLandingPage() {
  return (
    <main className="min-h-screen bg-[#f7f4ee] px-6 py-10 text-[#1e1b16]">
      <div className="mx-auto w-full max-w-5xl space-y-6">
        <AdminNav title="Activity" subtitle="Review prompts, coaching dialog, and scheduled runs." />

        <section className="grid gap-4 md:grid-cols-3">
          <Link
            href="/admin/prompts/history"
            className="rounded-3xl border border-[#e7e1d6] bg-white p-6 hover:border-[var(--accent)]"
          >
            <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Prompts</p>
            <h2 className="mt-2 text-lg font-semibold">Prompt history</h2>
            <p className="mt-2 text-sm text-[#6b6257]">
              Inspect assembled prompts and LLM responses by touchpoint, user, and date.
            </p>
          </Link>
          <Link
            href="/admin/history/touchpoints"
            className="rounded-3xl border border-[#e7e1d6] bg-white p-6 hover:border-[var(--accent)]"
          >
            <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Touchpoints</p>
            <h2 className="mt-2 text-lg font-semibold">Dialog history</h2>
            <p className="mt-2 text-sm text-[#6b6257]">
              Review coaching messages and touchpoints (including programme highlights).
            </p>
          </Link>
          <Link
            href="/admin/history/scheduled"
            className="rounded-3xl border border-[#e7e1d6] bg-white p-6 hover:border-[var(--accent)]"
          >
            <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Schedules</p>
            <h2 className="mt-2 text-lg font-semibold">Scheduled coaching</h2>
            <p className="mt-2 text-sm text-[#6b6257]">
              Inspect upcoming user coaching jobs, schedule source, and missing job rows.
            </p>
          </Link>
        </section>
      </div>
    </main>
  );
}
