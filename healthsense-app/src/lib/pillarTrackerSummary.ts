import type { PillarTrackerSummaryResponse } from "@/lib/api";

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
