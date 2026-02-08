import Link from "next/link";

type AdminNavProps = {
  title?: string;
  subtitle?: string;
};

export default function AdminNav({ title = "Admin", subtitle }: AdminNavProps) {
  return (
    <header className="rounded-3xl border border-[#e7e1d6] bg-white p-6 shadow-[0_20px_60px_-40px_rgba(30,27,22,0.4)]">
      <div className="flex items-center gap-3">
        <img src="/healthsense-logo.svg" alt="HealthSense" className="h-10 w-auto" />
        <span className="text-xs uppercase tracking-[0.3em] text-[#6b6257]">Admin</span>
      </div>
      <h1 className="mt-4 text-3xl">{title}</h1>
      {subtitle ? <p className="mt-2 text-sm text-[#6b6257]">{subtitle}</p> : null}
      <nav className="mt-4 flex flex-wrap gap-2 text-xs uppercase tracking-[0.2em] text-[#6b6257]">
        {[
          { href: "/admin", label: "Dashboard" },
          { href: "/admin/users", label: "Users" },
          { href: "/admin/messaging", label: "Messaging" },
          { href: "/admin/reporting", label: "Reporting" },
          { href: "/admin/prompts/templates", label: "Prompts" },
          { href: "/admin/history", label: "History" },
          { href: "/admin/library", label: "Library" },
          { href: "/admin/kb", label: "KB" },
          { href: "/admin/scripts", label: "Scripts" },
        ].map((item) => (
          <Link
            key={item.href}
            href={item.href}
            className="rounded-full border border-[#efe7db] bg-[#fdfaf4] px-3 py-1"
          >
            {item.label}
          </Link>
        ))}
      </nav>
    </header>
  );
}
