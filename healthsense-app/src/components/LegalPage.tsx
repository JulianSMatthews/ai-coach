import AppNav from "@/components/AppNav";
import type { ReactNode } from "react";

type LegalPageProps = {
  eyebrow: string;
  title: string;
  subtitle: string;
  children: ReactNode;
};

export default function LegalPage({ title, subtitle, children }: LegalPageProps) {
  return (
    <main className="h-[100dvh] overflow-hidden bg-[var(--background)] px-4 pb-[max(1rem,env(safe-area-inset-bottom))] pt-[max(1rem,env(safe-area-inset-top))] text-[var(--foreground)] sm:px-6">
      <div className="mx-auto flex h-full w-full max-w-3xl flex-col gap-3">
        <AppNav />
        <article className="min-h-0 flex-1 space-y-4 overflow-y-auto overscroll-contain rounded-3xl border border-[var(--border)] bg-[var(--surface)] p-4 text-[15px] leading-6 text-[var(--text-secondary)] sm:p-5">
          <header className="space-y-2">
            <h1 className="text-[22px] leading-7 text-[var(--text-primary)]">{title}</h1>
            <p className="text-[15px] leading-6 text-[var(--text-secondary)]">{subtitle}</p>
          </header>
          {children}
        </article>
      </div>
    </main>
  );
}
