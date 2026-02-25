import Link from "next/link";
import AdminNav from "@/components/AdminNav";

export const dynamic = "force-dynamic";

export default function TeamPage() {
  return (
    <main className="min-h-screen bg-[#f7f4ee] px-6 py-10 text-[#1e1b16]">
      <div className="mx-auto w-full max-w-6xl space-y-6">
        <AdminNav title="Team" subtitle="Manage internal team OKRs." />

        <section className="grid gap-4 md:grid-cols-1">
          <article className="rounded-3xl border border-[#e7e1d6] bg-white p-6">
            <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">OKR section</p>
            <h2 className="mt-3 text-xl font-semibold">Team OKRs</h2>
            <p className="mt-2 text-sm text-[#6b6257]">
              Review and update the team OKR workspace in the Expert System page.
            </p>
            <Link
              href="/admin/team/okrs"
              className="mt-4 inline-flex rounded-full border border-[var(--accent)] bg-[var(--accent)] px-4 py-2 text-xs uppercase tracking-[0.2em] text-white"
            >
              Open OKRs
            </Link>
          </article>
        </section>
      </div>
    </main>
  );
}
