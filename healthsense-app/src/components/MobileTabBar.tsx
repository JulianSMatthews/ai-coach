type MobileTabBarProps = {
  userId: string;
  active?: "home" | "assessment" | "library" | "preferences" | "history";
};

const items = [
  { key: "home", label: "Home", href: (userId: string) => `/progress/${userId}` },
  { key: "assessment", label: "Assessment", href: (userId: string) => `/assessment/${userId}` },
  { key: "library", label: "Library", href: (userId: string) => `/library/${userId}` },
  { key: "preferences", label: "Preferences", href: (userId: string) => `/preferences/${userId}` },
  { key: "history", label: "History", href: (userId: string) => `/history/${userId}` },
] as const;

export default function MobileTabBar({ userId, active }: MobileTabBarProps) {
  return (
    <nav className="fixed bottom-0 left-0 right-0 z-20 border-t border-[#efe7db] bg-[#fbf7f0]/95 backdrop-blur md:hidden">
      <div className="mx-auto flex max-w-3xl items-center justify-between px-4 py-3 text-[10px] uppercase tracking-[0.2em]">
        {items.map((item) => {
          const isActive = item.key === active;
          return (
            <a
              key={item.key}
              href={item.href(userId)}
              className={`flex flex-col items-center gap-1 ${isActive ? "text-[var(--accent)]" : "text-[#6b6257]"}`}
              aria-current={isActive ? "page" : undefined}
            >
              <span>{item.label}</span>
              {isActive ? <span className="h-1 w-4 rounded-full bg-[var(--accent)]" /> : null}
            </a>
          );
        })}
      </div>
    </nav>
  );
}
