import HealthSenseMark from "@/components/HealthSenseMark";
import LegalLinksMenu from "@/components/LegalLinksMenu";
import type { ReactNode } from "react";

type LegalPageProps = {
  eyebrow: string;
  title: string;
  subtitle: string;
  children: ReactNode;
};

export default function LegalPage({ eyebrow, title, subtitle, children }: LegalPageProps) {
  return (
    <main className="min-h-[100dvh] overflow-x-hidden bg-[var(--background)] px-6 py-6 text-[var(--foreground)]">
      <div className="mx-auto w-full max-w-3xl space-y-6">
        <LegalLinksMenu />
        <header className="rounded-3xl border border-[var(--border)] bg-[var(--surface)] p-6 shadow-[0_30px_80px_-60px_var(--shadow-strong)]">
          <div className="flex items-center gap-3">
            <HealthSenseMark className="h-10 w-7" />
            <p className="text-xs uppercase tracking-[0.3em] text-[var(--text-secondary)]">{eyebrow}</p>
          </div>
          <h1 className="mt-5 text-3xl">{title}</h1>
          <p className="mt-2 text-sm text-[var(--text-secondary)]">{subtitle}</p>
        </header>

        <article className="space-y-5 rounded-3xl border border-[var(--border)] bg-[var(--surface)] p-6 text-sm text-[var(--text-secondary)]">
          {children}
        </article>
      </div>
    </main>
  );
}
