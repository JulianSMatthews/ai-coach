"use client";

import { useEffect, useRef, useState } from "react";
import type {
  // Keep tracker responses local to this panel.
  PillarTrackerDetailResponse,
  PillarTrackerPillar,
  PillarTrackerSummaryResponse,
} from "@/lib/api";
import { getPillarPalette } from "@/lib/pillars";
import { ScoreRing } from "@/components/ui";
import { applyThemePreference, normalizeThemePreference, type ThemePreference } from "@/lib/theme";
import type { AssessmentIntroAvatar } from "./AssessmentPromptCard";
import LeadAssessmentBranding from "./LeadAssessmentBranding";

type LatestAssessmentPanelProps = {
  userId: string;
  initialSummary: PillarTrackerSummaryResponse;
  initialAssessmentCombinedScore?: number | null;
  initialAssessmentReviewed?: boolean;
  autoOpenResults?: boolean;
  initialTheme?: string;
  appIntroAvatar?: AssessmentIntroAvatar | null;
  appIntroHelpVideos?: {
    habits?: AssessmentIntroAvatar | null;
    insight?: AssessmentIntroAvatar | null;
    ask?: AssessmentIntroAvatar | null;
    dailyTracking?: AssessmentIntroAvatar | null;
  } | null;
};

type IntroVideoKey = "intro" | "habits" | "insight" | "ask" | "dailyTracking";

const PILLAR_ORDER = ["nutrition", "training", "resilience", "recovery"];
const HEALTHSENSE_ORANGE = "#c54817";

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

function WeeklyScoreRing({ value, tone }: { value?: number | null; tone: string }) {
  const resolved = resolveScore(value);
  if (resolved !== null) {
    return <ScoreRing value={resolved} tone={tone} />;
  }
  return (
    <div className="relative flex h-[84px] w-[84px] items-center justify-center">
      <div className="h-[84px] w-[84px] rounded-full border-[8px] border-[#efe7db]" />
      <span className="absolute text-lg font-semibold text-[#8c7f70]">—</span>
    </div>
  );
}

export default function LatestAssessmentPanel({
  userId,
  initialSummary,
  initialAssessmentCombinedScore = null,
  initialAssessmentReviewed = false,
  autoOpenResults = false,
  initialTheme = "dark",
  appIntroAvatar = null,
  appIntroHelpVideos = null,
}: LatestAssessmentPanelProps) {
  const [summary, setSummary] = useState<PillarTrackerSummaryResponse>(initialSummary);
  const [scoreCardOpen, setScoreCardOpen] = useState(false);
  const [selectedIntroVideoKey, setSelectedIntroVideoKey] = useState<IntroVideoKey>("intro");
  const [selectedPillarKey, setSelectedPillarKey] = useState<string | null>(null);
  const [detail, setDetail] = useState<PillarTrackerDetailResponse | null>(null);
  const [draft, setDraft] = useState<Record<string, number>>({});
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [saving, setSaving] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [setupOpen, setSetupOpen] = useState(false);
  const [themePreference, setThemePreference] = useState<ThemePreference>(normalizeThemePreference(initialTheme));
  const [themeSaving, setThemeSaving] = useState(false);
  const [themeError, setThemeError] = useState<string | null>(null);
  const [assessmentReviewed, setAssessmentReviewed] = useState(initialAssessmentReviewed);
  const [assessmentReviewSyncStarted, setAssessmentReviewSyncStarted] = useState(initialAssessmentReviewed);
  const introVideoRef = useRef<HTMLVideoElement | null>(null);

  const pillars = sortPillars(Array.isArray(summary.pillars) ? summary.pillars : []);
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
  const scoreCardSubtitle = hasTrackerScores
    ? "Daily tracking scores now lead once you start logging."
    : "Your baseline scores before daily tracking";
  const scoreCardHelper = hasTrackerScores
    ? "Tracked pillars show daily scores. The rest stay on baseline until you log them."
    : null;
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
  const introVideoOptions = [
    { key: "intro" as const, label: "General", avatar: appIntroAvatar },
    { key: "habits" as const, label: "Habits", avatar: appIntroHelpVideos?.habits ?? null },
    { key: "insight" as const, label: "Insight", avatar: appIntroHelpVideos?.insight ?? null },
    { key: "ask" as const, label: "Ask", avatar: appIntroHelpVideos?.ask ?? null },
    {
      key: "dailyTracking" as const,
      label: "Tracking",
      avatar: appIntroHelpVideos?.dailyTracking ?? null,
    },
  ].filter((item) => Boolean(String(item.avatar?.url || "").trim()));
  const hasIntroMessage = introVideoOptions.length > 0;
  const defaultIntroVideoKey = introVideoOptions[0]?.key || "intro";
  const activeIntroVideo =
    introVideoOptions.find((item) => item.key === selectedIntroVideoKey) || introVideoOptions[0] || null;
  const activeIntroVideoKey = activeIntroVideo?.key || null;

  useEffect(() => {
    if (!scoreCardOpen || !activeIntroVideoKey) return;
    const videoEl = introVideoRef.current;
    if (!videoEl) return;
    try {
      videoEl.currentTime = 0;
    } catch {}
    void videoEl.play().catch(() => undefined);
  }, [activeIntroVideoKey, scoreCardOpen]);

  useEffect(() => {
    if (!autoOpenResults) return;
    setScoreCardOpen(true);
  }, [autoOpenResults]);

  useEffect(() => {
    if (!scoreCardOpen || assessmentReviewed || assessmentReviewSyncStarted) return;
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
  }, [assessmentReviewed, assessmentReviewSyncStarted, scoreCardOpen, userId]);

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

  const loadTrackerDetail = async (pillarKey: string, anchorDate?: string) => {
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
  };

  const openTracker = async (pillarKey: string, anchorDate?: string) => {
    setScoreCardOpen(false);
    setSelectedPillarKey(pillarKey);
    setDetail(null);
    setDraft({});
    setDetailError(null);
    setSaveError(null);
    await loadTrackerDetail(pillarKey, anchorDate);
  };

  const closeTracker = () => {
    setSelectedPillarKey(null);
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
            },
          }),
        );
      }
      closeTracker();
      void refreshSummary().catch(() => {});
    } catch (error) {
      setSaveError(error instanceof Error ? error.message : String(error));
    } finally {
      setSaving(false);
    }
  };

  const openScoreCard = () => {
    setSelectedIntroVideoKey(defaultIntroVideoKey);
    setSetupOpen(false);
    setScoreCardOpen(true);
  };

  const selectIntroVideo = (nextKey: IntroVideoKey) => {
    setSelectedIntroVideoKey(nextKey);
  };

  const saveThemePreference = async (nextThemeInput: string) => {
    const nextTheme = normalizeThemePreference(nextThemeInput);
    const previousTheme = themePreference;
    setThemePreference(nextTheme);
    setThemeSaving(true);
    setThemeError(null);
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
        const text = await res.text().catch(() => "");
        throw new Error(normalizeError(text, "Failed to update appearance."));
      }
    } catch (error) {
      setThemePreference(previousTheme);
      applyThemePreference(previousTheme, true);
      setThemeError(error instanceof Error ? error.message : String(error));
    } finally {
      setThemeSaving(false);
    }
  };

  return (
    <>
      <section className="rounded-[28px] border border-[#e7e1d6] bg-[#fffaf3] px-4 py-5 shadow-[0_30px_80px_-60px_rgba(30,27,22,0.45)] sm:px-5 sm:py-6">
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
            <button
              type="button"
              onClick={openScoreCard}
              className="pointer-events-auto flex flex-col items-center gap-1 rounded-full"
              aria-label="Open How HealthSense works"
            >
              <div className="relative">
                <CombinedLogoRing value={combinedScore} />
                {hasIntroMessage ? (
                  <span className="absolute -right-1 top-0 flex h-5 w-5 items-center justify-center rounded-full border border-white bg-[var(--accent)] shadow-sm">
                    <span className="h-1.5 w-1.5 rounded-full bg-white" />
                  </span>
                ) : null}
              </div>
              {hasIntroMessage ? (
                <span className="rounded-full border border-[#e7e1d6] bg-white/95 px-2.5 py-1 text-[10px] leading-none text-[#5d5348] shadow-sm">
                  Message available
                </span>
              ) : null}
            </button>
          </div>
        </div>
      </section>

      {scoreCardOpen ? (
        <div className="fixed inset-0 z-40 flex items-stretch justify-center bg-black/30 sm:items-center sm:px-3 sm:py-3">
          <div className="flex h-[100dvh] max-h-[100dvh] w-full max-w-sm flex-col overflow-hidden bg-white pt-[env(safe-area-inset-top)] pb-[env(safe-area-inset-bottom)] shadow-[0_30px_80px_-60px_rgba(30,27,22,0.6)] sm:h-auto sm:max-h-[92vh] sm:rounded-[28px] sm:border sm:border-[#e7e1d6] sm:pt-0 sm:pb-0">
            <div className="shrink-0 border-b border-[#efe7db] bg-white px-3 py-3 sm:px-5">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <div className="flex items-center gap-1.5 text-base font-semibold text-[#1e1b16]">
                    <LeadAssessmentBranding titleLines={[]} logoClassName="h-4 w-4" />
                    <p>{`HealthSense score ${combinedScore}/100`}</p>
                  </div>
                  <p className="mt-1 text-xs text-[#6b6257]">{scoreCardSubtitle}</p>
                </div>
                <button
                  type="button"
                  onClick={() => setScoreCardOpen(false)}
                  className="shrink-0 rounded-full border border-[#e7e1d6] bg-white px-2.5 py-1.5 text-[10px] uppercase tracking-[0.16em] text-[#5d5348]"
                >
                  Close
                </button>
              </div>
            </div>

            <div className="flex-1 overflow-y-auto px-3 py-3 sm:px-5">
              <div className="mb-3 rounded-2xl border border-[#efe7db] bg-[#fffaf3] px-3 py-3">
                <p className="text-[11px] uppercase tracking-[0.18em] text-[#6b6257]">HealthSense score</p>
                <div className="mt-3 flex items-center gap-4 rounded-2xl border border-[#efe7db] bg-white px-4 py-4">
                  <CombinedLogoRing value={combinedScore} />
                  <div className="min-w-0">
                    <p className="text-2xl font-semibold text-[#1e1b16]">{combinedScore}/100</p>
                    <p className="mt-1 text-sm text-[#6b6257]">{scoreCardSubtitle}</p>
                    {scoreCardHelper ? (
                      <p className="mt-2 text-xs text-[#8c7f70]">{scoreCardHelper}</p>
                    ) : null}
                  </div>
                </div>
              </div>
              {activeIntroVideo && String(activeIntroVideo.avatar?.url || "").trim() ? (
                <div className="space-y-3">
                  <video
                    key={`${activeIntroVideo.key}-${String(activeIntroVideo.avatar?.url || "").trim()}`}
                    ref={introVideoRef}
                    autoPlay
                    controls
                    preload="metadata"
                    playsInline
                    poster={String(activeIntroVideo.avatar?.posterUrl || "").trim() || undefined}
                    className="w-full rounded-2xl border border-[#efe7db] bg-[#f7f4ee]"
                  >
                    <source src={String(activeIntroVideo.avatar?.url || "").trim()} />
                  </video>
                  {introVideoOptions.length > 1 ? (
                    <div className="rounded-2xl border border-[#efe7db] bg-[#fffaf3] px-3 py-3">
                      <p className="text-[11px] uppercase tracking-[0.18em] text-[#6b6257]">Help videos</p>
                      <div className="mt-2 flex flex-wrap gap-2">
                        {introVideoOptions.map((option) => {
                          const active = option.key === activeIntroVideo.key;
                          return (
                            <button
                              key={option.key}
                              type="button"
                              onClick={() => selectIntroVideo(option.key)}
                              className={`rounded-full border px-3 py-2 text-[11px] font-semibold uppercase tracking-[0.12em] ${
                                active
                                  ? "border-[#d6c3ab] bg-[#f6ede3] text-[#5d472d]"
                                  : "border-[#e7e1d6] bg-white text-[#5d5348]"
                              }`}
                            >
                              {option.label}
                            </button>
                          );
                        })}
                      </div>
                    </div>
                  ) : null}
                  {setupOpen ? (
                    <div className="rounded-2xl border border-[#efe7db] bg-[#fffaf3] px-3 py-3">
                      <p className="text-[11px] uppercase tracking-[0.18em] text-[#6b6257]">Mode</p>
                      <div className="mt-2 flex flex-wrap gap-2">
                        {[
                          { key: "system", label: "Match device" },
                          { key: "light", label: "Light" },
                          { key: "dark", label: "Dark" },
                        ].map((option) => {
                          const active = themePreference === option.key;
                          return (
                            <button
                              key={option.key}
                              type="button"
                              disabled={themeSaving}
                              onClick={() => void saveThemePreference(option.key)}
                              className={`rounded-full border px-3 py-2 text-[11px] font-semibold uppercase tracking-[0.12em] ${
                                active
                                  ? "border-[var(--accent)] bg-[var(--accent)] text-white"
                                  : "border-[#d9cdbb] bg-white text-[#5d5348]"
                              } disabled:cursor-not-allowed disabled:opacity-60`}
                            >
                              {option.label}
                            </button>
                          );
                        })}
                      </div>
                      {themeError ? <p className="mt-2 text-xs text-[#8a3e1a]">{themeError}</p> : null}
                    </div>
                  ) : null}
                </div>
              ) : (
                <div className="rounded-2xl border border-[#efe7db] bg-[#fffaf3] px-4 py-5 text-sm text-[#6b6257]">
                  The HealthSense introduction video is not available right now.
                </div>
              )}
            </div>

            <div className="shrink-0 border-t border-[#efe7db] px-3 py-3 sm:px-5">
              {themeSaving ? <p className="mb-2 text-center text-[11px] text-[#6b6257]">Saving…</p> : null}
              {themeError && !setupOpen ? <p className="mb-2 text-center text-xs text-[#8a3e1a]">{themeError}</p> : null}
              <div className="grid grid-cols-2 gap-2">
                <button
                  type="button"
                  onClick={() => setSetupOpen((current) => !current)}
                  className={`inline-flex items-center justify-center gap-2 rounded-full border px-4 py-2.5 text-center text-[11px] font-semibold uppercase tracking-[0.16em] ${
                    setupOpen
                      ? "border-[#d6c3ab] bg-[#f6ede3] text-[#5d472d]"
                      : "border-[#d9cdbb] bg-white text-[#5d5348]"
                  }`}
                >
                  <svg viewBox="0 0 24 24" className="h-3.5 w-3.5" aria-hidden="true">
                    <path
                      d="M12 8.5a3.5 3.5 0 1 0 0 7a3.5 3.5 0 0 0 0-7Zm8 3.5l-1.71-.57a6.76 6.76 0 0 0-.46-1.1l.82-1.6l-1.73-1.73l-1.6.82c-.35-.18-.72-.33-1.1-.46L13 4h-2l-.57 1.71c-.38.13-.75.28-1.1.46l-1.6-.82L5 7.08l.82 1.6c-.18.35-.33.72-.46 1.1L3.65 10v2l1.71.57c.13.38.28.75.46 1.1L5 15.27L6.73 17l1.6-.82c.35.18.72.33 1.1.46L11 18.35h2l.57-1.71c.38-.13.75-.28 1.1-.46l1.6.82l1.73-1.73l-.82-1.6c.18-.35.33-.72.46-1.1L20 14v-2Z"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="1.35"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    />
                  </svg>
                  Setup
                </button>
                <button
                  type="button"
                  onClick={() => setScoreCardOpen(false)}
                  className="w-full rounded-full border border-[#d9cdbb] bg-white px-4 py-2.5 text-center text-[11px] font-semibold uppercase tracking-[0.16em] text-[#5d5348]"
                >
                  Close
                </button>
              </div>
            </div>
          </div>
        </div>
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
                            onClick={() => void openTracker(String(detail.pillar?.pillar_key || selectedPillarKey || ""), itemDate)}
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
                    Close
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
                  Close
                </button>
              )}
            </div>
          </div>
        </div>
      ) : null}
    </>
  );
}
