"use client";

import { useEffect, useState } from "react";
import type { PillarTrackerSummaryResponse } from "@/lib/api";
import { dispatchPillarTrackerOverallScore } from "@/lib/pillarTrackerSummary";
import LatestAssessmentPanel from "./assessment/[userId]/chat/LatestAssessmentPanel";

type CoachHomeTrackerPanelProps = {
  userId: string;
  initialSummary: PillarTrackerSummaryResponse | null;
  initialAssessmentReviewed?: boolean;
  initialInteractionDaysCount?: number | null;
};

export default function CoachHomeTrackerPanel({
  userId,
  initialSummary,
  initialAssessmentReviewed = false,
  initialInteractionDaysCount = null,
}: CoachHomeTrackerPanelProps) {
  const [summary, setSummary] = useState<PillarTrackerSummaryResponse | null>(initialSummary);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    dispatchPillarTrackerOverallScore(summary);
  }, [summary]);

  useEffect(() => {
    if (summary) return;
    let cancelled = false;
    const loadSummary = async () => {
      try {
        const res = await fetch(`/api/pillar-tracker/summary?userId=${encodeURIComponent(userId)}`, {
          method: "GET",
          cache: "no-store",
        });
        const text = await res.text().catch(() => "");
        if (!res.ok) {
          throw new Error(text || "Failed to load check-in cards.");
        }
        const payload = (text ? JSON.parse(text) : {}) as PillarTrackerSummaryResponse;
        if (!cancelled) {
          setSummary(payload);
          setError(null);
        }
      } catch (loadError) {
        if (!cancelled) {
          setError(loadError instanceof Error ? loadError.message : String(loadError));
        }
      }
    };
    void loadSummary();
    return () => {
      cancelled = true;
    };
  }, [summary, userId]);

  if (summary) {
    return (
      <LatestAssessmentPanel
        userId={userId}
        initialSummary={summary}
        initialAssessmentReviewed={initialAssessmentReviewed}
        initialInteractionDaysCount={initialInteractionDaysCount}
      />
    );
  }

  return (
    <div className="flex h-full min-h-0 items-center justify-center px-6 pb-28 text-center">
      <p className="max-w-sm text-[1.05rem] leading-7 text-[var(--text-secondary)]">
        {error ? "Check-in cards are not available yet. Please try again shortly." : "Loading your check-in cards..."}
      </p>
    </div>
  );
}
