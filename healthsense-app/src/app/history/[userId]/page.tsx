import { getCoachingHistory, getUserStatus } from "@/lib/api";
import { PILLARS } from "@/lib/pillars";
import { Card, PageShell, SectionHeader } from "@/components/ui";
import TextScale from "@/components/TextScale";
import AppNav from "@/components/AppNav";

type PageProps = {
  params: Promise<{ userId: string }>;
};

const formatUk = (value?: string) => {
  if (!value) return "";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return new Intl.DateTimeFormat("en-GB", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "Europe/London",
  }).format(parsed);
};

const renderMessage = (text?: string) => {
  if (!text) return { __html: "" };
  const escaped = text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
  const withBold = escaped.replace(/\*(.+?)\*/g, "<strong>$1</strong>");
  const withBreaks = withBold.replace(/\n/g, "<br />");
  return { __html: withBreaks };
};

const weekToPillar = (weekNo?: number) => {
  if (!weekNo) return null;
  if (weekNo <= 3) return "Nutrition";
  if (weekNo <= 6) return "Recovery";
  if (weekNo <= 9) return "Training";
  if (weekNo <= 12) return "Resilience";
  return null;
};

export default async function HistoryPage(props: PageProps) {
  const { userId } = await props.params;
  const data = await getCoachingHistory(userId, 200);
  const status = await getUserStatus(userId);
  const textScale = status.coaching_preferences?.text_scale
    ? Number.parseFloat(status.coaching_preferences.text_scale)
    : undefined;
  const promptState = (status.prompt_state_override || "").toLowerCase();
  const promptBadge =
    promptState && promptState !== "live"
      ? `${promptState.charAt(0).toUpperCase()}${promptState.slice(1)} mode`
      : "";
  const items = data.items || [];
  const isKickoffItem = (item: (typeof items)[number]) => {
    const touchpoint = (item.touchpoint_type || "").toLowerCase();
    const text = `${item.full_text || ""} ${item.preview || ""}`.toLowerCase();
    return touchpoint.includes("kickoff") || text.includes("12-week programme kickoff");
  };
  const programmeItems = items.filter((item) => {
    if (item.week_no) return true;
    if (isKickoffItem(item)) return true;
    const touchpoint = (item.touchpoint_type || "").toLowerCase();
    if (touchpoint.includes("weekstart")) return true;
    return item.type === "podcast" || item.type === "prompt";
  });
  const seenKickoffItems = new Set<string>();
  const dedupedProgrammeItems = [...programmeItems]
    .sort((a, b) => {
      const aTs = a.ts ? new Date(a.ts).getTime() : 0;
      const bTs = b.ts ? new Date(b.ts).getTime() : 0;
      return bTs - aTs;
    })
    .filter((item) => {
      const kickoff = isKickoffItem(item);
      if (!kickoff) return true;
      const norm = `${item.full_text || item.preview || ""}`.replace(/\s+/g, " ").trim().toLowerCase();
      const day = (item.ts || "").slice(0, 10);
      const key = `kickoff|${day}|${item.audio_url || ""}|${norm}`;
      if (seenKickoffItems.has(key)) return false;
      seenKickoffItems.add(key);
      return true;
    });
  const programmeGroups = dedupedProgrammeItems.reduce<
    Array<{
      key: string;
      label: string;
      weekNo?: number;
      kickoff?: boolean;
      pillarLabel?: string;
      items: typeof programmeItems;
      latestTs?: string;
    }>
  >((acc, item) => {
    const kickoff = isKickoffItem(item);
    const weekNo = kickoff ? undefined : item.week_no ? Number(item.week_no) : undefined;
    const key = kickoff ? "programme-kickoff" : weekNo ? `week-${weekNo}` : `item-${item.id}`;
    let group = acc.find((entry) => entry.key === key);
    if (!group) {
      const pillarLabel = weekToPillar(weekNo);
      const label = kickoff
        ? "Programme kickoff"
        : weekNo
          ? `Week ${weekNo}${pillarLabel ? ` (${pillarLabel})` : ""}`
          : item.type || "Item";
      group = {
        key,
        label,
        weekNo,
        kickoff,
        pillarLabel: pillarLabel || undefined,
        items: [],
        latestTs: item.ts,
      };
      acc.push(group);
    }
    group.items.push(item);
    if (item.ts && (!group.latestTs || new Date(item.ts).getTime() > new Date(group.latestTs).getTime())) {
      group.latestTs = item.ts;
    }
    return acc;
  }, []);
  programmeGroups.forEach((group) => {
    group.items.sort((a, b) => {
      const aTs = a.ts ? new Date(a.ts).getTime() : 0;
      const bTs = b.ts ? new Date(b.ts).getTime() : 0;
      return aTs - bTs;
    });
  });
  programmeGroups.sort((a, b) => {
    if (a.kickoff && !b.kickoff) return -1;
    if (!a.kickoff && b.kickoff) return 1;
    if (a.weekNo != null && b.weekNo != null) return b.weekNo - a.weekNo;
    if (a.weekNo != null) return -1;
    if (b.weekNo != null) return 1;
    const aTs = a.latestTs ? new Date(a.latestTs).getTime() : 0;
    const bTs = b.latestTs ? new Date(b.latestTs).getTime() : 0;
    return bTs - aTs;
  });

  const groupedByDay = items.reduce<Record<string, typeof items>>((acc, item) => {
    const dayKey = formatUk(item.ts).split(",")[0] || "Unknown";
    if (!acc[dayKey]) acc[dayKey] = [];
    acc[dayKey].push(item);
    return acc;
  }, {});
  const orderedDays = Object.keys(groupedByDay).sort((a, b) => {
    const aItem = groupedByDay[a][0];
    const bItem = groupedByDay[b][0];
    const aTs = aItem?.ts ? new Date(aItem.ts).getTime() : 0;
    const bTs = bItem?.ts ? new Date(bItem.ts).getTime() : 0;
    return bTs - aTs;
  });
  const displayName = data.user?.display_name || "User";
  const displayFirstName = displayName.split(" ")[0];

  return (
    <PageShell>
      <TextScale defaultScale={textScale} />
      <AppNav userId={userId} promptBadge={promptBadge} />

      <SectionHeader
        eyebrow="Coaching history"
        title={<span className="text-xl">{`Your history, ${displayFirstName}`}</span>}
        subtitle="Latest activty first"
      />

      {programmeGroups.length ? (
        <section className="mb-6">
          <Card>
            <h2 className="text-xl">Programme history</h2>
            <div className="mt-4 space-y-3">
              {programmeGroups.map((group) => (
                <details key={group.key} className="rounded-2xl border border-[#efe7db] bg-[#fffaf0] p-3">
                  <summary className="flex cursor-pointer flex-wrap items-center justify-between gap-3 text-xs uppercase tracking-[0.2em] text-[#6b6257]">
                    <span className="flex flex-wrap items-center gap-2">
                      {group.kickoff ? (
                        <span>{group.label}</span>
                      ) : group.weekNo && group.pillarLabel ? (
                        (() => {
                          const meta = PILLARS.find(
                            (pillar) => pillar.label.toLowerCase() === group.pillarLabel?.toLowerCase()
                          );
                          return (
                            <>
                              <span>{`Week ${group.weekNo}`}</span>
                              <span className="inline-flex items-center gap-1">
                                <span>(</span>
                                {meta?.icon ? (
                                  <img src={meta.icon} alt="" className="h-[18px] w-[18px]" aria-hidden="true" />
                                ) : null}
                                <span style={{ color: meta?.accent || "#6b6257" }}>
                                  {group.pillarLabel}
                                </span>
                                <span>)</span>
                              </span>
                            </>
                          );
                        })()
                      ) : (
                        <span>{group.label}</span>
                      )}
                    </span>
                    <span className="text-[11px] normal-case tracking-normal text-[#6b6257]">
                      {formatUk(group.latestTs)}
                    </span>
                  </summary>
                  <div className="mt-3 space-y-3">
                    {group.items.map((item) => (
                      <div key={`programme-${group.key}-${item.id}`} className="rounded-2xl border border-[#efe7db] bg-white p-3">
                        <div className="flex flex-wrap items-center justify-between gap-3">
                          <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">{item.type}</p>
                          <p className="text-xs text-[#6b6257]">{formatUk(item.ts)}</p>
                        </div>
                        {item.preview ? (
                          <p
                            className="mt-2 text-sm text-[#3c332b]"
                            dangerouslySetInnerHTML={renderMessage(item.preview)}
                          />
                        ) : null}
                        {item.is_truncated && item.full_text ? (
                          <details className="mt-3 text-sm text-[#3c332b]">
                            <summary className="cursor-pointer text-xs uppercase tracking-[0.2em] text-[var(--accent)]">
                              Read full message
                            </summary>
                            <div
                              className="mt-3 rounded-2xl border border-[#efe7db] bg-white p-3 text-sm text-[#3c332b]"
                              dangerouslySetInnerHTML={renderMessage(item.full_text)}
                            />
                          </details>
                        ) : null}
                        {item.audio_url ? (
                          <div className="mt-4">
                            <a
                              className="rounded-full border border-[var(--accent)] bg-[var(--accent)] px-4 py-2 text-xs uppercase tracking-[0.2em] text-white"
                              href={item.audio_url}
                              target="_blank"
                              rel="noreferrer"
                            >
                              Play
                            </a>
                          </div>
                        ) : null}
                      </div>
                    ))}
                  </div>
                </details>
              ))}
            </div>
          </Card>
        </section>
      ) : null}

      <section className="space-y-4">
        {orderedDays.length ? (
          orderedDays.map((day) => (
            <Card key={day}>
              <details>
                <summary className="cursor-pointer text-xs uppercase tracking-[0.2em] text-[#6b6257]">
                  {day}
                </summary>
                <div className="mt-4 space-y-4">
                  {groupedByDay[day].map((item) => (
                    <div key={`${item.type}-${item.id}`} className="rounded-2xl border border-[#efe7db] bg-white p-4">
                      <div className="flex flex-wrap items-center justify-between gap-3">
                        <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">{item.type}</p>
                        <div className="text-xs text-[#6b6257]">{formatUk(item.ts)}</div>
                      </div>
                      {item.type === "dialog" ? (
                        <p className="mt-1 text-xs uppercase tracking-[0.2em] text-[#6b6257]">
                          {item.direction?.toLowerCase() === "inbound" ? "←" : "→"}
                        </p>
                      ) : null}
                      {item.preview ? (
                        <p
                          className="mt-3 text-sm text-[#3c332b]"
                          dangerouslySetInnerHTML={renderMessage(item.preview)}
                        />
                      ) : null}
                      {item.is_truncated && item.full_text ? (
                        <details className="mt-3 text-sm text-[#3c332b]">
                          <summary className="cursor-pointer text-xs uppercase tracking-[0.2em] text-[var(--accent)]">
                            Read full message
                          </summary>
                          <div
                            className="mt-3 rounded-2xl border border-[#efe7db] bg-white p-3 text-sm text-[#3c332b]"
                            dangerouslySetInnerHTML={renderMessage(item.full_text)}
                          />
                        </details>
                      ) : null}
                      {item.audio_url ? (
                        <div className="mt-4">
                          <a
                            className="rounded-full border border-[var(--accent)] bg-[var(--accent)] px-4 py-2 text-xs uppercase tracking-[0.2em] text-white"
                            href={item.audio_url}
                            target="_blank"
                            rel="noreferrer"
                          >
                            Play
                          </a>
                        </div>
                      ) : null}
                    </div>
                  ))}
                </div>
              </details>
            </Card>
          ))
        ) : (
          <Card>
            <p className="text-sm text-[#6b6257]">No coaching history yet.</p>
          </Card>
        )}
      </section>
    </PageShell>
  );
}
