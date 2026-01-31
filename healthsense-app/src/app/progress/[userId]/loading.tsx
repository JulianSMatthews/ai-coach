import { Card, PageShell, SectionHeader, StatPill } from "@/components/ui";

export default function LoadingProgress() {
  return (
    <PageShell>
      <SectionHeader eyebrow="Progress report" title="Weekly momentum" subtitle="Loading progress…" side={<StatPill label="Total KRs" value="…" accent="#b45309" bg="#fef3c7" border="#f5d0a0" />} />
      <section className="grid gap-6 lg:grid-cols-[1fr_1fr]">
        <Card>
          <div className="h-4 w-40 animate-pulse rounded bg-[#f1e9dd]" />
          <div className="mt-4 grid gap-3 sm:grid-cols-2">
            <div className="h-16 animate-pulse rounded-2xl bg-[#f1e9dd]" />
            <div className="h-16 animate-pulse rounded-2xl bg-[#f1e9dd]" />
            <div className="h-16 animate-pulse rounded-2xl bg-[#f1e9dd]" />
            <div className="h-16 animate-pulse rounded-2xl bg-[#f1e9dd]" />
          </div>
        </Card>
        <Card>
          <div className="h-4 w-32 animate-pulse rounded bg-[#f1e9dd]" />
          <div className="mt-4 space-y-2">
            <div className="h-10 w-full animate-pulse rounded-full bg-[#f1e9dd]" />
            <div className="h-10 w-full animate-pulse rounded-full bg-[#f1e9dd]" />
          </div>
        </Card>
      </section>
    </PageShell>
  );
}
