type LegalLinksMenuProps = {
  className?: string;
};

const links = [
  { href: "/privacy", label: "Privacy" },
  { href: "/terms", label: "Terms" },
  { href: "/support", label: "Support" },
  { href: "/delete-account", label: "Delete account" },
];

export default function LegalLinksMenu({ className = "" }: LegalLinksMenuProps) {
  return (
    <details className={`group relative z-40 w-fit ${className}`.trim()}>
      <summary className="flex cursor-pointer list-none items-center gap-2 rounded-full border border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-xs uppercase tracking-[0.18em] text-[var(--text-secondary)] shadow-[0_14px_40px_-32px_var(--shadow-strong)]">
        About
        <svg
          viewBox="0 0 20 20"
          className="h-3.5 w-3.5 transition-transform group-open:rotate-180"
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
      <div className="absolute left-0 mt-2 w-[min(16rem,calc(100vw-2rem))] overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-2 text-sm text-[var(--text-primary)] shadow-[0_24px_70px_-42px_var(--shadow-strong)]">
        {links.map((link) => (
          <a key={link.href} href={link.href} className="block rounded-xl px-3 py-2 hover:bg-[var(--surface-muted)]">
            {link.label}
          </a>
        ))}
      </div>
    </details>
  );
}
