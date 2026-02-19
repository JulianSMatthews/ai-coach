import type { CSSProperties } from "react";
import { getLibraryContent, getUserStatus } from "@/lib/api";
import { PILLARS } from "@/lib/pillars";
import { Badge, PageShell, SectionHeader, Card } from "@/components/ui";
import CarouselDots from "@/components/CarouselDots";
import TextScale from "@/components/TextScale";
import AppNav from "@/components/AppNav";
import TrackedAudio from "@/components/TrackedAudio";

type PageProps = {
  params: Promise<{ userId: string }>;
};

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
      <AppNav userId={userId} promptBadge={promptBadge} />
      <SectionHeader
        eyebrow="Library"
        title="Pillar playbooks"
        subtitle="Curated content library by pillar"
      />
      <section
        id="library-carousel"
        className="flex flex-nowrap gap-6 overflow-x-auto pb-2 snap-x snap-mandatory scroll-smooth"
        style={{ scrollSnapType: "x mandatory" }}
      >
        {PILLARS.map((pillar) => {
          const pillarItems = itemsByPillar[pillar.key] || [];
          const cardStyle = {
            borderColor: pillar.border,
            background: pillar.bg,
            "--accent": pillar.accent,
          } as CSSProperties;
          return (
            <Card
              key={pillar.key}
              className="min-w-full snap-start sm:min-w-[85%]"
              data-carousel-item
              style={{
              scrollSnapStop: "always",
              ...cardStyle,
            }}
            >
            <div>
              <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Pillar</p>
              <h2 className="mt-1 flex items-center gap-1 text-xl">
                {pillar.icon ? (
                  <img src={pillar.icon} alt="" className="h-[23px] w-[23px]" aria-hidden="true" />
                ) : null}
                {pillar.label}
              </h2>
            </div>
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
                      <p className="mt-2 whitespace-pre-wrap text-sm text-[#6b6257]">{truncate(item.body || "")}</p>
                      {item.body ? (
                        <details className="mt-3 text-sm text-[#3c332b]">
                          <summary className="cursor-pointer text-xs uppercase tracking-[0.2em] text-[var(--accent)]">
                            Read
                          </summary>
                          <div className="mt-2 whitespace-pre-wrap rounded-xl border border-[#efe7db] bg-white/80 p-3 text-sm text-[#2f2a21]">
                            {item.body}
                          </div>
                        </details>
                      ) : null}
                      {item.podcast_url ? (
                        <div className="mt-3">
                          <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Listen</p>
                          <TrackedAudio
                            userId={userId}
                            src={item.podcast_url}
                            surface="library"
                            podcastId={item.id || `${item.pillar_key || pillar.key}:${item.concept_code || item.title || "podcast"}`}
                            className="mt-2 w-full"
                          />
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
