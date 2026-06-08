import { cookies } from "next/headers";
import AppNav from "@/components/AppNav";
import type { ReactNode } from "react";

type LegalPageProps = {
  eyebrow: string;
  title: string;
  subtitle: string;
  children: ReactNode;
};

export default async function LegalPage({ title, subtitle, children }: LegalPageProps) {
  const cookieStore = await cookies();
  const userId = String(cookieStore.get("hs_user_id")?.value || "").trim();

  return (
    <main className="h-[100dvh] overflow-hidden bg-[var(--background)] px-4 pb-[max(1rem,env(safe-area-inset-bottom))] pt-[env(safe-area-inset-top)] text-[var(--foreground)] sm:px-6">
      <div className="mx-auto flex h-full w-full max-w-3xl flex-col gap-3">
        <AppNav userId={userId} />
        <article className="coach-scrollbar min-h-0 flex-1 space-y-5 overflow-y-auto overscroll-contain rounded-3xl border border-[var(--border)] bg-[var(--surface)] p-4 text-[19px] leading-8 text-[var(--text-secondary)] sm:p-5 [&_h2]:text-[21px] [&_h2]:leading-7 [&_p]:text-[19px] [&_p]:leading-8">
          <header className="space-y-2">
            <h1 className="text-[28px] leading-9 text-[var(--text-primary)]">{title}</h1>
            <p className="text-[19px] leading-8 text-[var(--text-secondary)]">{subtitle}</p>
          </header>
          {children}
        </article>
      </div>
    </main>
  );
}
