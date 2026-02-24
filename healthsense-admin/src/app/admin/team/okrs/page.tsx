import Link from "next/link";
import AdminNav from "@/components/AdminNav";

export const dynamic = "force-dynamic";

const EXPERT_SYSTEM_DOC_NAME = "HealthSense — Expert System_ Roles & Q1 OKRs.html";
const EXPERT_SYSTEM_DOC = `/ExpertSystem/${encodeURIComponent(EXPERT_SYSTEM_DOC_NAME)}`;

export default function TeamOkrsPage() {
  return (
    <main className="min-h-screen bg-[#f7f4ee] px-6 py-10 text-[#1e1b16]">
      <div className="mx-auto w-full max-w-6xl space-y-6">
        <AdminNav title="Team OKRs" subtitle="Internal team OKR workspace." />

        <section className="rounded-3xl border border-[#e7e1d6] bg-white p-6">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Expert System</p>
              <p className="mt-1 text-sm text-[#6b6257]">
                This section opens the OKR block from the Expert System document.
              </p>
            </div>
            <div className="flex items-center gap-2">
              <Link
                href="/admin/team"
                className="rounded-full border border-[#efe7db] bg-[#fdfaf4] px-4 py-2 text-xs uppercase tracking-[0.2em]"
              >
                Back to team
              </Link>
              <a
                href={`${EXPERT_SYSTEM_DOC}#okrs`}
                target="_blank"
                rel="noreferrer"
                className="rounded-full border border-[var(--accent)] bg-[var(--accent)] px-4 py-2 text-xs uppercase tracking-[0.2em] text-white"
              >
                Open in new tab
              </a>
            </div>
          </div>

          <div className="mt-4 overflow-hidden rounded-2xl border border-[#efe7db]">
            <iframe
              title="Team OKRs"
              src={`${EXPERT_SYSTEM_DOC}#okrs`}
              className="h-[78vh] w-full bg-white"
            />
          </div>
        </section>
      </div>
    </main>
  );
}
