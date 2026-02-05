import { Card, PageShell } from "@/components/ui";

export default function LoadingProgress() {
  return (
    <PageShell>
      <section className="grid gap-6 lg:grid-cols-[1fr_1fr]">
        <Card>
          <div className="h-5 w-48 animate-pulse rounded bg-[#f1e9dd]" />
          <div className="mt-4 grid gap-3 sm:grid-cols-2">
            <div className="h-16 animate-pulse rounded-2xl bg-[#f1e9dd]" />
            <div className="h-16 animate-pulse rounded-2xl bg-[#f1e9dd]" />
            <div className="h-16 animate-pulse rounded-2xl bg-[#f1e9dd]" />
            <div className="h-16 animate-pulse rounded-2xl bg-[#f1e9dd]" />
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
