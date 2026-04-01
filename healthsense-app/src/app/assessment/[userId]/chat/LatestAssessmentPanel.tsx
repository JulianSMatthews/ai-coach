"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type {
  // Keep tracker responses local to this panel.
  PillarTrackerDetailResponse,
  PillarTrackerPillar,
  PillarTrackerSummaryResponse,
} from "@/lib/api";
import { applyThemePreference, readStoredThemePreference } from "@/lib/theme";
import { getPillarPalette } from "@/lib/pillars";
import { ScoreRing } from "@/components/ui";
import LeadAssessmentBranding from "./LeadAssessmentBranding";

type LatestAssessmentPanelProps = {
  userId: string;
  initialSummary: PillarTrackerSummaryResponse;
  initialAssessmentCombinedScore?: number | null;
  initialAssessmentReviewed?: boolean;
};

type TrackerReturnSurface = "tracking" | "habits" | "insight" | "ask";
type MorningSequenceState = "idle" | "in_progress" | "completed";
type DisplayTheme = "light" | "dark";

const PILLAR_ORDER = ["nutrition", "training", "resilience", "recovery"];
const HEALTHSENSE_ORANGE = "#c54817";
const MORNING_SEQUENCE_STORAGE_PREFIX = "hs:morning-sequence-complete";

function isDailyCheckInComplete(summary?: PillarTrackerSummaryResponse | null): boolean {
  if (!summary) return false;
  if (summary.today_complete === true) return true;
  const totalPillars = Number(summary.total_pillars);
  const completedPillars = Number(summary.today_completed_pillars_count);
  if (Number.isFinite(totalPillars) && totalPillars > 0 && Number.isFinite(completedPillars)) {
    return completedPillars >= totalPillars;
  }
  const pillars = Array.isArray(summary.pillars) ? summary.pillars : [];
  return pillars.length > 0 && pillars.every((pillar) => pillar?.today_complete === true);
}

function readMorningSequenceState(
  userId: string,
  dayToken: string | null | undefined,
): MorningSequenceState {
  if (typeof window === "undefined") return "idle";
  const normalizedUserId = String(userId || "").trim();
  const normalizedDayToken = String(dayToken || "").trim();
  if (!normalizedUserId || !normalizedDayToken) return "idle";
  try {
    const raw = String(
      window.localStorage.getItem(
        `${MORNING_SEQUENCE_STORAGE_PREFIX}:${normalizedUserId}:${normalizedDayToken}`,
      ) || "",
    )
      .trim()
      .toLowerCase();
    if (raw === "completed" || raw === "1") return "completed";
    if (raw === "in_progress") return "in_progress";
    return "idle";
  } catch {
    return "idle";
  }
}

function resolveSummaryPanelVisible(
  summary: PillarTrackerSummaryResponse,
  sequenceState: MorningSequenceState,
): boolean {
  if (sequenceState === "completed") return true;
  if (sequenceState === "in_progress") return false;
  return isDailyCheckInComplete(summary);
}

function resolveCurrentDisplayTheme(): DisplayTheme {
  if (typeof document !== "undefined") {
    const resolved = String(document.documentElement.dataset.theme || "").trim().toLowerCase();
    if (resolved === "light" || resolved === "dark") {
      return resolved;
    }
  }
  const stored = readStoredThemePreference();
  return stored === "light" ? "light" : "dark";
}

function sortPillars(pillars: PillarTrackerPillar[]): PillarTrackerPillar[] {
  return [...pillars].sort((a, b) => {
    const left = PILLAR_ORDER.indexOf(String(a.pillar_key || "").trim().toLowerCase());
    const right = PILLAR_ORDER.indexOf(String(b.pillar_key || "").trim().toLowerCase());
    return (left === -1 ? 99 : left) - (right === -1 ? 99 : right);
  });
}

function normalizeError(text: string, fallback: string): string {
  if (!text) return fallback;
  try {
    const parsed = JSON.parse(text) as { error?: string };
    return String(parsed.error || fallback);
  } catch {
    return text;
  }
}

function resolveScore(value?: number | null): number | null {
  const resolved = Number(value);
  if (!Number.isFinite(resolved)) return null;
  return Math.max(0, Math.min(100, Math.round(resolved)));
}

function resolvePillarDisplayScore(pillar: PillarTrackerPillar): number | null {
  return resolveScore(pillar.score);
}

function resolvePillarSource(pillar: PillarTrackerPillar): "tracker" | "assessment" {
  return resolveScore(pillar.tracker_score) !== null ? "tracker" : "assessment";
}

function circleDayTone(status?: string | null, isActive?: boolean): string {
  const activeRing = isActive ? " ring-1 ring-[#d9cdbb]" : "";
  if (status === "success") return `border-[#d5e8bf] bg-[#f2fae8] text-[#335f16]${activeRing}`;
  if (status === "warning") return `border-[#f2dccb] bg-[#fff4ea] text-[#8a5a1a]${activeRing}`;
  if (status === "danger") return `border-[#efc4b6] bg-[#fff0eb] text-[#9b3218]${activeRing}`;
  return `border-[#ece5d9] bg-white text-[#8c7f70]${activeRing}`;
}

function completeDayTone(complete?: boolean, score?: number | null, isToday?: boolean): string {
  if (complete && Number.isFinite(Number(score))) {
    const resolved = Number(score);
    if (resolved >= 80) return "border-[#d5e8bf] bg-[#f2fae8] text-[#335f16]";
    if (resolved >= 40) return "border-[#f2dccb] bg-[#fff4ea] text-[#8a5a1a]";
    return "border-[#efc4b6] bg-[#fff0eb] text-[#9b3218]";
  }
  if (isToday) return "border-[#f3d8c9] bg-[#fff5ef] text-[#8a3e1a]";
  return "border-[#ece5d9] bg-white text-[#8c7f70]";
}

function CombinedLogoRing({ value }: { value: number }) {
  const pct = Math.max(0, Math.min(1, value / 100));
  const size = 84;
  const stroke = 8;
  const radius = (size - stroke) / 2;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference * (1 - pct);
  return (
    <div className="relative flex h-[84px] w-[84px] items-center justify-center">
      <svg width={size} height={size} className="rotate-[-90deg]">
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          stroke="rgba(197,72,23,0.18)"
          strokeWidth={stroke}
          fill="none"
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          stroke={HEALTHSENSE_ORANGE}
          strokeWidth={stroke}
          fill="none"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          strokeLinecap="round"
        />
      </svg>
      <div className="absolute flex h-[60px] w-[60px] items-center justify-center rounded-full bg-white">
        <LeadAssessmentBranding
          titleLines={[]}
          logoClassName="h-8 w-8"
        />
      </div>
    </div>
  );
}

function WeeklyScoreRing({ value, tone, compact = false }: { value?: number | null; tone: string; compact?: boolean }) {
  const resolved = resolveScore(value);
  if (resolved !== null) {
    return (
      <div className={compact ? "origin-center scale-[0.78] sm:scale-100" : ""}>
        <ScoreRing value={resolved} tone={tone} />
      </div>
    );
  }
  return (
    <div className={compact ? "origin-center scale-[0.78] sm:scale-100" : ""}>
      <div className="relative flex h-[84px] w-[84px] items-center justify-center">
        <div className="h-[84px] w-[84px] rounded-full border-[8px] border-[#efe7db]" />
        <span className="absolute text-lg font-semibold text-[#8c7f70]">—</span>
      </div>
    </div>
  );
}

function HabitStepsIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      className="h-5 w-5 text-[var(--accent)]"
      aria-hidden="true"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M9 6h10" />
      <path d="M9 12h10" />
      <path d="M9 18h10" />
      <path d="M4 6l1.5 1.5L7.5 5" />
      <path d="M4 12l1.5 1.5L7.5 11" />
      <path d="M4 18l1.5 1.5L7.5 17" />
    </svg>
  );
}

function InsightIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      className="h-5 w-5 text-[var(--accent)]"
      aria-hidden="true"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M12 3a7 7 0 0 0-4 12.7c.6.4 1 1 1.2 1.7h5.6c.2-.7.6-1.3 1.2-1.7A7 7 0 0 0 12 3Z" />
      <path d="M9.5 21h5" />
      <path d="M10 18.5h4" />
    </svg>
  );
}

function GiaMessageIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      className="h-5 w-5 text-[var(--accent)]"
      aria-hidden="true"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M6 18l-3 3V7a3 3 0 0 1 3-3h12a3 3 0 0 1 3 3v8a3 3 0 0 1-3 3H6Z" />
      <path d="M8 9h8" />
      <path d="M8 13h5" />
    </svg>
  );
}

export default function LatestAssessmentPanel({
  userId,
  initialSummary,
  initialAssessmentCombinedScore = null,
  initialAssessmentReviewed = false,
}: LatestAssessmentPanelProps) {
  const [summary, setSummary] = useState<PillarTrackerSummaryResponse>(initialSummary);
  const [summaryPanelVisible, setSummaryPanelVisible] = useState(
    () => resolveSummaryPanelVisible(initialSummary, readMorningSequenceState(userId, initialSummary.today)),
  );
  const [displayTheme, setDisplayTheme] = useState<DisplayTheme>("dark");
  const [togglingDisplay, setTogglingDisplay] = useState(false);
  const [selectedPillarKey, setSelectedPillarKey] = useState<string | null>(null);
  const [detail, setDetail] = useState<PillarTrackerDetailResponse | null>(null);
  const [draft, setDraft] = useState<Record<string, number>>({});
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [saving, setSaving] = useState(false);
  const [guidedTrackingActive, setGuidedTrackingActive] = useState(false);
  const [trackerReturnSurface, setTrackerReturnSurface] = useState<TrackerReturnSurface | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [assessmentReviewed, setAssessmentReviewed] = useState(initialAssessmentReviewed);
  const [assessmentReviewSyncStarted, setAssessmentReviewSyncStarted] = useState(initialAssessmentReviewed);
  const summaryPanelRef = useRef<HTMLElement | null>(null);

  const pillars = sortPillars(Array.isArray(summary.pillars) ? summary.pillars : []);
  const orderedPillarKeys = pillars
    .map((pillar) => String(pillar.pillar_key || "").trim().toLowerCase())
    .filter((pillarKey) => Boolean(pillarKey));
  const resolveNextPillarKey = (pillarKey: string): string | null => {
    const normalizedPillarKey = String(pillarKey || "").trim().toLowerCase();
    const currentIndex = orderedPillarKeys.indexOf(normalizedPillarKey);
    if (currentIndex < 0) {
      return orderedPillarKeys[0] || null;
    }
    return orderedPillarKeys[currentIndex + 1] || null;
  };
  const hasTrackerScores = pillars.some((pillar) => resolvePillarSource(pillar) === "tracker");
  const combinedScore = (() => {
    if (!hasTrackerScores) {
      const assessmentCombined = resolveScore(initialAssessmentCombinedScore);
      if (assessmentCombined !== null) {
        return assessmentCombined;
      }
    }
    const scores = pillars
      .map((pillar) => resolvePillarDisplayScore(pillar))
      .filter((score): score is number => score !== null);
    if (!scores.length) return 0;
    return Math.round(scores.reduce((total, score) => total + score, 0) / scores.length);
  })();
  const concepts = Array.isArray(detail?.concepts) ? detail?.concepts : [];
  const canSave =
    !saving &&
    concepts.length > 0 &&
    concepts.every((concept) => {
      const conceptKey = String(concept.concept_key || "").trim();
      return conceptKey && Number.isFinite(Number(draft[conceptKey]));
    });
  const activeDate = String(detail?.pillar?.active_date || detail?.pillar?.today || "").trim();
  const activeLabel = String(detail?.pillar?.active_label || "").trim();
  const currentDate = String(detail?.pillar?.current_date || "").trim();
  const savingPastDay = Boolean(activeDate && currentDate && activeDate !== currentDate);
  const viewingCurrentWeek = detail?.pillar?.is_current_week !== false;
  const canEditActiveWeek = detail?.pillar?.is_editable !== false;
  const trackerScoreLabel =
    detail?.pillar?.tracker_score !== null && detail?.pillar?.tracker_score !== undefined
      ? `${detail?.pillar?.tracker_score}/100 ${viewingCurrentWeek ? "this week so far" : "last week"}`
      : viewingCurrentWeek
        ? savingPastDay
          ? `Complete ${activeLabel || "yesterday"} to update this week's score`
          : "Complete today to start this week's score"
        : "No completed tracker days last week";
  const closeTrackerLabel =
    trackerReturnSurface === "tracking"
      ? "Back to daily check-in"
      : "Close";
  const displayLabel = displayTheme === "dark" ? "light" : "dark";
  const displayButtonClassName =
    displayLabel === "dark"
      ? "rounded-full border border-[#2f3542] bg-[#1c2230] px-4 py-2 text-xs font-semibold text-white shadow-[0_10px_24px_-18px_rgba(12,18,28,0.9)] disabled:cursor-not-allowed disabled:opacity-60"
      : "rounded-full border border-[#d9cdbb] bg-white px-4 py-2 text-xs font-semibold text-[#5d5348] shadow-[0_10px_24px_-18px_rgba(93,83,72,0.45)] disabled:cursor-not-allowed disabled:opacity-60";

  const toggleDisplayTheme = useCallback(async () => {
    if (togglingDisplay) return;
    const currentTheme = resolveCurrentDisplayTheme();
    const nextTheme: DisplayTheme = currentTheme === "dark" ? "light" : "dark";
    setTogglingDisplay(true);
    setDisplayTheme(nextTheme);
    applyThemePreference(nextTheme, true);
    try {
      const res = await fetch("/api/preferences", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          userId,
          theme: nextTheme,
        }),
      });
      if (!res.ok) {
        throw new Error("Failed to save display preference.");
      }
    } catch {
      setDisplayTheme(currentTheme);
      applyThemePreference(currentTheme, true);
    } finally {
      setTogglingDisplay(false);
    }
  }, [togglingDisplay, userId]);

  useEffect(() => {
    setSummaryPanelVisible(
      resolveSummaryPanelVisible(summary, readMorningSequenceState(userId, summary.today)),
    );
  }, [summary, userId]);

  useEffect(() => {
    setDisplayTheme(resolveCurrentDisplayTheme());
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const onSummaryVisibilityChange = (event: Event) => {
      const detail = (event as CustomEvent<{ visible?: boolean }>).detail;
      setSummaryPanelVisible(Boolean(detail?.visible));
    };
    window.addEventListener("healthsense-score-panel-visibility", onSummaryVisibilityChange as EventListener);
    return () => {
      window.removeEventListener("healthsense-score-panel-visibility", onSummaryVisibilityChange as EventListener);
    };
  }, []);

  useEffect(() => {
    if (!summaryPanelVisible) return;
    const panel = summaryPanelRef.current;
    if (!panel || typeof panel.scrollIntoView !== "function") return;
    const frame = window.requestAnimationFrame(() => {
      panel.scrollIntoView({ behavior: "smooth", block: "start" });
    });
    return () => {
      window.cancelAnimationFrame(frame);
    };
  }, [summaryPanelVisible]);

  useEffect(() => {
    if (!summaryPanelVisible || assessmentReviewed || assessmentReviewSyncStarted) return;
    let cancelled = false;
    setAssessmentReviewSyncStarted(true);
    const syncAssessmentReview = async () => {
      try {
        const params = new URLSearchParams({ userId });
        const res = await fetch(`/api/assessment/report?${params.toString()}`, {
          method: "GET",
          cache: "no-store",
        });
        if (res.ok && !cancelled) {
          setAssessmentReviewed(true);
        }
      } catch {
        // Ignore silent review sync failures; the score view still works without this marker.
      }
    };
    void syncAssessmentReview();
    return () => {
      cancelled = true;
    };
  }, [assessmentReviewed, assessmentReviewSyncStarted, summaryPanelVisible, userId]);

  const refreshSummary = async () => {
    const res = await fetch(`/api/pillar-tracker/summary?userId=${encodeURIComponent(userId)}`, {
      method: "GET",
      cache: "no-store",
    });
    const text = await res.text().catch(() => "");
    if (!res.ok) {
      throw new Error(normalizeError(text, "Failed to refresh the pillar tracker summary."));
    }
    const payload = (text ? (JSON.parse(text) as PillarTrackerSummaryResponse) : {}) as PillarTrackerSummaryResponse;
    setSummary(payload);
  };

  const loadTrackerDetail = useCallback(async (pillarKey: string, anchorDate?: string) => {
    setLoadingDetail(true);
    setDetailError(null);
    setSaveError(null);
    try {
      const params = new URLSearchParams({ userId });
      if (anchorDate) {
        params.set("anchorDate", anchorDate);
      }
      const res = await fetch(`/api/pillar-tracker/${encodeURIComponent(pillarKey)}?${params.toString()}`, {
        method: "GET",
        cache: "no-store",
      });
      const text = await res.text().catch(() => "");
      if (!res.ok) {
        throw new Error(normalizeError(text, "Failed to load the pillar tracker."));
      }
      const payload = (text ? (JSON.parse(text) as PillarTrackerDetailResponse) : {}) as PillarTrackerDetailResponse;
      setDetail(payload);
      const nextDraft: Record<string, number> = {};
      (payload.concepts || []).forEach((concept) => {
        const conceptKey = String(concept.concept_key || "").trim();
        const value = Number(concept.value);
        if (conceptKey && Number.isFinite(value)) {
          nextDraft[conceptKey] = value;
        }
      });
      setDraft(nextDraft);
    } catch (error) {
      setDetailError(error instanceof Error ? error.message : String(error));
    } finally {
      setLoadingDetail(false);
    }
  }, [userId]);

  const openTracker = useCallback(async (
    pillarKey: string,
    anchorDate?: string,
    options?: { guided?: boolean; returnSurface?: TrackerReturnSurface | null },
  ) => {
    const normalizedPillarKey = String(pillarKey || "").trim().toLowerCase();
    if (!normalizedPillarKey) return;
    const guided = Boolean(options?.guided);
    setGuidedTrackingActive(guided);
    setTrackerReturnSurface(options?.returnSurface ?? null);
    setSelectedPillarKey(normalizedPillarKey);
    setDetail(null);
    setDraft({});
    setDetailError(null);
    setSaveError(null);
    if (guided && typeof window !== "undefined") {
      window.dispatchEvent(
        new CustomEvent("healthsense-home-surface", {
          detail: {
            surface: "tracking",
          },
        }),
      );
    }
    await loadTrackerDetail(normalizedPillarKey, anchorDate);
  }, [loadTrackerDetail]);

  const closeTracker = () => {
    setSelectedPillarKey(null);
    setGuidedTrackingActive(false);
    setTrackerReturnSurface(null);
    setDetail(null);
    setDraft({});
    setDetailError(null);
    setSaveError(null);
    setLoadingDetail(false);
    setSaving(false);
  };

  const saveTracker = async () => {
    if (!detail?.pillar?.pillar_key || !canSave) return;
    setSaving(true);
    setSaveError(null);
    try {
      const entries = concepts.map((concept) => ({
        concept_key: concept.concept_key,
        value: draft[String(concept.concept_key || "").trim()],
      }));
      const res = await fetch(`/api/pillar-tracker/${encodeURIComponent(String(detail.pillar.pillar_key))}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          userId,
          score_date: activeDate || detail.pillar.today,
          entries,
        }),
      });
      const text = await res.text().catch(() => "");
      if (!res.ok) {
        throw new Error(normalizeError(text, "Failed to save the pillar tracker."));
      }
      if (typeof window !== "undefined") {
        window.dispatchEvent(
          new CustomEvent("healthsense-tracker-updated", {
            detail: {
              pillarKey: String(detail.pillar.pillar_key || "").trim().toLowerCase(),
              scoreDate: activeDate || detail.pillar.today || null,
              guided: guidedTrackingActive,
            },
          }),
        );
      }
      await refreshSummary().catch(() => undefined);
      const currentPillarKey = String(detail.pillar.pillar_key || "").trim().toLowerCase();
      const nextPillarKey = guidedTrackingActive ? resolveNextPillarKey(currentPillarKey) : null;
      if (nextPillarKey) {
        await openTracker(nextPillarKey, undefined, { guided: true });
        return;
      }
      if (guidedTrackingActive && typeof window !== "undefined") {
        window.dispatchEvent(
          new CustomEvent("healthsense-home-surface", {
            detail: {
              surface: "habits",
            },
          }),
        );
      } else if (trackerReturnSurface && typeof window !== "undefined") {
        window.dispatchEvent(
          new CustomEvent("healthsense-home-surface", {
            detail: {
              surface: trackerReturnSurface,
            },
          }),
        );
      }
      closeTracker();
    } catch (error) {
      setSaveError(error instanceof Error ? error.message : String(error));
    } finally {
      setSaving(false);
    }
  };

  const openDailyMenuSurface = (surface: "habits" | "insight" | "ask") => {
    if (typeof window !== "undefined") {
      window.dispatchEvent(
        new CustomEvent("healthsense-home-surface", {
          detail: {
            surface,
            source: "summary",
          },
        }),
      );
      window.scrollTo({ top: 0, behavior: "smooth" });
    }
  };

  useEffect(() => {
    if (typeof window === "undefined") return;
    const onOpenTracker = (event: Event) => {
      const detail = (event as CustomEvent<{
        pillarKey?: string;
        guided?: boolean;
        returnSurface?: TrackerReturnSurface | null;
      }>).detail;
      const requestedPillarKey = String(detail?.pillarKey || "").trim().toLowerCase();
      const nextPillarKey = requestedPillarKey || orderedPillarKeys[0] || "";
      if (!nextPillarKey) return;
      void openTracker(nextPillarKey, undefined, {
        guided: detail?.guided !== false,
        returnSurface: detail?.returnSurface ?? null,
      });
    };
    window.addEventListener("healthsense-open-tracker", onOpenTracker as EventListener);
    return () => {
      window.removeEventListener("healthsense-open-tracker", onOpenTracker as EventListener);
    };
  }, [orderedPillarKeys, openTracker]);

  return (
    <>
      {summaryPanelVisible ? (
        <section
          ref={summaryPanelRef}
          className="rounded-[28px] border border-[#e7e1d6] bg-[#fffaf3] px-4 py-5 shadow-[0_30px_80px_-60px_rgba(30,27,22,0.45)] sm:px-5 sm:py-6"
        >
          <div className="mb-4 flex justify-end">
            <button
              type="button"
              onClick={() => void toggleDisplayTheme()}
              disabled={togglingDisplay}
              className={displayButtonClassName}
            >
              {displayLabel}
            </button>
          </div>
          <div className="relative">
            <div className="grid grid-cols-2 gap-3">
              {pillars.map((pillar) => {
                const pillarKey = String(pillar.pillar_key || "").trim().toLowerCase();
                const palette = getPillarPalette(pillarKey);
                const score = resolvePillarDisplayScore(pillar);
                return (
                  <button
                    key={pillarKey}
                    type="button"
                    onClick={() => void openTracker(pillarKey)}
                    className="rounded-2xl border border-[#efe7db] bg-white px-3 py-4 text-left transition hover:border-[#dccfbe]"
                  >
                    <div className="flex flex-col items-center text-center">
                      <WeeklyScoreRing value={score} tone={palette.accent} />
                      <p className="mt-3 text-sm font-semibold text-[#1e1b16]">{pillar.label}</p>
                    </div>
                  </button>
                );
              })}
            </div>

            <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
              <div className="rounded-full" aria-hidden="true">
                <div className="relative">
                  <CombinedLogoRing value={combinedScore} />
                </div>
              </div>
            </div>
          </div>
          <div className="mt-5 space-y-3">
            <button
              type="button"
              onClick={() => openDailyMenuSurface("habits")}
              className="flex min-h-[6.25rem] w-full flex-col items-start justify-center rounded-[28px] border border-[#d9cdbb] bg-white px-5 py-4 text-left shadow-[0_24px_40px_-36px_rgba(30,27,22,0.4)]"
            >
              <div className="flex items-center gap-3">
                <HabitStepsIcon />
                <span className="text-base font-semibold text-[#1e1b16]">Habit steps for the day</span>
              </div>
            </button>
            <button
              type="button"
              onClick={() => openDailyMenuSurface("insight")}
              className="flex min-h-[6.25rem] w-full flex-col items-start justify-center rounded-[28px] border border-[#d9cdbb] bg-white px-5 py-4 text-left shadow-[0_24px_40px_-36px_rgba(30,27,22,0.4)]"
            >
              <div className="flex items-center gap-3">
                <InsightIcon />
                <span className="text-base font-semibold text-[#1e1b16]">Insight of the day</span>
              </div>
            </button>
            <button
              type="button"
              onClick={() => openDailyMenuSurface("ask")}
              className="flex min-h-[6.25rem] w-full flex-col items-start justify-center rounded-[28px] border border-[#d9cdbb] bg-white px-5 py-4 text-left shadow-[0_24px_40px_-36px_rgba(30,27,22,0.4)]"
            >
              <div className="flex items-center gap-3">
                <GiaMessageIcon />
                <span className="text-base font-semibold text-[#1e1b16]">Gia&apos;s message of the day</span>
              </div>
            </button>
          </div>
        </section>
      ) : null}

      {selectedPillarKey ? (
        <div className="fixed inset-0 z-50 flex items-stretch justify-center bg-black/40 sm:items-center sm:px-3 sm:py-3">
          <div className="flex h-[100dvh] max-h-[100dvh] w-full max-w-2xl flex-col overflow-hidden bg-white pt-[env(safe-area-inset-top)] pb-[env(safe-area-inset-bottom)] shadow-[0_30px_80px_-60px_rgba(30,27,22,0.6)] sm:h-auto sm:max-h-[92vh] sm:rounded-[28px] sm:border sm:border-[#e7e1d6] sm:pt-0 sm:pb-0">
            <div className="shrink-0 border-b border-[#efe7db] bg-white px-4 py-4 sm:px-5">
              <div className="min-w-0 space-y-1">
                <p className="text-xs uppercase tracking-[0.22em] text-[#6b6257]">
                  {(detail?.pillar?.label || selectedPillarKey.replace(/_/g, " ")) +
                    (viewingCurrentWeek
                      ? savingPastDay
                        ? ` · Catching up ${activeLabel || "yesterday"}`
                        : " · Tracking today"
                      : " · Last week results")}
                </p>
                <p className="text-sm text-[#6b6257]">{trackerScoreLabel}</p>
                {detail?.pillar?.completed_days_count !== undefined || detail?.pillar?.streak_days !== undefined ? (
                  <p className="text-xs text-[#8c7f70]">
                    {`${detail?.pillar?.completed_days_count || 0}/7 days complete · ${detail?.pillar?.streak_days || 0} day check-in streak`}
                  </p>
                ) : null}
              </div>
            </div>

            <div className="flex-1 overflow-y-auto px-4 py-4 sm:px-5">
              {loadingDetail ? <p className="text-sm text-[#6b6257]">Loading tracker…</p> : null}
              {detailError ? <p className="text-sm text-[#8a3e1a]">{detailError}</p> : null}

              {detail && !loadingDetail ? (
                <div className="space-y-5">
                  {(detail.editable_dates || []).length > 1 ? (
                    <div className="flex flex-wrap gap-2">
                      {(detail.editable_dates || []).map((item) => {
                        const itemDate = String(item.date || "").trim();
                        const active = Boolean(item.is_active);
                        return (
                          <button
                            key={itemDate}
                            type="button"
                            disabled={!itemDate || active || saving}
                            onClick={() =>
                              void openTracker(
                                String(detail.pillar?.pillar_key || selectedPillarKey || ""),
                                itemDate,
                                {
                                  guided: guidedTrackingActive,
                                  returnSurface: trackerReturnSurface,
                                },
                              )
                            }
                            className={`rounded-full border px-3 py-2 text-xs font-semibold uppercase tracking-[0.16em] ${
                              active
                                ? "border-[#d6c3ab] bg-[#f6ede3] text-[#5d472d]"
                                : "border-[#d9cdbb] bg-white text-[#5d5348]"
                            } disabled:cursor-default disabled:opacity-100`}
                          >
                            {item.label}
                          </button>
                        );
                      })}
                    </div>
                  ) : null}

                  <div className="rounded-2xl border border-[#efe7db] bg-[#fffaf3] px-4 py-4">
                    <p className="text-xs uppercase tracking-[0.22em] text-[#6b6257]">
                      {viewingCurrentWeek ? "This week" : "Last week"}
                    </p>
                    <div className="mt-3 grid grid-cols-7 gap-2">
                      {(detail.days || []).map((day) => (
                        <div
                          key={day.date}
                          className={`rounded-xl border px-2 py-2 text-center text-[11px] ${completeDayTone(day.complete, day.score, day.is_today)}`}
                        >
                          <p className="font-semibold">{day.label}</p>
                          <p className="mt-1">{day.complete ? day.score ?? "Done" : day.is_today ? "Today" : "—"}</p>
                        </div>
                      ))}
                    </div>
                  </div>

                  {(detail.concepts || []).map((concept) => {
                    const conceptKey = String(concept.concept_key || "").trim();
                    const selectedValue = draft[conceptKey];
                    const targetLabel = String(concept.target_label || "").trim();
                    const okrStatusLabel = String(concept.okr_status_label || "").trim();
                    const okrStatusDetail = String(concept.okr_status_detail || "").trim();
                    const showInlineOkrProgress = Boolean(okrStatusDetail);
                    const okrStatusTone =
                      concept.okr_on_track === true
                        ? "text-[#4e7a1f]"
                        : concept.okr_on_track === false
                          ? "text-[#b55b1d]"
                          : "text-[#6b6257]";
                    return (
                      <div key={conceptKey} className="rounded-2xl border border-[#efe7db] bg-white px-4 py-4">
                        <div className="flex items-start justify-between gap-3">
                          <div>
                            <p className="text-sm font-semibold text-[#1e1b16]">{concept.label}</p>
                            <p className="mt-1 text-xs uppercase tracking-[0.18em] text-[#8c7f70]">{concept.helper}</p>
                            {targetLabel || okrStatusLabel ? (
                              <p className="mt-2 text-xs text-[#6b6257]">
                                {targetLabel}
                                {targetLabel && showInlineOkrProgress ? " · " : null}
                                {showInlineOkrProgress ? okrStatusDetail : null}
                                {(targetLabel || showInlineOkrProgress) && okrStatusLabel ? " · " : null}
                                {okrStatusLabel ? (
                                  <span className={`font-medium ${okrStatusTone}`}>{okrStatusLabel}</span>
                                ) : null}
                              </p>
                            ) : null}
                          </div>
                          <p className="text-xs text-[#8c7f70]">{`${concept.streak_days || 0} day streak`}</p>
                        </div>

                        <div className="mt-3 grid grid-cols-7 gap-2">
                          {(concept.week || []).map((day) => (
                            <div
                              key={`${conceptKey}-${day.date}`}
                              className={`rounded-xl border px-2 py-2 text-center text-[11px] ${circleDayTone(day.daily_status, day.is_active)}`}
                            >
                              <p className="font-semibold">{day.label}</p>
                              <p className="mt-1 truncate">{day.value_label || "—"}</p>
                            </div>
                          ))}
                        </div>

                        <div className="mt-3 flex flex-wrap gap-2">
                          {canEditActiveWeek
                            ? (concept.options || []).map((option) => {
                                const value = Number(option.value);
                                const active = Number.isFinite(value) && value === selectedValue;
                                return (
                                  <button
                                    key={`${conceptKey}-${option.label}-${option.value}`}
                                    type="button"
                                    onClick={() =>
                                      setDraft((current) => ({
                                        ...current,
                                        [conceptKey]: value,
                                      }))
                                    }
                                    className={`rounded-full border px-3 py-2 text-xs font-semibold uppercase tracking-[0.16em] ${
                                      active
                                        ? "border-[var(--accent)] bg-[var(--accent)] text-white"
                                        : "border-[#d9cdbb] bg-white text-[#5d5348]"
                                    }`}
                                  >
                                    {option.label}
                                  </button>
                                );
                              })
                            : null}
                        </div>
                      </div>
                    );
                  })}

                  {saveError ? <p className="text-sm text-[#8a3e1a]">{saveError}</p> : null}
                </div>
                ) : null}
              </div>

            <div className="shrink-0 border-t border-[#efe7db] px-4 py-4 sm:px-5">
              {canEditActiveWeek ? (
                <div className="grid grid-cols-2 gap-2">
                  <button
                    type="button"
                    onClick={closeTracker}
                    className="rounded-full border border-[#d9cdbb] bg-white px-4 py-3 text-center text-xs font-semibold uppercase tracking-[0.18em] text-[#5d5348]"
                  >
                    {closeTrackerLabel}
                  </button>
                  <button
                    type="button"
                    onClick={() => void saveTracker()}
                    disabled={!canSave}
                    className="rounded-full border border-[var(--accent)] bg-[var(--accent)] px-4 py-3 text-center text-xs font-semibold uppercase tracking-[0.18em] text-white disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    {saving
                      ? "Saving tracker…"
                      : "Save"}
                  </button>
                </div>
              ) : (
                <button
                  type="button"
                  onClick={closeTracker}
                  className="w-full rounded-full border border-[#d9cdbb] bg-white px-4 py-3 text-center text-xs font-semibold uppercase tracking-[0.18em] text-[#5d5348]"
                >
                  {closeTrackerLabel}
                </button>
              )}
            </div>
          </div>
        </div>
      ) : null}
    </>
  );
}
