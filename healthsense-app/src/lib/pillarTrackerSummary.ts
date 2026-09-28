import type { PillarTrackerSummaryResponse, PillarTrackerDetailResponse } from "@/lib/api";

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
