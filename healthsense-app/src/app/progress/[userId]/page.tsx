import type { CSSProperties } from "react";
import { getProgress, getUserStatus } from "@/lib/api";
import { getPillarPalette } from "@/lib/pillars";
import { Card, PageShell } from "@/components/ui";
import CarouselDots from "@/components/CarouselDots";
import TextScale from "@/components/TextScale";
import AppNav from "@/components/AppNav";
import IntroInlinePanel from "@/components/IntroInlinePanel";
import KRUpdateEditor from "@/components/KRUpdateEditor";
import ProgrammeCalendar from "./ProgrammeCalendar";

type PageProps = {
  params: Promise<{ userId: string }>;
  searchParams: Promise<{ anchor_date?: string }>;
};

type ProgressKr = {
  id?: number;
  description?: string;
  baseline?: number | null;
  actual?: number | null;
  target?: number | null;
  metric_label?: string | null;
  unit?: string | null;
  habit_steps?: HabitStep[];
};

type ProgressRow = {
  pillar?: string;
  cycle_label?: string;
  cycle_start?: string;
  cycle_end?: string;
  objective?: string;
  krs?: ProgressKr[];
};

type HabitStep = {
  id?: number;
  text?: string;
};

export default async function ProgressPage(props: PageProps) {
  const { userId } = await props.params;
  const { anchor_date } = await props.searchParams;
  const data = await getProgress(userId, anchor_date);
  const status = await getUserStatus(userId);
  const meta = data.meta || {};
  const focus = data.focus || {};
  const focusIds = new Set(
    (focus.kr_ids || [])
      .map((value: unknown) => Number(value))
      .filter((value: number) => Number.isInteger(value) && value > 0),
  );
  const rows: ProgressRow[] = data.rows || [];
  const textScale = status.coaching_preferences?.text_scale
    ? Number.parseFloat(status.coaching_preferences.text_scale)
    : undefined;
  const promptState = (status.prompt_state_override || "").toLowerCase();
  const promptBadge =
    promptState && promptState !== "live"
      ? `${promptState.charAt(0).toUpperCase()}${promptState.slice(1)} mode`
      : "";
  const chipPalette: Record<string, { bg: string; text: string }> = {
    "on track": { bg: "#ecfdf3", text: "#027a48" },
    "at risk": { bg: "#fff7ed", text: "#c2410c" },
    "off track": { bg: "#fef2f2", text: "#b42318" },
    "in progress": { bg: "#eff6ff", text: "#1d4ed8" },
    "not started": { bg: "#eff6ff", text: "#1d4ed8" },
  };

  const programmeBlocks = [
    { label: "Nutrition", weeks: "Weeks 1–3", key: "nutrition", weekStart: 1, weekEnd: 3 },
    { label: "Recovery", weeks: "Weeks 4–6", key: "recovery", weekStart: 4, weekEnd: 6 },
    { label: "Training", weeks: "Weeks 7–9", key: "training", weekStart: 7, weekEnd: 9 },
    { label: "Resilience", weeks: "Weeks 10–12", key: "resilience", weekStart: 10, weekEnd: 12 },
  ];

  const rowStarts = rows
    .map((row) => (row.cycle_start ? new Date(row.cycle_start) : null))
    .filter((d: Date | null) => d && !Number.isNaN(d.getTime())) as Date[];
  const programmeStart =
    rowStarts.length > 0
      ? new Date(Math.min(...rowStarts.map((d) => d.getTime())))
      : meta.anchor_date
        ? new Date(meta.anchor_date)
        : null;

  const formatDateUk = (value?: Date | null) => {
    if (!value) return "";
    if (Number.isNaN(value.getTime())) return "";
    return new Intl.DateTimeFormat("en-GB", {
      dateStyle: "medium",
      timeZone: "Europe/London",
    }).format(value);
  };
  const formatDateUkFromIso = (value?: string | null) => {
    if (!value) return "";
    const parsed = new Date(value);
    return Number.isNaN(parsed.getTime()) ? "–" : formatDateUk(parsed);
  };
  const formatNumber = (value?: number | null) => {
    if (value === null || value === undefined) return "–";
    if (Number.isInteger(value)) return String(value);
    return value.toFixed(2).replace(/\.?0+$/, "");
  };

  const toFiniteNumber = (value?: number | null) => {
    if (value === null || value === undefined) return null;
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  };

  const progressRatio = (actual?: number | null, target?: number | null, baseline?: number | null) => {
    const actualNum = toFiniteNumber(actual);
    const targetNum = toFiniteNumber(target);
    const baselineNum = toFiniteNumber(baseline);
    if (actualNum === null || targetNum === null) return null;
    if (baselineNum !== null && Math.abs(targetNum - baselineNum) > 1e-9) {
      return Math.max(0, Math.min(1, (actualNum - baselineNum) / (targetNum - baselineNum)));
    }
    if (Math.abs(targetNum) < 1e-9) return null;
    return Math.max(0, Math.min(1, actualNum / targetNum));
  };
  const computeStatus = (
    actual?: number | null,
    target?: number | null,
    baseline?: number | null,
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

    if (inFuture) {
      return { status: "not started", pct: null };
    }
    const ratio = progressRatio(actual, target, baseline);
    if (!finished) {
      return { status: "on track", pct: ratio };
    }
    if (ratio === null) {
      return { status: "off track", pct: null };
    }
    if (ratio >= 0.9) return { status: "on track", pct: ratio };
    if (ratio >= 0.5) return { status: "at risk", pct: ratio };
    return { status: "off track", pct: ratio };
  };

  const MS_PER_DAY = 24 * 60 * 60 * 1000;
  const isoDateToDayNumber = (value?: string | null) => {
    if (!value) return null;
    const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value.trim());
    if (!m) return null;
    const y = Number(m[1]);
    const mo = Number(m[2]);
    const d = Number(m[3]);
    return Math.floor(Date.UTC(y, mo - 1, d) / MS_PER_DAY);
  };
  const dayNumberToIso = (dayNumber: number) => {
    return new Date(dayNumber * MS_PER_DAY).toISOString().slice(0, 10);
  };
  const valueToDayNumber = (value?: string | null) => {
    if (!value) return null;
    const trimmed = value.trim();
    const isoPrefix = /^(\d{4}-\d{2}-\d{2})/.exec(trimmed);
    if (isoPrefix) return isoDateToDayNumber(isoPrefix[1]);
    const parsed = new Date(trimmed);
    if (Number.isNaN(parsed.getTime())) return null;
    return Math.floor(Date.UTC(parsed.getUTCFullYear(), parsed.getUTCMonth(), parsed.getUTCDate()) / MS_PER_DAY);
  };

  const user = data.user || {};
  const MAX_STREAK_ICONS = 10;
  const rawDailyStreak = Number(data.engagement?.daily_streak ?? 0);
  const totalActiveStreakDays = Number.isFinite(rawDailyStreak) ? Math.max(0, Math.floor(rawDailyStreak)) : 0;
  const streakWindowDays = Math.min(
    MAX_STREAK_ICONS,
    Math.max(1, Number(data.engagement?.recent_window_days || MAX_STREAK_ICONS)),
  );
  const streakActiveDateSet = new Set(
    (data.engagement?.recent_active_dates || []).filter((value): value is string => typeof value === "string" && value.length >= 10),
  );
  const anchorDateKey =
    typeof meta.anchor_date === "string" && /^\d{4}-\d{2}-\d{2}$/.test(meta.anchor_date)
      ? meta.anchor_date
      : new Date().toISOString().slice(0, 10);
  const anchorDayNumber = isoDateToDayNumber(anchorDateKey) ?? 0;
  const programmeStartDayNumbers = rows
    .map((row) => valueToDayNumber(row.cycle_start || null))
    .filter((dayNumber): dayNumber is number => dayNumber !== null);
  const programmeStartDayNumber = programmeStartDayNumbers.length ? Math.min(...programmeStartDayNumbers) : null;
  const fallbackPillarKey = programmeBlocks[0]?.key || "nutrition";
  const pillarKeyForDay = (dayNumber: number) => {
    if (programmeStartDayNumber === null) return fallbackPillarKey;
    const dayOffset = dayNumber - programmeStartDayNumber;
    if (dayOffset < 0 || dayOffset >= 84) return fallbackPillarKey;
    const blockIndex = Math.min(3, Math.max(0, Math.floor(dayOffset / 21)));
    return programmeBlocks[blockIndex]?.key || fallbackPillarKey;
  };
  const streakDays = Array.from({ length: streakWindowDays }, (_, idx) => {
    const dayNumber = anchorDayNumber - idx;
    const iso = dayNumberToIso(dayNumber);
    const pillarKey = pillarKeyForDay(dayNumber);
    return {
      iso,
      active: streakActiveDateSet.has(iso),
      pillar: getPillarPalette(pillarKey),
    };
  });

  const programmeDayRaw = programmeStartDayNumber !== null ? anchorDayNumber - programmeStartDayNumber + 1 : null;
  const programmeDay = programmeDayRaw === null ? 0 : Math.max(0, Math.min(84, programmeDayRaw));
  const currentProgrammeWeek = Math.max(1, Math.min(12, Math.ceil(Math.max(programmeDay, 1) / 7)));
  const currentBlockIndex = Math.min(programmeBlocks.length - 1, Math.floor((currentProgrammeWeek - 1) / 3));
  const currentBlock = programmeBlocks[currentBlockIndex] || programmeBlocks[0];
  const weekOfCurrentBlock = ((currentProgrammeWeek - 1) % 3) + 1;
  let activeStreakDays = 0;
  for (const day of streakDays) {
    if (!day.active) break;
    activeStreakDays += 1;
  }
  const activeStreakIcons = streakDays.slice(0, Math.min(activeStreakDays, MAX_STREAK_ICONS));
  const firstName = (user.first_name || user.display_name || status.user?.first_name || status.user?.display_name || "User").split(" ")[0];
  const dayLabel = totalActiveStreakDays === 1 ? "day" : "days";
  const weekHeadline =
    totalActiveStreakDays > 0
      ? `You on week ${weekOfCurrentBlock} of 3 for ${currentBlock.label} and on a ${totalActiveStreakDays} ${dayLabel} streak, keep it up ${firstName}!`
      : `You on week ${weekOfCurrentBlock} of 3 for ${currentBlock.label}. Start your streak today, ${firstName}.`;
  const introHeadline = String(status.intro?.message || "").trim();
  const introIncomplete = !String(status.onboarding?.intro_content_completed_at || "").trim();
  const headlineText =
    status.intro?.enabled && introIncomplete && introHeadline ? introHeadline : weekHeadline;
  const anchorLabel = `${meta.anchor_label || "n/a"}${meta.is_virtual_date ? "*" : ""}`;

  const normalizePillarKey = (value?: string) => {
    const key = (value || "").toLowerCase();
    if (key.includes("nutri")) return "nutrition";
    if (key.includes("recover")) return "recovery";
    if (key.includes("train")) return "training";
    if (key.includes("resilien")) return "resilience";
    return fallbackPillarKey;
  };

  const programmeDaysCapped = Math.max(0, Math.min(84, programmeDay));
  const pillarSummaries = programmeBlocks.map((block) => {
    const blockStartDay = (block.weekStart - 1) * 7 + 1;
    const daysIntoBlock = Math.max(0, Math.min(21, programmeDaysCapped - blockStartDay + 1));
    const pct = Math.round((daysIntoBlock / 21) * 100);
    return {
      key: block.key,
      label: block.label,
      palette: getPillarPalette(block.key),
      pct,
      notStarted: daysIntoBlock === 0,
    };
  });
  const dailyFocusTexts: string[] = [];
  const seenDailyFocus = new Set<string>();
  const addDailyFocusSteps = (candidateRows: ProgressRow[], krPredicate?: (kr: ProgressKr) => boolean) => {
    for (const row of candidateRows) {
      for (const kr of row.krs || []) {
        if (krPredicate && !krPredicate(kr)) continue;
        for (const step of kr.habit_steps || []) {
          const text = (step.text || "").trim();
          if (!text) continue;
          const key = text.toLowerCase();
          if (seenDailyFocus.has(key)) continue;
          seenDailyFocus.add(key);
          dailyFocusTexts.push(text);
          if (dailyFocusTexts.length >= 4) return;
        }
      }
    }
  };
  addDailyFocusSteps(rows, (kr) => typeof kr.id === "number" && focusIds.has(kr.id));
  if (!dailyFocusTexts.length) {
    addDailyFocusSteps(rows.filter((row) => normalizePillarKey(row.pillar) === currentBlock.key));
  }
  if (!dailyFocusTexts.length) {
    addDailyFocusSteps(rows);
  }

  const nextAssessmentDue =
    programmeStart && !Number.isNaN(programmeStart.getTime())
      ? new Date(programmeStart.getTime() + 84 * MS_PER_DAY)
      : null;

  return (
    <PageShell>
      <TextScale defaultScale={textScale} />
      <AppNav userId={userId} promptBadge={promptBadge} />

      <section id="overview" className="space-y-3">
        <div
          id="overview-carousel"
          className="flex flex-nowrap gap-4 overflow-x-auto pb-2 snap-x snap-mandatory scroll-smooth"
          style={{ scrollSnapType: "x mandatory" }}
        >
          <Card className="min-w-full snap-start p-4 sm:min-w-[85%]" style={{ scrollSnapStop: "always" }} data-carousel-item>
            <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">{anchorLabel}</p>
            <p className="mt-2 text-[32px] leading-[1.2] text-[#1e1b16]">{headlineText}</p>
            <IntroInlinePanel
              userId={userId}
              intro={status.intro}
              introCompleted={!introIncomplete}
            />

            <div className="mt-3 border-t border-[#efe7db] pt-3">
              <p className="text-sm font-semibold uppercase tracking-[0.2em] text-[#6b6257]">Daily Streak</p>
              <div className="mt-2 rounded-xl border border-[#f4c9a9] bg-white p-3">
                {activeStreakIcons.length ? (
                  <div className="flex flex-wrap gap-2">
                    {activeStreakIcons.map((day) => (
                      <div
                        key={day.iso}
                        className="rounded-xl border p-2"
                        style={{
                          borderColor: "#e6a786",
                          background: "#fff7f1",
                        }}
                        title={day.iso}
                      >
                        <img src="/healthsense-mark.svg" alt="" className="mx-auto h-7 w-7" aria-hidden="true" />
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="text-sm text-[#6b6257]">No streak yet.</p>
                )}
              </div>
            </div>

            <div className="mt-3 border-t border-[#efe7db] pt-3">
              <p className="text-sm font-semibold uppercase tracking-[0.2em] text-[#6b6257]">Daily Focus</p>
              {dailyFocusTexts.length ? (
                <ul className="mt-2 space-y-2 text-sm text-[#1e1b16]">
                  {dailyFocusTexts.map((step, idx) => (
                    <li
                      key={`daily-focus-${idx}`}
                      className="rounded-lg px-3 py-2 font-medium"
                      style={{
                        background: "#c54817",
                        color: "#ffffff",
                      }}
                    >
                      <span>{step}</span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="mt-2 text-xs text-[#6b6257]">No habit steps to focus on yet.</p>
              )}
            </div>

            <div className="mt-3 border-t border-[#efe7db] pt-3 text-[#1e1b16]">
              <p className="text-sm font-semibold uppercase tracking-[0.2em] text-[#6b6257]">Programme Progress</p>
              <div className="mt-3 rounded-xl border border-[#e6a786] bg-[#fff7f1] p-3">
                <div className="space-y-3">
                  {pillarSummaries.map((summary, idx) => (
                    <div key={`pillar-summary-${summary.key}`} className={idx > 0 ? "border-t border-[#efd4bf] pt-3" : ""}>
                      <div className="flex items-center justify-between gap-3">
                        <div className="flex items-center gap-2.5">
                          {summary.palette.icon ? (
                            <img src={summary.palette.icon} alt="" className="h-6 w-6" aria-hidden="true" />
                          ) : null}
                          <span className="text-sm font-semibold uppercase tracking-[0.2em] text-[#3c332b]">{summary.label}</span>
                        </div>
                        <span
                          className="text-base font-semibold"
                          style={{ color: summary.notStarted ? "#8b8074" : summary.palette.accent }}
                          title={summary.notStarted ? "Not started" : undefined}
                        >
                          {summary.notStarted ? "○" : `${summary.pct}%`}
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
              <div className="mt-3 border-t border-[#efe7db] pt-3">
                <p className="text-sm font-semibold uppercase tracking-[0.2em] text-[#6b6257]">
                  Your next assessment is on {nextAssessmentDue ? formatDateUk(nextAssessmentDue) : "Not available"}
                </p>
              </div>
            </div>
          </Card>

          <Card className="min-w-full snap-start p-4 sm:min-w-[85%]" style={{ scrollSnapStop: "always" }} data-carousel-item>
            <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Programme</p>
            <h2 className="mt-1 text-xl">Overview</h2>
            <ProgrammeCalendar
              programmeStart={programmeStart ? programmeStart.toISOString() : null}
              programmeBlocks={programmeBlocks}
            />
          </Card>
        </div>
        <CarouselDots containerId="overview-carousel" count={2} />
      </section>

      <section id="timeline" className="space-y-4">
        {rows.length ? (
          <>
            <div
              id="pillar-krs-carousel"
              className="flex flex-nowrap gap-6 overflow-x-auto pb-2 snap-x snap-mandatory scroll-smooth"
              style={{ scrollSnapType: "x mandatory" }}
            >
              {rows.map((row: ProgressRow, idx: number) => {
                const palette = getPillarPalette(row.pillar);
                const cardStyle = {
                  borderColor: palette.border,
                  background: palette.bg,
                  "--accent": palette.accent,
                } as CSSProperties;
                return (
                  <Card
                    key={`${row.pillar || "pillar"}-${idx}`}
                    className="min-w-full snap-start sm:min-w-[85%]"
                    style={{
                      scrollSnapStop: "always",
                      ...cardStyle,
                    }}
                    data-carousel-item
                  >
                    <div className="flex items-center justify-between gap-4">
                      <div>
                        <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Key results</p>
                        <h3 className="mt-1 flex items-center gap-1 text-lg capitalize">
                          {palette.icon ? (
                            <img src={palette.icon} alt="" className="h-[23px] w-[23px]" aria-hidden="true" />
                          ) : null}
                          {row.pillar || "Pillar"}
                        </h3>
                      </div>
                      <span className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">
                        {row.cycle_label || "Current"}
                      </span>
                    </div>
                    {row.cycle_start || row.cycle_end ? (
                      <p className="mt-1 text-xs text-[#6b6257]">
                        {formatDateUkFromIso(row.cycle_start)} – {formatDateUkFromIso(row.cycle_end)}
                      </p>
                    ) : null}
                    <p className="mt-2 text-sm text-[#3c332b]">{row.objective || "No objective yet."}</p>
                    {(row.krs || []).length ? (
                      <div className="mt-4 space-y-3">
                        {(row.krs || []).map((kr: ProgressKr, krIdx: number) => {
                          const status = computeStatus(
                            kr.actual,
                            kr.target,
                            kr.baseline,
                            row.cycle_start,
                            row.cycle_end,
                          );
                          const chip = chipPalette[status.status] || { bg: "#f4f4f5", text: "#52525b" };
                          const pctValue = status.pct ?? 0;
                          const barWidth = status.pct === null ? "4%" : `${Math.round(pctValue * 100)}%`;
                          return (
                            <div key={`${row.pillar || "pillar"}-${idx}-${kr.id || krIdx}`} className="rounded-2xl border border-[#eadcc6] bg-white p-3">
                              <p className="text-sm font-semibold text-[#1e1b16]">{kr.description || "Key result"}</p>
                              <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-[#6b6257]">
                                <span
                                  className="rounded-full px-2 py-0.5"
                                  style={{ background: chip.bg, color: chip.text }}
                                >
                                  {status.status}
                                </span>
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
                                    className="h-full rounded-full"
                                    style={{
                                      width: barWidth,
                                      background: palette.accent,
                                    }}
                                  />
                                </div>
                              </div>
                              <div className="mt-2">
                                <p className="text-[11px] uppercase tracking-[0.26em] text-[#8b8074]">Habit steps</p>
                                {(kr.habit_steps || []).length ? (
                                  <ul className="mt-1 space-y-1 text-xs text-[#3c332b]">
                                    {(kr.habit_steps || []).map((step: HabitStep, stepIdx: number) => (
                                      <li key={`${row.pillar || "pillar"}-${kr.id || krIdx}-${step.id || stepIdx}`} className="flex items-start gap-2">
                                        <span className="mt-1 h-1.5 w-1.5 rounded-full bg-[var(--accent)]" />
                                        <span>{step.text}</span>
                                      </li>
                                    ))}
                                  </ul>
                                ) : (
                                  <p className="mt-1 text-xs text-[#6b6257]">No habit steps yet.</p>
                                )}
                              </div>
                              {typeof kr.id === "number" ? (
                                <KRUpdateEditor
                                  userId={userId}
                                  krId={kr.id}
                                  initialDescription={kr.description}
                                  initialActual={kr.actual}
                                  initialTarget={kr.target}
                                  metricLabel={kr.metric_label}
                                  unit={kr.unit}
                                />
                              ) : null}
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
            <CarouselDots containerId="pillar-krs-carousel" count={rows.length} />
          </>
        ) : (
          <Card>
            <p className="text-sm text-[#6b6257]">No key results recorded yet.</p>
          </Card>
        )}
      </section>
    </PageShell>
  );
}
