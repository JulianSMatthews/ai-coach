import type { PillarTrackerSummaryResponse } from "@/lib/api";

export const PILLAR_TRACKER_OVERALL_SCORE_EVENT = "healthsense-overall-score-updated";

export function resolvePillarTrackerOverallScore(summary?: PillarTrackerSummaryResponse | null): number | null {
  const explicitScore = Number((summary as { overall_score?: number | null } | null | undefined)?.overall_score);
  if (Number.isFinite(explicitScore)) {
    return Math.max(0, Math.min(100, Math.round(explicitScore)));
  }
  const scores = (Array.isArray(summary?.pillars) ? summary.pillars : [])
    .map((pillar) => Number(pillar?.score))
    .filter((score) => Number.isFinite(score));
  if (!scores.length) return null;
  const average = scores.reduce((total, score) => total + score, 0) / scores.length;
  return Math.max(0, Math.min(100, Math.round(average)));
}

export function dispatchPillarTrackerOverallScore(summary?: PillarTrackerSummaryResponse | null): void {
  if (typeof window === "undefined") return;
  const overallScore = resolvePillarTrackerOverallScore(summary);
  if (overallScore === null) return;
  window.dispatchEvent(
    new CustomEvent(PILLAR_TRACKER_OVERALL_SCORE_EVENT, {
      detail: { overallScore },
    }),
  );
}
