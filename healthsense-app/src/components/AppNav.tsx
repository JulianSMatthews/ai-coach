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
      <span className="absolute text-[10px] font-semibold leading-none text-black">{score}</span>
    </span>
  );
}

function FlameBadge({ days }: { days: number }) {
  return (
    <span className="inline-flex h-11 items-center gap-1.5 rounded-full border border-[#efe7db] bg-[#fffdf9] px-3 text-black">
      <svg viewBox="0 0 24 24" className="h-4 w-4 shrink-0" aria-hidden="true">
        <path
          d="M12.5 3.5c.5 2.4-.7 3.8-2.1 5.4C8.8 10.3 7 12.4 7 15.1A5 5 0 0 0 12 20a5 5 0 0 0 5-4.9c0-1.8-.8-3.4-2-4.8-.4-.5-.9-1-1.3-1.6-.2.9-.7 1.7-1.5 2.4-.9-1-.8-2.5-.2-3.9.4-1 .5-1.9.5-3 0-.2 0-.4 0-.7Z"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.8"
          strokeLinejoin="round"
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
      <nav className="sticky top-0 z-50 mb-2 flex min-w-0 flex-col gap-1 px-0 py-0 text-xs text-[var(--text-secondary)] md:static md:mb-4 md:flex-row md:flex-nowrap md:items-center md:px-0 md:py-0">
        <div className="flex w-full items-center justify-between gap-2 md:w-auto md:justify-start">
          <div className="min-w-0">
            {greetingLabel ? (
              <p className="truncate text-base font-semibold leading-none text-[#1e1b16] sm:text-lg">
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
                className="inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-full border border-[#efe7db] bg-[#fffdf9]"
                aria-label="Open overall score"
              >
                <ScoreBadge score={resolvedOverallScore} />
              </button>
            ) : null}
            {resolvedInteractionDaysCount !== null ? <FlameBadge days={resolvedInteractionDaysCount} /> : null}
            <button
              type="button"
              className="inline-flex h-11 w-11 items-center justify-center rounded-full border border-[#efe7db] md:hidden"
              style={{ backgroundColor: "#fffdf9", color: "#000000" }}
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
            href={resolvedUserId ? `/assessment/${resolvedUserId}/chat` : "/login"}
            className="sr-only"
            aria-label="HealthSense home"
          >
            HealthSense home
          </Link>
        </div>
        <div className="hidden flex-wrap items-center gap-2 md:flex">
          {links.map((link) => (
            <Link
              key={link.label}
              className="rounded-full border border-[#efe7db] bg-[#fffdf9] px-3 py-1 text-sm text-black"
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
          style={{ backgroundColor: "#fffdf9", color: "#000000" }}
        >
          <div className="flex items-center justify-between">
            <Link
              href={resolvedUserId ? `/assessment/${resolvedUserId}/chat` : "/login"}
              className="sr-only"
              aria-label="HealthSense home"
            >
              HealthSense home
            </Link>
            <button
              type="button"
              className="inline-flex h-11 w-11 items-center justify-center rounded-full border border-[#efe7db]"
              style={{ backgroundColor: "#fffdf9", color: "#000000" }}
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

          <div className="mt-4 grid gap-2 text-[13px] text-black">
            {links.map((link) => (
              <Link
                key={link.label}
                href={link.href}
                onClick={() => setOpen(false)}
                className="rounded-[18px] border border-[#e7e1d6] px-4 py-2.5 text-sm text-black transition"
                style={{ backgroundColor: "#f6f1e7" }}
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
              style={{ backgroundColor: "#f6f1e7", borderColor: "#e7e1d6", color: "#000000" }}
            />
          </div>

        </div>
      </div>
    </>
  );
}
