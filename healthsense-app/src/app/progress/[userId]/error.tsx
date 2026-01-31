"use client";

import { Card, PageShell } from "@/components/ui";

export default function ProgressError({ error }: { error: Error }) {
  return (
    <PageShell>
      <Card>
        <h2 className="text-xl">Something went wrong</h2>
        <p className="mt-2 text-sm text-[#6b6257]">We couldn’t load progress data.</p>
        <pre className="mt-4 rounded-2xl bg-[#fff3dc] p-4 text-xs text-[#3c332b]">{error.message}</pre>
      </Card>
    </PageShell>
  );
}
