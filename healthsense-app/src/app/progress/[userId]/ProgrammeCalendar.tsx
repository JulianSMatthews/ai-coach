"use client";

import { useMemo } from "react";

type ProgrammeBlock = { label: string; weeks: string; key: string };

const pillarColors: Record<string, { border: string; bg: string; dot: string }> = {
  nutrition: { border: "#0ba5ec", bg: "#f0f9ff", dot: "#0ba5ec" },
  recovery: { border: "#a855f7", bg: "#f8f5ff", dot: "#a855f7" },
  training: { border: "#22c55e", bg: "#ecfdf3", dot: "#22c55e" },
  resilience: { border: "#f97316", bg: "#fff7ed", dot: "#f97316" },
};

type ProgrammeCalendarProps = {
  programmeStart?: string | null;
  programmeBlocks: ProgrammeBlock[];
  programmeLengthDays?: number;
};

const weekLabels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

const toMonthKey = (date: Date) => `${date.getFullYear()}-${date.getMonth()}`;

export default function ProgrammeCalendar({
  programmeStart,
  programmeBlocks,
  programmeLengthDays = 84,
}: ProgrammeCalendarProps) {
  const startDate = programmeStart ? new Date(programmeStart) : null;
  const days = useMemo(() => {
    if (!startDate || Number.isNaN(startDate.getTime())) return [];
    return Array.from({ length: programmeLengthDays }, (_, idx) => {
      const date = new Date(startDate.getTime() + idx * 24 * 60 * 60 * 1000);
      const week = Math.floor(idx / 7) + 1;
      let key = "nutrition";
      if (week >= 4 && week <= 6) key = "recovery";
      if (week >= 7 && week <= 9) key = "training";
      if (week >= 10) key = "resilience";
      return { date, key };
    });
  }, [programmeLengthDays, startDate]);

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
          const palette = pillarColors[block.key] || { border: "#e4e7ec", bg: "#f8fafc", dot: "#98a2b3" };
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
                    const palette = pillarColors[item.key] || { border: "#e4e7ec", bg: "#f8fafc", dot: "#98a2b3" };
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
