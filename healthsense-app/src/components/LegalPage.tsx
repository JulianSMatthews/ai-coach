import HealthSenseMark from "@/components/HealthSenseMark";
import AboutCloseButton from "@/components/AboutCloseButton";
import AboutMenu from "@/components/AboutMenu";
import type { ReactNode } from "react";

type LegalPageProps = {
  eyebrow: string;
  title: string;
  subtitle: string;
  children: ReactNode;
};

export default function LegalPage({ eyebrow, title, subtitle, children }: LegalPageProps) {
  return (
    <main className="h-[100dvh] overflow-hidden bg-[var(--background)] px-4 pb-[max(1rem,env(safe-area-inset-bottom))] pt-[max(1rem,env(safe-area-inset-top))] text-[var(--foreground)] sm:px-6">
      <div className="mx-auto flex h-full w-full max-w-3xl flex-col gap-3">
        <div className="flex shrink-0 items-center justify-between gap-3">
          <AboutMenu buttonClassName="rounded-full border border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-[13px] font-semibold text-[var(--text-secondary)] shadow-[0_10px_24px_-18px_var(--shadow-strong)]" />
          <AboutCloseButton />
        </div>

        <header className="shrink-0 rounded-3xl border border-[var(--border)] bg-[var(--surface)] p-4 shadow-[0_30px_80px_-60px_var(--shadow-strong)] sm:p-5">
          <div className="flex items-center gap-3">
            <HealthSenseMark className="h-8 w-6" />
            <p className="text-[10px] uppercase tracking-[0.24em] text-[var(--text-secondary)]">{eyebrow}</p>
          </div>
          <h1 className="mt-4 text-[22px] leading-7">{title}</h1>
          <p className="mt-2 text-[15px] leading-6 text-[var(--text-secondary)]">{subtitle}</p>
        </header>

        <article className="min-h-0 flex-1 space-y-4 overflow-y-auto overscroll-contain rounded-3xl border border-[var(--border)] bg-[var(--surface)] p-4 text-[15px] leading-6 text-[var(--text-secondary)] sm:p-5">
          {children}
        </article>
      </div>
    </main>
  );
}
