type LegalFooterProps = {
  className?: string;
};

const links = [
  { href: "/privacy", label: "Privacy" },
  { href: "/terms", label: "Terms" },
  { href: "/support", label: "Support" },
  { href: "/delete-account", label: "Delete account" },
];

export default function LegalFooter({ className = "" }: LegalFooterProps) {
  return (
    <footer className={`text-center text-xs text-[var(--text-secondary)] ${className}`.trim()}>
      <div className="flex flex-wrap justify-center gap-x-4 gap-y-2">
        {links.map((link) => (
          <a key={link.href} href={link.href} className="underline-offset-4 hover:underline">
            {link.label}
          </a>
        ))}
      </div>
      <p className="mt-3">
        HealthSense provides wellbeing coaching and habit support. It is not a medical diagnosis or emergency service.
      </p>
    </footer>
  );
}
