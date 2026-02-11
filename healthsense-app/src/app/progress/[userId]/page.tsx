import type { CSSProperties } from "react";
import { getProgress, getUserStatus } from "@/lib/api";
import { getPillarPalette } from "@/lib/pillars";
import { Badge, Card, PageShell, StatPill } from "@/components/ui";
import CarouselDots from "@/components/CarouselDots";
import TextScale from "@/components/TextScale";
import AppNav from "@/components/AppNav";
import HabitStepsEditor from "@/components/HabitStepsEditor";
import ProgrammeCalendar from "./ProgrammeCalendar";

type PageProps = {
  params: Promise<{ userId: string }>;
  searchParams: Promise<{ anchor_date?: string }>;
};

type HabitStep = {
  id?: number;
  text?: string;
  status?: string;
  week_no?: number | null;
};

type ProgressKr = {
  id?: number;
  description?: string;
  baseline?: number | null;
  actual?: number | null;
  target?: number | null;
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

export default async function ProgressPage(props: PageProps) {
  const { userId } = await props.params;
  const { anchor_date } = await props.searchParams;
  const data = await getProgress(userId, anchor_date);
  const status = await getUserStatus(userId);
  const user = data.user || {};
  const meta = data.meta || {};
  const focus = data.focus || {};
  const rows: ProgressRow[] = data.rows || [];
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
  const programmeBlocks = [
    { label: "Nutrition", weeks: "Weeks 1–3", key: "nutrition" },
    { label: "Recovery", weeks: "Weeks 4–6", key: "recovery" },
    { label: "Training", weeks: "Weeks 7–9", key: "training" },
    { label: "Resilience", weeks: "Weeks 10–12", key: "resilience" },
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
    if (ratio === null) {
      return { status: finished ? "off track" : "not started", pct: null };
    }
    if (ratio >= 0.9) return { status: "on track", pct: ratio };
    if (ratio >= 0.5) return { status: "at risk", pct: ratio };
    return { status: "off track", pct: ratio };
  };
  const focusHabitGroups = rows.flatMap((row) =>
    (row.krs || [])
      .filter((kr) => typeof kr.id === "number" && focusIds.has(kr.id))
      .map((kr) => ({
        id: kr.id as number,
        description: kr.description || "Focus KR",
        steps: kr.habit_steps || [],
      })),
  );
  const statusCounts = data.status_counts || {};
  const onTrackCount = Number(statusCounts["on track"] || 0);
  const atRiskCount = Number(statusCounts["at risk"] || 0);
  const offTrackCount = Number(statusCounts["off track"] || 0);
  const notStartedCount = Number(statusCounts["not started"] || 0);
  const totalKrs = Number(data.total_krs || onTrackCount + atRiskCount + offTrackCount + notStartedCount);
  const momentumScore = totalKrs > 0 ? Math.round(((onTrackCount + atRiskCount * 0.5) / totalKrs) * 100) : 0;
  const weekWindow = data.week_window || {};
  const weekEnd = weekWindow.end ? new Date(weekWindow.end) : null;
  const now = new Date();
  const weekDaysLeft =
    weekEnd && !Number.isNaN(weekEnd.getTime())
      ? Math.max(0, Math.ceil((weekEnd.getTime() - now.getTime()) / (24 * 60 * 60 * 1000)))
      : null;
  const focusHabitSteps: HabitStep[] = focusHabitGroups.flatMap((group) => group.steps || []);
  const focusHabitDone = focusHabitSteps.filter((step) =>
    ["done", "complete", "completed"].includes(String(step.status || "").toLowerCase()),
  ).length;
  const focusHabitTotal = focusHabitSteps.length;
  const focusHabitPct = focusHabitTotal > 0 ? Math.round((focusHabitDone / focusHabitTotal) * 100) : 0;
  const focusXp = focusHabitDone * 10;

  return (
    <PageShell>
      <TextScale defaultScale={textScale} />
      <AppNav userId={userId} promptBadge={promptBadge} />
      <section id="overview" className="space-y-3">
        <div
          id="momentum-carousel"
          className="flex flex-nowrap gap-6 overflow-x-auto pb-2 snap-x snap-mandatory scroll-smooth"
          style={{ scrollSnapType: "x mandatory" }}
        >
          <Card
            className="min-w-full snap-start sm:min-w-[85%]"
            data-carousel-item
            style={{ scrollSnapStop: "always" }}
          >
            <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Momentum</p>
            <h2 className="mt-1 text-xl">
              {`Your momentum, ${(user.first_name || user.display_name || "User").split(" ")[0]}`}
            </h2>
            <p className="mt-1 text-xs text-[#6b6257]">{meta.anchor_label || "n/a"}</p>
            <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-3">
              <StatPill label="Momentum score" value={`${momentumScore}%`} />
              <StatPill label="Total KRs" value={totalKrs} bg="#f5f3ff" border="#ddd6fe" accent="#5b21b6" />
              <StatPill
                label="Week window"
                value={weekWindow.is_current ? `${weekDaysLeft ?? 0}d left` : "Inactive"}
                bg="#eff6ff"
                border="#bfdbfe"
                accent="#1d4ed8"
              />
            </div>
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
            style={{ scrollSnapStop: "always" }}
          >
            <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Focus</p>
            <h2 className="mt-1 text-xl">Key results</h2>
            <div className="mt-4 rounded-2xl border border-[#efe7db] bg-[#faf7f1] p-3">
              <div className="grid grid-cols-3 gap-2 text-center text-xs">
                <div className="rounded-xl border border-[#e7e1d6] bg-white px-2 py-2">
                  <p className="uppercase tracking-[0.2em] text-[#8b8074]">Completed</p>
                  <p className="mt-1 text-base font-semibold text-[#1e1b16]">{focusHabitDone}/{focusHabitTotal || 0}</p>
                </div>
                <div className="rounded-xl border border-[#e7e1d6] bg-white px-2 py-2">
                  <p className="uppercase tracking-[0.2em] text-[#8b8074]">Focus XP</p>
                  <p className="mt-1 text-base font-semibold text-[#1e1b16]">{focusXp}</p>
                </div>
                <div className="rounded-xl border border-[#e7e1d6] bg-white px-2 py-2">
                  <p className="uppercase tracking-[0.2em] text-[#8b8074]">Completion</p>
                  <p className="mt-1 text-base font-semibold text-[#1e1b16]">{focusHabitPct}%</p>
                </div>
              </div>
              <div className="mt-3 h-2 overflow-hidden rounded-full bg-[#e4e7ec]">
                <div className="h-full rounded-full bg-[#0ea5a4]" style={{ width: `${focusHabitPct}%` }} />
              </div>
            </div>
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
                            {group.steps.map((step: HabitStep) => (
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
            style={{ scrollSnapStop: "always" }}
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
                  key={`${row.pillar}-${idx}`}
                  className="min-w-full snap-start sm:min-w-[85%]"
                  style={{
                    scrollSnapStop: "always",
                    ...cardStyle,
                  }}
                  data-carousel-item
                >
                  <div className="flex items-center justify-between gap-4">
                    <div>
                      <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">key results</p>
                      <h3 className="mt-1 flex items-center gap-1 text-lg capitalize">
                        {palette.icon ? (
                          <img src={palette.icon} alt="" className="h-[23px] w-[23px]" aria-hidden="true" />
                        ) : null}
                        {row.pillar}
                      </h3>
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
                  {(row.krs || []).map((kr: ProgressKr, krIdx: number) => {
                        const krId = typeof kr.id === "number" ? kr.id : null;
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
                        const barColor = palette.accent;
                        return (
                          <div key={krId ?? `${row.pillar || "pillar"}-${idx}-${krIdx}`} className="rounded-2xl border border-[#eadcc6] bg-white p-3">
                            <p className="text-sm font-semibold text-[#1e1b16]">{kr.description}</p>
                            <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-[#6b6257]">
                              <span
                                className="rounded-full px-2 py-0.5"
                                style={{ background: chip.bg, color: chip.text }}
                              >
                                {status.status}
                              </span>
                              {krId !== null && focusIds.has(krId) ? (
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
                                  className="h-full rounded-full"
                                  style={{
                                    width: barWidth,
                                    background: barColor,
                                  }}
                                />
                              </div>
                            </div>
                            {krId !== null ? (
                              <HabitStepsEditor
                                userId={userId}
                                krId={krId}
                                initialSteps={kr.habit_steps || []}
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
