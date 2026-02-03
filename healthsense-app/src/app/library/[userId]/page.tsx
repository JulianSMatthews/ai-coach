import { getLibraryContent, getUserStatus } from "@/lib/api";
import { Badge, PageShell, SectionHeader, Card } from "@/components/ui";
import CarouselDots from "@/components/CarouselDots";
import TextScale from "@/components/TextScale";
import LogoutButton from "@/components/LogoutButton";
import MobileTabBar from "@/components/MobileTabBar";

type PageProps = {
  params: Promise<{ userId: string }>;
};

const PILLARS = [
  { key: "nutrition", label: "Nutrition", note: "Fuel, hydration, and consistency." },
  { key: "recovery", label: "Recovery", note: "Sleep, recovery rituals, and restoration." },
  { key: "training", label: "Training", note: "Strength, mobility, and movement." },
  { key: "resilience", label: "Resilience", note: "Stress, mindset, and connection." },
  { key: "habit_forming", label: "Habit forming", note: "Routines, cues, and consistency." },
];

export default async function LibraryPage(props: PageProps) {
  const { userId } = await props.params;
  const status = await getUserStatus(userId);
  const library = await getLibraryContent(userId);
  const textScale = status.coaching_preferences?.text_scale
    ? Number.parseFloat(status.coaching_preferences.text_scale)
    : undefined;
  const itemsByPillar = library.items || {};
  const truncate = (text: string, limit = 220) =>
    text.length <= limit ? text : `${text.slice(0, Math.max(0, limit - 1))}…`;
  const promptState = (status.prompt_state_override || "").toLowerCase();
  const promptBadge =
    promptState && promptState !== "live"
      ? `${promptState.charAt(0).toUpperCase()}${promptState.slice(1)} mode`
      : "";
  return (
    <PageShell>
      <TextScale defaultScale={textScale} />
      <nav className="sticky top-0 z-10 -mx-6 mb-4 hidden flex-wrap items-center gap-2 border-y border-[#efe7db] bg-[#fbf7f0]/90 px-6 py-3 text-xs uppercase tracking-[0.2em] text-[#6b6257] backdrop-blur md:static md:mx-0 md:mb-6 md:flex md:border md:border-[#efe7db] md:rounded-full md:px-6 md:py-3">
        <a href={`/progress/${userId}`} className="flex items-center" aria-label="HealthSense home">
          <img src="/healthsense-logo.svg" alt="HealthSense" className="h-6 w-auto" />
        </a>
        <a className="rounded-full border border-[#efe7db] bg-white px-3 py-1" href={`/progress/${userId}`}>
          Home
        </a>
        <a className="rounded-full border border-[#efe7db] bg-white px-3 py-1" href={`/assessment/${userId}`}>
          Assessment
        </a>
        <a className="rounded-full border border-[#efe7db] bg-white px-3 py-1" href={`/library/${userId}`}>
          Library
        </a>
        <a className="rounded-full border border-[#efe7db] bg-white px-3 py-1" href={`/preferences/${userId}`}>
          Preferences
        </a>
        <a className="rounded-full border border-[#efe7db] bg-white px-3 py-1" href={`/history/${userId}`}>
          History
        </a>
        {promptBadge ? <Badge label={promptBadge} /> : null}
        <LogoutButton />
      </nav>
      <MobileTabBar userId={userId} active="library" />
      <SectionHeader
        eyebrow="Library"
        title="Pillar playbooks"
        subtitle="Curated content library by pillar"
      />
      <section
        id="library-carousel"
        className="flex flex-nowrap gap-6 overflow-x-auto pb-2 snap-x snap-mandatory scroll-smooth"
        style={{ scrollSnapType: "x mandatory", scrollPadding: "1.5rem" }}
      >
        {PILLARS.map((pillar) => {
          const pillarItems = itemsByPillar[pillar.key] || [];
          return (
          <Card
            key={pillar.key}
            className="min-w-full snap-start sm:min-w-[85%]"
            data-carousel-item
            style={{ scrollSnapStop: "always", scrollMarginLeft: "1.5rem" }}
          >
            <h2 className="text-xl">{pillar.label}</h2>
            <p className="mt-2 text-sm text-[#6b6257]">{pillar.note}</p>
            {pillarItems.length ? (
              <div className="mt-4 space-y-3">
                {pillarItems.map((item) => (
                  <div
                    key={item.id || `${pillar.key}-${item.title}`}
                    className="rounded-2xl border border-[#efe7db] bg-[#fffaf0] p-4 text-sm text-[#3c332b]"
                  >
                    {item.concept_code ? (
                      <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">
                        {item.concept_code}
                      </p>
                    ) : null}
                    <p className="mt-2 font-semibold text-[#1e1b16]">{item.title}</p>
                    <p className="mt-2 text-sm text-[#6b6257]">{truncate(item.body || "")}</p>
                    {item.body ? (
                      <details className="mt-3 text-sm text-[#3c332b]">
                        <summary className="cursor-pointer text-xs uppercase tracking-[0.2em] text-[var(--accent)]">
                          Read
                        </summary>
                        <div className="mt-2 rounded-xl border border-[#efe7db] bg-white/80 p-3 text-sm text-[#2f2a21]">
                          {item.body}
                        </div>
                      </details>
                    ) : null}
                    {item.podcast_url ? (
                      <div className="mt-3">
                        <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Listen</p>
                        <audio controls className="mt-2 w-full">
                          <source src={item.podcast_url} />
                        </audio>
                      </div>
                    ) : null}
                  </div>
                ))}
              </div>
            ) : (
              <div className="mt-4 rounded-2xl border border-[#efe7db] bg-[#fffaf0] p-4 text-sm text-[#3c332b]">
                <p className="font-semibold text-[#1e1b16]">Coming soon</p>
                <p className="mt-2">We’ll surface your tailored guidance and library content here.</p>
              </div>
            )}
          </Card>
          );
        })}
      </section>
      <CarouselDots containerId="library-carousel" count={PILLARS.length} />
    </PageShell>
  );
}
