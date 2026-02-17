"use client";

import { useMemo } from "react";
import { getPillarPalette } from "@/lib/pillars";

type ProgrammeBlock = { label: string; weeks: string; key: string };
type ProgrammeBlockRange = ProgrammeBlock & { start?: string | null; end?: string | null };

type ProgrammeCalendarProps = {
  programmeStart?: string | null;
  programmeBlocks: ProgrammeBlockRange[];
  programmeLengthDays?: number;
};

const weekLabels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

const toMonthKey = (date: Date) => `${date.getFullYear()}-${date.getMonth()}`;

export default function ProgrammeCalendar({
  programmeStart,
  programmeBlocks,
  programmeLengthDays = 84,
}: ProgrammeCalendarProps) {
  const days = useMemo(() => {
    const startDate = programmeStart ? new Date(programmeStart) : null;
    const ranges = programmeBlocks
      .map((block) => {
        const start = block.start ? new Date(block.start) : null;
        const end = block.end ? new Date(block.end) : null;
        if (!start || !end || Number.isNaN(start.getTime()) || Number.isNaN(end.getTime())) return null;
        return { key: block.key, start, end };
      })
      .filter((value): value is { key: string; start: Date; end: Date } => Boolean(value));
    const baseStart =
      ranges.length > 0
        ? new Date(Math.min(...ranges.map((range) => range.start.getTime())))
        : startDate && !Number.isNaN(startDate.getTime())
          ? startDate
          : null;
    if (!baseStart) return [];
    const baseEnd =
      ranges.length > 0
        ? new Date(Math.max(...ranges.map((range) => range.end.getTime())))
        : new Date(baseStart.getTime() + (programmeLengthDays - 1) * 24 * 60 * 60 * 1000);
    const totalDays = Math.max(
      1,
      Math.floor((baseEnd.getTime() - baseStart.getTime()) / (24 * 60 * 60 * 1000)) + 1,
    );
    const fallbackKey = programmeBlocks[0]?.key || "nutrition";
    return Array.from({ length: totalDays }, (_, idx) => {
      const date = new Date(baseStart.getTime() + idx * 24 * 60 * 60 * 1000);
      const key =
        ranges.find((range) => date >= range.start && date <= range.end)?.key || fallbackKey;
      return { date, key };
    });
  }, [programmeBlocks, programmeLengthDays, programmeStart]);

  const monthOptions = useMemo(() => {
    if (!days.length) return [];
    const unique: Record<string, Date> = {};
    for (const item of days) {
      const key = toMonthKey(item.date);
      if (!unique[key]) unique[key] = new Date(item.date.getFullYear(), item.date.getMonth(), 1);
    }
    return Object.entries(unique)
      .sort(([a], [b]) => (a < b ? -1 : 1))
      .map(([key, date]) => ({
        key,
        label: date.toLocaleDateString("en-GB", { month: "long", year: "numeric" }),
        date,
      }));
  }, [days]);

  const monthData = useMemo(() => {
    return monthOptions.map((opt) => {
      const monthDays = days.filter((d) => toMonthKey(d.date) === opt.key);
      if (!monthDays.length) return { ...opt, days: [], blanks: 0 };
      const first = monthDays[0].date;
      const weekday = first.getDay(); // 0 Sun..6 Sat
      const blanks = weekday === 0 ? 6 : weekday - 1; // align Monday start
      return { ...opt, days: monthDays, blanks };
    });
  }, [days, monthOptions]);

  return (
    <div className="mt-4 rounded-2xl border border-[#efe7db] bg-white p-4">
      <div className="flex flex-wrap items-center gap-2 text-xs text-[#6b6257]">
        {programmeBlocks.map((block) => {
          const palette = getPillarPalette(block.key);
          return (
            <span
              key={block.key}
              className="inline-flex items-center gap-2 rounded-full border px-3 py-1"
              style={{ borderColor: palette.border, background: palette.bg }}
            >
              <span className="h-2 w-2 rounded-full" style={{ background: palette.dot }} />
              {block.label}
            </span>
          );
        })}
      </div>

      {monthData.length ? (
        <>
          <div className="mt-2 flex snap-x snap-mandatory gap-4 overflow-x-auto pb-2">
            {monthData.map((month) => (
              <div
                key={month.key}
                className="min-w-[260px] snap-start rounded-2xl border border-[#efe7db] bg-[#faf7f1] p-3"
                style={{ scrollSnapStop: "always" }}
              >
                <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">{month.label}</p>
                <div className="mt-2 grid grid-cols-7 gap-1.5 text-[10px] uppercase tracking-[0.2em] text-[#8b8074]">
                  {weekLabels.map((label) => (
                    <div key={`${month.key}-${label}`} className="text-center">
                      {label}
                    </div>
                  ))}
                </div>
                <div className="mt-1.5 grid grid-cols-7 gap-1.5">
                  {Array.from({ length: month.blanks }).map((_, idx) => (
                    <div key={`blank-${month.key}-${idx}`} className="h-9 rounded-lg border border-transparent" />
                  ))}
                  {month.days.map((item) => {
                    const palette = getPillarPalette(item.key);
                    return (
                      <div
                        key={item.date.toISOString()}
                        className="flex h-9 items-center justify-center rounded-lg border text-xs font-semibold text-[#1e1b16]"
                        style={{ borderColor: palette.border, background: palette.bg }}
                      >
                        {item.date.getDate()}
                      </div>
                    );
                  })}
                </div>
              </div>
            ))}
          </div>
          
        </>
      ) : (
        <p className="mt-3 text-xs text-[#6b6257]">Programme dates not available yet.</p>
      )}
    </div>
  );
}
