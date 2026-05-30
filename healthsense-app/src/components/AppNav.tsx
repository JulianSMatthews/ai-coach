"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import LogoutButton from "@/components/LogoutButton";
import { Badge } from "@/components/ui";

type AppNavProps = {
  userId?: string;
  promptBadge?: string;
};

export default function AppNav({ userId = "", promptBadge = "" }: AppNavProps) {
  const [open, setOpen] = useState(false);
  const resolvedUserId = String(userId || "").trim();
  const links: Array<{ label: string; href: string }> = [
    { label: "Home", href: resolvedUserId ? `/assessment/${resolvedUserId}/chat` : "/login" },
    ...(resolvedUserId
      ? [
          { label: "Preferences", href: `/preferences/${resolvedUserId}` },
          { label: "Wearables", href: `/preferences/${resolvedUserId}/wearables` },
        ]
      : []),
    { label: "Support", href: "/support" },
    { label: "Privacy", href: "/privacy" },
    { label: "Terms", href: "/terms" },
    { label: "Delete account", href: "/delete-account" },
  ];

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
      <nav className="sticky top-0 z-30 mb-2 flex min-w-0 flex-col gap-1 px-0 py-0 text-xs text-[var(--text-secondary)] md:static md:mb-4 md:flex-row md:flex-nowrap md:items-center md:px-0 md:py-0">
        <div className="flex w-full items-center justify-between md:w-auto md:justify-start">
          <Link href={resolvedUserId ? `/assessment/${resolvedUserId}/chat` : "/login"} className="flex items-baseline gap-1 text-white" aria-label="HealthSense home">
            <span className="text-sm font-semibold leading-none">HealthSense</span>
          </Link>
          <button
            type="button"
            className="flex h-8 w-8 items-center justify-center border border-black bg-black text-white md:hidden"
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
        <div className="hidden flex-wrap items-center gap-2 md:flex">
          {links.map((link) => (
            <Link
              key={link.label}
              className="border border-black bg-white px-3 py-1 text-sm text-black"
              href={link.href}
            >
              {link.label}
            </Link>
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
          className={`absolute right-0 top-0 h-full w-full max-w-sm transform overflow-y-auto overscroll-contain bg-white px-5 pb-[max(2rem,env(safe-area-inset-bottom))] pt-[max(1.5rem,env(safe-area-inset-top))] transition-transform duration-300 sm:px-6 ${
            open ? "translate-x-0" : "translate-x-full"
          }`}
        >
          <div className="flex items-center justify-between">
            <Link href={resolvedUserId ? `/assessment/${resolvedUserId}/chat` : "/login"} className="flex items-baseline gap-1 text-black" aria-label="HealthSense home">
              <span className="text-sm font-semibold leading-none">HealthSense</span>
            </Link>
            <button
              type="button"
              className="flex h-9 w-9 items-center justify-center border border-black bg-black text-white"
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

          <div className="mt-4 grid gap-2 text-[13px] text-[var(--text-primary)]">
            {links.map((link) => (
              <Link
                key={link.label}
                href={link.href}
                onClick={() => setOpen(false)}
                className="border border-black bg-white px-4 py-2.5 text-sm text-black"
              >
                {link.label}
              </Link>
            ))}
          </div>

          {promptBadge ? (
            <div className="mt-6">
              <Badge label={promptBadge} />
            </div>
          ) : null}

          <div className="mt-4">
            <LogoutButton className="w-full px-4 py-2.5 text-center" />
          </div>

        </div>
      </div>
    </>
  );
}
