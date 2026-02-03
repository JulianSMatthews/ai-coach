import { getProgress, getUserStatus } from "@/lib/api";
import { Badge, Card, PageShell, StatPill } from "@/components/ui";
import CarouselDots from "@/components/CarouselDots";
import TextScale from "@/components/TextScale";
import LogoutButton from "@/components/LogoutButton";
import HabitStepsEditor from "@/components/HabitStepsEditor";
import ProgrammeCalendar from "./ProgrammeCalendar";

type PageProps = {
  params: Promise<{ userId: string }>;
  searchParams: Promise<{ anchor_date?: string }>;
};

export default async function ProgressPage(props: PageProps) {
  const { userId } = await props.params;
  const { anchor_date } = await props.searchParams;
  const data = await getProgress(userId, anchor_date);
  const status = await getUserStatus(userId);
  const user = data.user || {};
  const meta = data.meta || {};
  const focus = data.focus || {};
  const rows = data.rows || [];
  const focusIds = new Set(focus.kr_ids || []);
  const textScale = status.coaching_preferences?.text_scale
    ? Number.parseFloat(status.coaching_preferences.text_scale)
    : undefined;
  const promptState = (status.prompt_state_override || "").toLowerCase();
  const promptBadge =
    promptState && promptState !== "live"
      ? `${promptState.charAt(0).toUpperCase()}${promptState.slice(1)} mode`
      : "";

  const statusPalette: Record<string, { bg: string; border: string; text: string }> = {
    "on track": { bg: "#ecfdf3", border: "#c6f6d5", text: "#065f46" },
    "at risk": { bg: "#fff7ed", border: "#fed7aa", text: "#9a3412" },
    "off track": { bg: "#fef2f2", border: "#fecdd3", text: "#b42318" },
    "not started": { bg: "#eff6ff", border: "#bfdbfe", text: "#1d4ed8" },
  };
  const chipPalette: Record<string, { bg: string; text: string }> = {
    "on track": { bg: "#ecfdf3", text: "#027a48" },
    "at risk": { bg: "#fff7ed", text: "#c2410c" },
    "off track": { bg: "#fef2f2", text: "#b42318" },
    "in progress": { bg: "#eff6ff", text: "#1d4ed8" },
    "not started": { bg: "#eff6ff", text: "#1d4ed8" },
  };
  const pillarColors: Record<string, { border: string; bg: string; dot: string }> = {
    nutrition: { border: "#0ba5ec", bg: "#f0f9ff", dot: "#0ba5ec" },
    recovery: { border: "#a855f7", bg: "#f8f5ff", dot: "#a855f7" },
    training: { border: "#22c55e", bg: "#ecfdf3", dot: "#22c55e" },
    resilience: { border: "#f97316", bg: "#fff7ed", dot: "#f97316" },
  };
  const programmeBlocks = [
    { label: "Nutrition", weeks: "Weeks 1–3", key: "nutrition" },
    { label: "Recovery", weeks: "Weeks 4–6", key: "recovery" },
    { label: "Training", weeks: "Weeks 7–9", key: "training" },
    { label: "Resilience", weeks: "Weeks 10–12", key: "resilience" },
  ];
  const rowStarts = rows
    .map((row: any) => (row.cycle_start ? new Date(row.cycle_start) : null))
    .filter((d: Date | null) => d && !Number.isNaN(d.getTime())) as Date[];
  const programmeStart =
    rowStarts.length > 0
      ? new Date(Math.min(...rowStarts.map((d) => d.getTime())))
      : meta.anchor_date
        ? new Date(meta.anchor_date)
        : null;
  const formatNumber = (value?: number | null) => {
    if (value === null || value === undefined) return "–";
    if (Number.isInteger(value)) return String(value);
    return value.toFixed(2).replace(/\.?0+$/, "");
  };
  const formatDateUk = (value?: string | null) => {
    if (!value) return "";
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) return value;
    return new Intl.DateTimeFormat("en-GB", {
      dateStyle: "medium",
      timeZone: "Europe/London",
    }).format(parsed);
  };
  const computeStatus = (
    actual?: number | null,
    target?: number | null,
    cycleStart?: string | null,
    cycleEnd?: string | null,
  ) => {
    const now = new Date();
    const start = cycleStart ? new Date(cycleStart) : null;
    const end = cycleEnd ? new Date(cycleEnd) : null;
    const hasStart = start && !Number.isNaN(start.getTime());
    const hasEnd = end && !Number.isNaN(end.getTime());
    const inFuture = hasStart ? now < start! : false;
    const finished = hasEnd ? now > end! : false;

    const validTarget = target !== null && target !== undefined && Number(target) !== 0;
    const validActual = actual !== null && actual !== undefined && Number.isFinite(Number(actual));

    if (inFuture) {
      return { status: "not started", pct: null };
    }

    if (!finished) {
      const ratio =
        validTarget && validActual ? Math.max(0, Math.min(1, Number(actual) / Number(target))) : null;
      return { status: "on track", pct: ratio };
    }

    if (!validTarget || !validActual) {
      return { status: "off track", pct: null };
    }

    const ratio = Math.max(0, Math.min(1, Number(actual) / Number(target)));
    return ratio >= 0.9 ? { status: "on track", pct: ratio } : { status: "off track", pct: ratio };
  };
  const focusHabitGroups = rows.flatMap((row: any) =>
    (row.krs || [])
      .filter((kr: any) => focusIds.has(kr.id))
      .map((kr: any) => ({
        id: kr.id,
        description: kr.description,
        steps: kr.habit_steps || [],
      })),
  );

  return (
    <PageShell>
      <TextScale defaultScale={textScale} />
      <nav className="sticky top-0 z-10 -mx-6 mb-4 flex flex-wrap items-center gap-2 border-y border-[#efe7db] bg-[#fbf7f0]/90 px-6 py-3 text-xs uppercase tracking-[0.2em] text-[#6b6257] backdrop-blur md:static md:mx-0 md:mb-6 md:border md:border-[#efe7db] md:rounded-full md:px-6 md:py-3">
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
      <section id="overview" className="space-y-3">
        <div
          id="momentum-carousel"
          className="flex flex-nowrap gap-6 overflow-x-auto pb-2 snap-x snap-mandatory scroll-smooth"
          style={{ scrollSnapType: "x mandatory", scrollPadding: "1.5rem" }}
        >
          <Card
            className="min-w-full snap-start sm:min-w-[85%]"
            data-carousel-item
            style={{ scrollSnapStop: "always", scrollMarginLeft: "1.5rem" }}
          >
            <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Momentum</p>
            <h2 className="mt-1 text-xl">{user.display_name || user.first_name || "User"}</h2>
            <p className="mt-1 text-xs text-[#6b6257]">{meta.anchor_label || "n/a"}</p>
            <div className="mt-4 grid grid-cols-2 gap-3">
              {Object.entries(data.status_counts || {}).map(([label, value]) => {
                const palette = statusPalette[label] || { bg: "#f5f2eb", border: "#e7e1d6", text: "#6b6257" };
                return (
                  <div
                    key={label}
                    className="rounded-2xl border px-4 py-3"
                    style={{ background: palette.bg, borderColor: palette.border, color: palette.text }}
                  >
                    <p className="text-xs uppercase tracking-[0.2em]">{label}</p>
                    <p className="text-2xl font-semibold">{value as number}</p>
                  </div>
                );
              })}
            </div>
          </Card>

          <Card
            className="min-w-full snap-start sm:min-w-[85%]"
            data-carousel-item
            style={{ scrollSnapStop: "always", scrollMarginLeft: "1.5rem" }}
          >
            <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Focus</p>
            <h2 className="mt-1 text-xl">Key results</h2>
            {focusHabitGroups.length ? (
              <div className="mt-4 space-y-3">
                {focusHabitGroups.map((group) => (
                  <div key={group.id} className="rounded-2xl border border-[#efe7db] bg-white p-3">
                    <Badge label={group.description} />
                    <details className="mt-2 text-sm text-[#3c332b]">
                      <summary className="flex cursor-pointer items-center justify-end gap-3">
                        <span className="rounded-full bg-[#e6f4f2] px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.2em] text-[var(--accent)]">
                          Habit steps
                        </span>
                      </summary>
                      <div className="mt-3">
                        {group.steps.length ? (
                          <ul className="space-y-1 text-sm text-[#3c332b]">
                            {group.steps.map((step: any) => (
                              <li key={step.id || step.text} className="flex items-start gap-2">
                                <span className="mt-1 h-1.5 w-1.5 rounded-full bg-[var(--accent)]" />
                                <span>{step.text}</span>
                              </li>
                            ))}
                          </ul>
                        ) : (
                          <p className="text-xs text-[#6b6257]">No habit steps yet.</p>
                        )}
                      </div>
                    </details>
                  </div>
                ))}
              </div>
            ) : (
              <p className="mt-4 text-sm text-[#6b6257]">No focus KRs yet.</p>
            )}
          </Card>

          <Card
            className="min-w-full snap-start sm:min-w-[85%]"
            data-carousel-item
            style={{ scrollSnapStop: "always", scrollMarginLeft: "1.5rem" }}
          >
            <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Programme</p>
            <h2 className="mt-1 text-xl">Overview</h2>
            <ProgrammeCalendar
              programmeStart={programmeStart ? programmeStart.toISOString() : null}
              programmeBlocks={programmeBlocks}
            />
          </Card>
        </div>
        <CarouselDots containerId="momentum-carousel" count={3} />
      </section>

      <section id="timeline" className="space-y-4">
        {rows.length ? (
          <div
            id="pillar-krs-carousel"
            className="flex flex-nowrap gap-6 overflow-x-auto pb-2 snap-x snap-mandatory scroll-smooth"
            style={{ scrollSnapType: "x mandatory", scrollPadding: "1.5rem" }}
          >
            {rows.map((row: any, idx: number) => {
              const palette = pillarColors[row.pillar] || { border: "#e4e7ec", bg: "#f8fafc", dot: "#98a2b3" };
              return (
                <Card
                  key={`${row.pillar}-${idx}`}
                  className="min-w-full snap-start sm:min-w-[85%]"
                  style={{
                    borderColor: palette.border,
                    background: palette.bg,
                    scrollSnapStop: "always",
                    scrollMarginLeft: "1.5rem",
                  }}
                  data-carousel-item
                >
                  <div className="flex items-center justify-between gap-4">
                    <div>
                      <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">key results</p>
                      <h3 className="mt-1 text-lg">{row.pillar}</h3>
                    </div>
                    <span className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">
                      {row.cycle_label || "Current"}
                    </span>
                  </div>
                  {row.cycle_start || row.cycle_end ? (
                    <p className="mt-1 text-xs text-[#6b6257]">
                      {row.cycle_start ? formatDateUk(row.cycle_start) : "–"} – {row.cycle_end ? formatDateUk(row.cycle_end) : "–"}
                    </p>
                  ) : null}
                  <p className="mt-2 text-sm text-[#3c332b]">{row.objective || "No objective yet."}</p>
                  {(row.krs || []).length ? (
                    <div className="mt-4 space-y-3">
                      {(row.krs || []).map((kr: any) => {
                        const status = computeStatus(kr.actual, kr.target, row.cycle_start, row.cycle_end);
                        const chip = chipPalette[status.status] || { bg: "#f4f4f5", text: "#52525b" };
                        const pctValue = status.pct ?? 0;
                        const barWidth = status.pct === null ? "4%" : `${Math.round(pctValue * 100)}%`;
                        const barColor = status.status === "not started" ? "#93c5fd" : undefined;
                        return (
                          <div key={kr.id} className="rounded-2xl border border-[#eadcc6] bg-white p-3">
                            <p className="text-sm font-semibold text-[#1e1b16]">{kr.description}</p>
                            <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-[#6b6257]">
                              <span
                                className="rounded-full px-2 py-0.5"
                                style={{ background: chip.bg, color: chip.text }}
                              >
                                {status.status}
                              </span>
                              {focusIds.has(kr.id) ? (
                                <span className="rounded-full bg-[#fef3c7] px-2 py-0.5 font-semibold text-[#92400e]">
                                  Focus KR
                                </span>
                              ) : null}
                            </div>
                            <div className="mt-2 grid grid-cols-3 gap-2 text-xs text-[#6b6257]">
                              <div>
                                <p className="text-[10px] uppercase tracking-[0.26em] text-[#8b8074]">Baseline</p>
                                <p className="text-sm text-[#1e1b16]">{formatNumber(kr.baseline)}</p>
                              </div>
                              <div>
                                <p className="text-[10px] uppercase tracking-[0.26em] text-[#8b8074]">Current</p>
                                <p className="text-sm text-[#1e1b16]">{formatNumber(kr.actual)}</p>
                              </div>
                              <div>
                                <p className="text-[10px] uppercase tracking-[0.26em] text-[#8b8074]">Target</p>
                                <p className="text-sm text-[#1e1b16]">{formatNumber(kr.target)}</p>
                              </div>
                            </div>
                            <div className="mt-2 flex items-center gap-2">
                              <span className="text-xs font-semibold text-[#101828]">
                                {status.pct !== null ? `${Math.round(status.pct * 100)}%` : "–"}
                              </span>
                              <div className="h-2 flex-1 overflow-hidden rounded-full bg-[#e4e7ec]">
                                <div
                                  className="h-full rounded-full bg-gradient-to-r from-[#0ba5ec] to-[#3cba92]"
                                  style={{
                                    width: barWidth,
                                    background: barColor ?? undefined,
                                  }}
                                />
                              </div>
                            </div>
                            <HabitStepsEditor
                              userId={userId}
                              krId={kr.id}
                              initialSteps={kr.habit_steps || []}
                            />
                          </div>
                        );
                      })}
                    </div>
                  ) : (
                    <p className="mt-3 text-sm text-[#6b6257]">No key results recorded yet.</p>
                  )}
                </Card>
              );
            })}
          </div>
        ) : (
          <Card>
            <p className="text-sm text-[#6b6257]">No key results recorded yet.</p>
          </Card>
        )}
        {rows.length ? <CarouselDots containerId="pillar-krs-carousel" count={rows.length} /> : null}
      </section>

    </PageShell>
  );
}
