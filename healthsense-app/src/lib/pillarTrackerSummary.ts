import type { PillarTrackerSummaryResponse, PillarTrackerDetailResponse, PillarTrackerConcept, PillarTrackerConceptWeekDay } from "@/lib/api";

export const PILLAR_TRACKER_OVERALL_SCORE_EVENT = "healthsense-overall-score-updated";

export function resolvePillarTrackerOverallScore(summary?: PillarTrackerSummaryResponse | null): number | null {
  if (summary && "overall_score" in summary && summary.overall_score == null) return null;
  const explicitScore = Number(summary?.overall_score);
  if (Number.isFinite(explicitScore)) {
    return Math.max(0, Math.min(100, Math.round(explicitScore)));
  }
  const scores = (Array.isArray(summary?.pillars) ? summary.pillars : [])
    .map((pillar) => pillar.tracker_score ?? pillar.score)
    .filter((score): score is number => score != null)
    .map(Number)
    .filter((score) => Number.isFinite(score));
  if (!scores.length) return null;
  const average = scores.reduce((total, score) => total + score, 0) / scores.length;
  return Math.max(0, Math.min(100, Math.round(average)));
}

export function dispatchPillarTrackerOverallScore(summary?: PillarTrackerSummaryResponse | null): void {
  if (typeof window === "undefined") return;
  const overallScore = resolvePillarTrackerOverallScore(summary);
  window.dispatchEvent(
    new CustomEvent(PILLAR_TRACKER_OVERALL_SCORE_EVENT, {
      detail: { overallScore },
    }),
  );
}

// Use the same historical score as the Last week view, without changing the
// current check-in/completion state supplied by the summary endpoint.
export async function resolveMondayCueScores(
  summary: PillarTrackerSummaryResponse,
  loadDetail: (pillarKey: string, anchorDate: string) => Promise<PillarTrackerDetailResponse>,
): Promise<PillarTrackerSummaryResponse> {
  const today = summary.today;
  if (!today || new Date(`${today}T12:00:00Z`).getUTCDay() !== 1) return summary;
  const pillars = await Promise.all((summary.pillars || []).map(async (pillar) => {
    if (pillar.today_complete === true || !pillar.pillar_key) return pillar;
    const previousWeek = pillar.checkin_options?.find((option) => option.is_last_week)?.date;
    if (!previousWeek) return pillar;
    try {
      const detail = await loadDetail(pillar.pillar_key, previousWeek);
      if (detail.pillar?.is_current_week !== false) return pillar;
      const score = detail.pillar.tracker_score ?? detail.pillar.score;
      if (score == null || !Number.isFinite(score)) return pillar;
      return { ...pillar, score, tracker_score: score, source: "tracker" };
    } catch {
      return pillar;
    }
  }));
  if (pillars.every((pillar, index) => pillar === summary.pillars?.[index])) return summary;
  return { ...summary, pillars, overall_score: resolvePillarTrackerOverallScore({ pillars }) };
}

export function resolveTrackerDetailDisplayScore(
  detail: PillarTrackerDetailResponse,
  summary: PillarTrackerSummaryResponse,
): number | null {
  const pillar = detail.pillar;
  const ownScore = pillar?.tracker_score ?? pillar?.score ?? null;
  const today = pillar?.current_date || summary.today;
  if (!today || pillar?.is_current_week === false || new Date(`${today}T12:00:00Z`).getUTCDay() !== 1) {
    return ownScore;
  }
  const homePillar = summary.pillars?.find((item) => item.pillar_key === pillar?.pillar_key);
  const todayComplete = detail.days?.find((day) => day.date === today)?.complete ?? homePillar?.today_complete;
  if (todayComplete === true) return ownScore;
  return homePillar?.tracker_score ?? homePillar?.score ?? ownScore;
}

export function resolveTrackerDayStatus(
  concept: PillarTrackerConcept,
  day: PillarTrackerConceptWeekDay,
): PillarTrackerConceptWeekDay["daily_status"] {
  // Weekly progress and daily success are different: a green day need not
  // complete the whole weekly target. Prefer the appropriate achievement flag.
  const achieved = concept.target_period === "day" ? day.target_met : day.target_reached;
  if (achieved === true) return "success";
  return day.daily_status;
}

function trackerDate(value?: string | null): Date | null {
  if (!value || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return null;
  const parsed = new Date(`${value}T12:00:00Z`);
  return Number.isFinite(parsed.getTime()) ? parsed : null;
}

export function formatTrackerWeekRange(start?: string | null, end?: string | null): string {
  const from = trackerDate(start), to = trackerDate(end);
  if (!from || !to) return "";
  const ordinal = (d: Date) => {
    const n = d.getUTCDate(), remainder = n % 100;
    const suffix = remainder >= 11 && remainder <= 13 ? "th" : ({ 1: "st", 2: "nd", 3: "rd" } as Record<number, string>)[n % 10] || "th";
    return `${n}${suffix}`;
  };
  const month = (d: Date) => d.toLocaleDateString("en-GB", { month: "long", timeZone: "UTC" });
  const year = (d: Date) => String(d.getUTCFullYear()).slice(-2);
  const sameYear = from.getUTCFullYear() === to.getUTCFullYear();
  const sameMonth = sameYear && from.getUTCMonth() === to.getUTCMonth();
  const left = `${ordinal(from)}${sameMonth ? "" : ` ${month(from)}`}${sameYear ? "" : ` ${year(from)}`}`;
  return `${left} - ${ordinal(to)} ${month(to)} ${year(to)}`;
}

export function trackerWeekNavigation(start?: string | null, today?: string | null): { previous: string | null; next: string | null } {
  const week = trackerDate(start), now = trackerDate(today);
  if (!week || !now) return { previous: null, next: null };
  const currentMonday = new Date(now);
  currentMonday.setUTCDate(now.getUTCDate() - (now.getUTCDay() + 6) % 7);
  const previous = new Date(week), next = new Date(week);
  previous.setUTCDate(week.getUTCDate() - 7);
  next.setUTCDate(week.getUTCDate() + 7);
  return { previous: previous.toISOString().slice(0, 10), next: next < currentMonday ? next.toISOString().slice(0, 10) : null };
}
