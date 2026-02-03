import React from "react";
import SessionBootstrap from "./SessionBootstrap";

export function PageShell({ children }: { children: React.ReactNode }) {
  return (
    <main className="min-h-screen bg-white px-6 py-10 text-[#1e1b16]">
      <SessionBootstrap />
      <div className="mx-auto max-w-6xl space-y-10">{children}</div>
    </main>
  );
}

export function Card({
  children,
  className = "",
  ...props
}: React.HTMLAttributes<HTMLDivElement> & {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={`rounded-3xl border border-[#e7e1d6] bg-white p-6 ${className}`} {...props}>
      {children}
    </div>
  );
}

export function SectionHeader({
  eyebrow,
  title,
  subtitle,
  side,
  brandMark,
}: {
  eyebrow?: React.ReactNode;
  title: React.ReactNode;
  subtitle?: string;
  side?: React.ReactNode;
  brandMark?: React.ReactNode;
}) {
  return (
    <div className="rounded-3xl border border-[#e7e1d6] bg-white/70 p-8 shadow-[0_30px_80px_-60px_rgba(30,27,22,0.5)] backdrop-blur">
      <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
        <div className="space-y-2">
          {brandMark ? <div className="flex items-center gap-3">{brandMark}</div> : null}
          {eyebrow ? (
            typeof eyebrow === "string" ? (
              <p className="text-xs uppercase tracking-[0.3em] text-[#6b6257]">{eyebrow}</p>
            ) : (
              eyebrow
            )
          ) : null}
          <h1 className="text-3xl md:text-4xl">{title}</h1>
          {subtitle ? <p className="text-sm text-[#6b6257]">{subtitle}</p> : null}
        </div>
        {side}
      </div>
    </div>
  );
}

export function Badge({ label }: { label: string }) {
  return (
    <span className="rounded-full border border-[#f5d0a0] bg-[#fff3dc] px-3 py-1 text-xs">
      {label}
    </span>
  );
}

export function StatPill({
  label,
  value,
  accent = "var(--accent)",
  bg = "#ecfdf7",
  border = "#d7efe7",
}: {
  label: string;
  value: string | number;
  accent?: string;
  bg?: string;
  border?: string;
}) {
  return (
    <div className="rounded-2xl border px-6 py-4 text-center" style={{ background: bg, borderColor: border }}>
      <p className="text-xs uppercase tracking-[0.3em]" style={{ color: accent }}>
        {label}
      </p>
      <p className="text-3xl font-semibold">{value}</p>
    </div>
  );
}

export function ProgressBar({
  value,
  max = 100,
  tone = "var(--accent)",
}: {
  value: number;
  max?: number;
  tone?: string;
}) {
  const pct = Math.max(0, Math.min(100, (value / max) * 100));
  return (
    <div className="mt-3 h-2 overflow-hidden rounded-full bg-[#f1e9dd]">
      <div className="h-full rounded-full" style={{ width: `${pct}%`, background: tone }} />
    </div>
  );
}

export function ScoreRing({
  value,
  max = 100,
  tone = "var(--accent)",
}: {
  value: number;
  max?: number;
  tone?: string;
}) {
  const pct = Math.max(0, Math.min(1, value / max));
  const size = 84;
  const stroke = 8;
  const radius = (size - stroke) / 2;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference * (1 - pct);
  return (
    <div className="relative flex h-[84px] w-[84px] items-center justify-center">
      <svg width={size} height={size} className="rotate-[-90deg]">
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          stroke="#efe7db"
          strokeWidth={stroke}
          fill="none"
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          stroke={tone}
          strokeWidth={stroke}
          fill="none"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          strokeLinecap="round"
        />
      </svg>
      <span className="absolute text-lg font-semibold">{value}</span>
    </div>
  );
}
