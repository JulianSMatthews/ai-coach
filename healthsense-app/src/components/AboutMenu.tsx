"use client";

import type { MouseEvent } from "react";

type AboutMenuProps = {
  className?: string;
  buttonClassName?: string;
  menuClassName?: string;
  align?: "left" | "right";
};

const links = [
  { href: "/privacy", label: "Privacy" },
  { href: "/terms", label: "Terms" },
  { href: "/support", label: "Support" },
  { href: "/delete-account", label: "Delete account" },
];

const defaultButtonClassName =
  "rounded-full border border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-[13px] font-semibold text-[var(--text-secondary)] shadow-[0_10px_24px_-18px_var(--shadow-strong)]";

function isSafeReturnPath(value: string): boolean {
  return Boolean(value && value.startsWith("/") && !value.startsWith("//") && !value.startsWith("/api"));
}

function resolveReturnTo(): string {
  const params = new URLSearchParams(window.location.search);
  const existingReturnTo = String(params.get("returnTo") || "").trim();
  const currentPath = `${window.location.pathname}${window.location.search || ""}`;
  return isSafeReturnPath(existingReturnTo) ? existingReturnTo : currentPath;
}

export default function AboutMenu({
  className = "",
  buttonClassName = defaultButtonClassName,
  menuClassName = "",
  align = "left",
}: AboutMenuProps) {
  const menuPositionClassName = align === "right" ? "right-0" : "left-0";
  const navigateWithReturn = (event: MouseEvent<HTMLAnchorElement>, href: string) => {
    const returnTo = resolveReturnTo();
    if (!returnTo) return;
    event.preventDefault();
    window.location.assign(`${href}?returnTo=${encodeURIComponent(returnTo)}`);
  };

  return (
    <details className={`group relative z-40 w-fit ${className}`.trim()}>
      <summary className={`flex cursor-pointer list-none items-center gap-2 ${buttonClassName}`.trim()}>
        about
        <svg
          viewBox="0 0 20 20"
          className="h-4 w-4 transition-transform group-open:rotate-180"
          aria-hidden="true"
        >
          <path
            d="M5 8l5 5 5-5"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.7"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </summary>
      <div
        className={`absolute ${menuPositionClassName} mt-2 w-[min(16rem,calc(100vw-2rem))] overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-2 text-[15px] text-[var(--text-primary)] shadow-[0_24px_70px_-42px_var(--shadow-strong)] ${menuClassName}`.trim()}
      >
        {links.map((link) => (
          <a
            key={link.href}
            href={link.href}
            onClick={(event) => navigateWithReturn(event, link.href)}
            className="block rounded-xl px-3 py-2 hover:bg-[var(--surface-muted)]"
          >
            {link.label}
          </a>
        ))}
      </div>
    </details>
  );
}
