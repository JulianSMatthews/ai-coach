import { Card, PageShell } from "@/components/ui";

export default function LoadingAssessment() {
  return (
    <PageShell>
      <section className="grid gap-6 lg:grid-cols-[1.2fr_0.8fr]">
        <Card>
          <div className="h-5 w-48 animate-pulse rounded bg-[#f1e9dd]" />
          <div className="mt-4 space-y-3">
            <div className="h-3 w-full animate-pulse rounded bg-[#f1e9dd]" />
            <div className="h-3 w-4/5 animate-pulse rounded bg-[#f1e9dd]" />
            <div className="h-3 w-3/5 animate-pulse rounded bg-[#f1e9dd]" />
          </div>
        </Card>
        <Card>
          <div className="h-5 w-36 animate-pulse rounded bg-[#f1e9dd]" />
          <div className="mt-4 space-y-2">
            <div className="h-10 w-full animate-pulse rounded-full bg-[#f1e9dd]" />
            <div className="h-10 w-full animate-pulse rounded-full bg-[#f1e9dd]" />
          </div>
        </Card>
      </section>
    </PageShell>
  );
}
