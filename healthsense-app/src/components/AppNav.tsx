"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import LogoutButton from "@/components/LogoutButton";
import { Badge } from "@/components/ui";

type AppNavProps = {
  userId?: string;
  promptBadge?: string;
  overallScore?: number | null;
  interactionDaysCount?: number | null;
  userFirstName?: string | null;
};

function ScoreBadge({ score }: { score: number }) {
  const pct = Math.max(0, Math.min(1, score / 100));
  const size = 34;
  const stroke = 4.5;
  const radius = (size - stroke) / 2;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference * (1 - pct);
  return (
    <span className="relative flex h-9 w-9 items-center justify-center">
      <svg width={size} height={size} className="rotate-[-90deg]" aria-hidden="true">
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          stroke="rgba(197,72,23,0.18)"
          strokeWidth={stroke}
          fill="none"
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          stroke="#c54817"
          strokeWidth={stroke}
          fill="none"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          strokeLinecap="round"
          />
        </svg>
      <span className="absolute text-[10px] font-semibold leading-none text-[var(--chrome-text)]">{score}</span>
    </span>
  );
}

function FlameBadge({ days }: { days: number }) {
  return (
    <span className="inline-flex h-11 items-center gap-1.5 rounded-full border border-[var(--chrome-border)] bg-[var(--chrome)] px-3 text-[var(--chrome-text)]">
      <svg viewBox="0 0 24 24" className="h-4.5 w-4.5 shrink-0" aria-hidden="true">
        <path
          d="M12 3.2c.38 1.54-.25 2.55-1.05 3.46C9.86 7.69 8.7 9 8.7 10.8c0 1.76 1.06 3.02 2.05 3.73.24-1.12.24-2.17.1-3.04.94.86 2.05 2.22 2.05 4.02A3.98 3.98 0 0 1 9 19.5a4.12 4.12 0 0 1-4.1-4.1c0-1.98.97-3.62 2.4-5.06 1.03-1.05 2.2-2.08 2.94-3.18.42-.62.74-1.3.85-2.28.27.15.58.55.91 1.3Z"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.55"
          strokeLinejoin="round"
          strokeLinecap="round"
        />
      </svg>
      <span className="min-w-[0.9rem] text-sm font-semibold leading-none">{days}</span>
    </span>
  );
}

export default function AppNav({
  userId = "",
  promptBadge = "",
  overallScore = null,
  interactionDaysCount = null,
  userFirstName = "",
}: AppNavProps) {
  const [open, setOpen] = useState(false);
  const resolvedUserId = String(userId || "").trim();
  const resolvedOverallScore = Number.isFinite(Number(overallScore)) ? Math.max(0, Math.min(100, Math.round(Number(overallScore)))) : null;
  const resolvedInteractionDaysCount = Number.isFinite(Number(interactionDaysCount))
    ? Math.max(0, Math.round(Number(interactionDaysCount)))
    : null;
  const resolvedFirstName = String(userFirstName || "").trim();
  const greetingLabel = resolvedFirstName ? `Hi ${resolvedFirstName}` : "";
  const links: Array<{ label: string; href: string }> = [
    { label: "Home", href: resolvedUserId ? "/" : "/login" },
    ...(resolvedUserId
      ? [
          { label: "Preferences", href: `/preferences/${resolvedUserId}` },
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
      <nav className="sticky top-0 z-50 mb-2 flex min-h-[4.25rem] min-w-0 flex-col justify-center gap-1 px-0 py-0 text-xs text-[var(--text-secondary)] md:static md:mb-4 md:min-h-0 md:flex-row md:flex-nowrap md:items-center md:justify-start md:px-0 md:py-0">
        <div className="flex w-full items-center justify-between gap-2 md:w-auto md:justify-start">
          <div className="min-w-0">
            {greetingLabel ? (
              <p className="truncate text-base font-semibold leading-none text-[var(--text-primary)] sm:text-lg">
                {greetingLabel}
              </p>
            ) : (
              <div className="h-5 w-16" aria-hidden="true" />
            )}
          </div>
          <div className="flex shrink-0 items-center gap-2">
            {resolvedOverallScore !== null ? (
              <button
                type="button"
                onClick={() => {
                  if (typeof window !== "undefined") {
                    window.dispatchEvent(new CustomEvent("healthsense-open-objectives"));
                  }
                }}
                className="inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-full border border-[var(--chrome-border)] bg-[var(--chrome)]"
                aria-label="Open overall score"
              >
                <ScoreBadge score={resolvedOverallScore} />
              </button>
            ) : null}
            {resolvedInteractionDaysCount !== null ? <FlameBadge days={resolvedInteractionDaysCount} /> : null}
            <button
              type="button"
              className="inline-flex h-11 w-11 items-center justify-center rounded-full border border-[var(--chrome-border)] bg-[var(--chrome)] text-[var(--chrome-text)] md:hidden"
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
          <Link
            href={resolvedUserId ? "/" : "/login"}
            className="sr-only"
            aria-label="CoachSense home"
          >
            CoachSense home
          </Link>
        </div>
        <div className="hidden flex-wrap items-center gap-2 md:flex">
          {links.map((link) => (
            <Link
              key={link.label}
              className="rounded-full border border-[var(--chrome-border)] bg-[var(--chrome)] px-3 py-1 text-sm text-[var(--chrome-text)]"
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
          className={`absolute right-0 top-0 h-full w-full max-w-sm transform overflow-y-auto overscroll-contain px-5 pb-[max(2rem,env(safe-area-inset-bottom))] pt-[max(1.5rem,env(safe-area-inset-top))] transition-transform duration-300 sm:px-6 ${
            open ? "translate-x-0" : "translate-x-full"
          }`}
          style={{ backgroundColor: "var(--chrome)", color: "var(--chrome-text)" }}
        >
          <div className="flex items-center justify-between">
            <Link
              href={resolvedUserId ? "/" : "/login"}
              className="sr-only"
              aria-label="CoachSense home"
            >
              CoachSense home
            </Link>
            <button
              type="button"
              className="inline-flex h-11 w-11 items-center justify-center rounded-full border border-[var(--chrome-border)] bg-[var(--chrome)] text-[var(--chrome-text)]"
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

          <div className="mt-4 grid gap-2 text-[13px] text-[var(--chrome-text)]">
            {links.map((link) => (
              <Link
                key={link.label}
                href={link.href}
                onClick={() => setOpen(false)}
                className="rounded-[18px] border border-[var(--chrome-border)] px-4 py-2.5 text-sm text-[var(--chrome-text)] transition"
                style={{ backgroundColor: "var(--chrome-soft)" }}
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
            <LogoutButton
              className="w-full rounded-[18px] px-4 py-2.5 text-center"
              style={{ backgroundColor: "var(--chrome-soft)", borderColor: "var(--chrome-border)", color: "var(--chrome-text)" }}
            />
          </div>

        </div>
      </div>
    </>
  );
}
