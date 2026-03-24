"use client";

import { useEffect, useState } from "react";
import LogoutButton from "@/components/LogoutButton";
import { Badge } from "@/components/ui";

type AppNavProps = {
  userId: string;
  promptBadge?: string;
};

const APP_LABEL = process.env.NODE_ENV === "development" ? "App (Develop)" : "App";

export default function AppNav({ userId, promptBadge = "" }: AppNavProps) {
  const [open, setOpen] = useState(false);
  const links: Array<{ label: string; href: string }> = [];

  useEffect(() => {
    if (!open) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previous;
    };
  }, [open]);

  return (
    <>
      <nav className="sticky top-0 z-30 -mx-6 mb-4 flex flex-col gap-2 border-y border-[var(--border)] bg-[var(--surface-soft)] px-6 py-3 text-xs uppercase tracking-[0.2em] text-[var(--text-secondary)] backdrop-blur md:static md:mx-0 md:mb-6 md:flex-row md:flex-nowrap md:items-center md:border md:border-[var(--border)] md:rounded-full md:px-6 md:py-3">
        <div className="flex w-full items-center justify-between md:w-auto md:justify-start">
          <a href={`/assessment/${userId}/chat`} className="flex items-center gap-2" aria-label="HealthSense home">
            <img
              src="/healthsense-logo.svg"
              alt="HealthSense"
              className="hs-brand-logo h-8 w-auto md:hidden"
            />
            <img
              src="/healthsense-mark.svg"
              alt="HealthSense"
              className="hs-brand-mark hidden h-8 w-auto md:block"
            />
            <span className="text-[11px] uppercase tracking-[0.22em] text-[var(--text-secondary)]">{APP_LABEL}</span>
          </a>
          <button
            type="button"
            className="flex h-9 w-9 items-center justify-center rounded-full border border-[var(--border)] bg-[var(--surface)] text-[var(--text-secondary)] md:hidden"
            aria-label="Open menu"
            aria-expanded={open}
            onClick={() => setOpen(true)}
          >
            <span className="sr-only">Open menu</span>
            <svg viewBox="0 0 24 24" className="h-5 w-5" aria-hidden="true">
              <path
                d="M4 7h16M4 12h16M4 17h16"
                stroke="currentColor"
                strokeWidth="1.5"
                strokeLinecap="round"
              />
            </svg>
          </button>
        </div>
        <div className="hidden flex-wrap items-center gap-2 md:flex md:flex-nowrap">
          {links.map((link) => (
            <a
              key={link.label}
              className="rounded-full border border-[var(--border)] bg-[var(--surface)] px-3 py-1"
              href={link.href}
            >
              {link.label}
            </a>
          ))}
          {promptBadge ? <Badge label={promptBadge} /> : null}
          <LogoutButton />
        </div>
      </nav>

      <div
        className={`fixed inset-0 z-50 transition ${open ? "pointer-events-auto" : "pointer-events-none"}`}
        aria-hidden={!open}
      >
        <div
          className={`absolute inset-0 bg-black/30 transition-opacity ${open ? "opacity-100" : "opacity-0"}`}
          onClick={() => setOpen(false)}
        />
        <div
          className={`absolute right-0 top-0 h-full w-full max-w-sm transform bg-[var(--surface-soft)] px-6 pb-8 pt-6 shadow-2xl transition-transform duration-300 ${
            open ? "translate-x-0" : "translate-x-full"
          }`}
        >
          <div className="flex items-center justify-between">
            <a href={`/assessment/${userId}/chat`} className="flex items-center gap-2" aria-label="HealthSense home">
              <img src="/healthsense-logo.svg" alt="HealthSense" className="hs-brand-logo h-9 w-auto" />
              <span className="text-[11px] uppercase tracking-[0.22em] text-[var(--text-secondary)]">{APP_LABEL}</span>
            </a>
            <button
              type="button"
              className="flex h-9 w-9 items-center justify-center rounded-full border border-[var(--border)] bg-[var(--surface)] text-[var(--text-secondary)]"
              aria-label="Close menu"
              onClick={() => setOpen(false)}
            >
              <span className="sr-only">Close menu</span>
              <svg viewBox="0 0 24 24" className="h-5 w-5" aria-hidden="true">
                <path
                  d="M4 7h16M4 12h16M4 17h16"
                  stroke="currentColor"
                  strokeWidth="1.5"
                  strokeLinecap="round"
                />
              </svg>
            </button>
          </div>

          <div className="mt-6 grid gap-3 text-[13px] uppercase tracking-[0.18em] text-[var(--text-primary)]">
            {links.map((link) => (
              <a
                key={link.label}
                href={link.href}
                onClick={() => setOpen(false)}
                className="rounded-full border border-[var(--border)] bg-[var(--surface)] px-5 py-3 text-sm"
              >
                {link.label}
              </a>
            ))}
          </div>

          {promptBadge ? (
            <div className="mt-6">
              <Badge label={promptBadge} />
            </div>
          ) : null}

          <div className="mt-6">
            <LogoutButton className="w-full text-center" />
          </div>
        </div>
      </div>
    </>
  );
}
