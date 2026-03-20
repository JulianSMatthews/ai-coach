"use client";

import { useState } from "react";
import type {
  PillarTrackerDetailResponse,
  PillarTrackerPillar,
  PillarTrackerSummaryResponse,
} from "@/lib/api";
import { getPillarPalette } from "@/lib/pillars";
import { ScoreRing } from "@/components/ui";
import LeadAssessmentBranding from "./LeadAssessmentBranding";

type LatestAssessmentPanelProps = {
  userId: string;
  initialSummary: PillarTrackerSummaryResponse;
};

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

function okrTone(onTrack?: boolean | null): string {
  if (onTrack === true) return "border-[#d5e8bf] bg-[#f2fae8] text-[#335f16]";
  if (onTrack === false) return "border-[#f2dccb] bg-[#fff4ea] text-[#8a5a1a]";
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

export default function LatestAssessmentPanel({ userId, initialSummary }: LatestAssessmentPanelProps) {
  const [summary, setSummary] = useState<PillarTrackerSummaryResponse>(initialSummary);
  const [scoreCardOpen, setScoreCardOpen] = useState(false);
  const [selectedPillarKey, setSelectedPillarKey] = useState<string | null>(null);
  const [detail, setDetail] = useState<PillarTrackerDetailResponse | null>(null);
  const [draft, setDraft] = useState<Record<string, number>>({});
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [saving, setSaving] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);

  const pillars = sortPillars(Array.isArray(summary.pillars) ? summary.pillars : []);
  const combinedScore = (() => {
    const scores = pillars
      .map((pillar) => Number(pillar.score))
      .filter((score) => Number.isFinite(score));
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

  return (
    <>
      <section className="rounded-[28px] border border-[#e7e1d6] bg-[#fffaf3] px-4 py-5 shadow-[0_30px_80px_-60px_rgba(30,27,22,0.45)] sm:px-5 sm:py-6">
        <div className="relative">
          <div className="grid grid-cols-2 gap-3">
            {pillars.map((pillar) => {
              const pillarKey = String(pillar.pillar_key || "").trim().toLowerCase();
              const palette = getPillarPalette(pillarKey);
              const score = Number(pillar.score);
              return (
                <button
                  key={pillarKey}
                  type="button"
                  onClick={() => void openTracker(pillarKey)}
                  className="rounded-2xl border border-[#efe7db] bg-white px-3 py-4 text-left transition hover:border-[#dccfbe]"
                >
                  <div className="flex flex-col items-center text-center">
                    <ScoreRing value={Number.isFinite(score) ? score : 0} tone={palette.accent} />
                    <p className="mt-3 text-sm font-semibold text-[#1e1b16]">{pillar.label}</p>
                  </div>
                </button>
              );
            })}
          </div>

          <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
            <button
              type="button"
              onClick={() => setScoreCardOpen(true)}
              className="pointer-events-auto rounded-full"
              aria-label="Open HealthSense score breakdown"
            >
              <CombinedLogoRing value={combinedScore} />
            </button>
          </div>
        </div>
      </section>

      {scoreCardOpen ? (
        <div className="fixed inset-0 z-40 flex items-end justify-center bg-black/30 px-3 py-3 sm:items-center sm:p-6">
          <div className="w-full max-w-sm rounded-[28px] border border-[#e7e1d6] bg-white p-5 shadow-[0_30px_80px_-60px_rgba(30,27,22,0.6)]">
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="text-xs uppercase tracking-[0.22em] text-[#6b6257]">HealthSense</p>
                <p className="mt-1 text-lg font-semibold text-[#1e1b16]">Score breakdown</p>
              </div>
              <button
                type="button"
                onClick={() => setScoreCardOpen(false)}
                className="rounded-full border border-[#e7e1d6] px-3 py-2 text-xs uppercase tracking-[0.18em] text-[#5d5348]"
              >
                Close
              </button>
            </div>

            <div className="mt-5 flex flex-col items-center text-center">
              <CombinedLogoRing value={combinedScore} />
              <p className="mt-3 text-3xl font-semibold text-[#1e1b16]">{combinedScore}</p>
              <p className="text-sm text-[#6b6257]">Combined HealthSense score</p>
            </div>

            <div className="mt-5 space-y-2">
              {pillars.map((pillar) => {
                const score = Number(pillar.score);
                return (
                  <div
                    key={`score-card-${pillar.pillar_key}`}
                    className="flex items-center justify-between rounded-2xl border border-[#efe7db] bg-[#fffaf3] px-4 py-3"
                  >
                    <p className="text-sm font-semibold text-[#1e1b16]">{pillar.label}</p>
                    <p className="text-sm text-[#6b6257]">
                      {Number.isFinite(score) ? `${score}/100` : "—"}
                    </p>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      ) : null}

      {selectedPillarKey ? (
        <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/40 px-3 py-3 sm:items-center sm:p-6">
          <div className="flex max-h-[92vh] w-full max-w-2xl flex-col overflow-hidden rounded-[28px] border border-[#e7e1d6] bg-white shadow-[0_30px_80px_-60px_rgba(30,27,22,0.6)]">
            <div className="relative border-b border-[#efe7db] px-4 py-4 pr-20 sm:px-5 sm:pr-5">
              <div className="space-y-1">
                <p className="text-xs uppercase tracking-[0.22em] text-[#6b6257]">
                  {detail?.pillar?.label || selectedPillarKey.replace(/_/g, " ")}
                </p>
                <p className="text-sm font-medium text-[#3f372f]">
                  {savingPastDay ? `Catching up ${activeLabel || "yesterday"}` : "Tracking today"}
                </p>
                <p className="text-sm text-[#6b6257]">
                  {detail?.pillar?.tracker_score !== null && detail?.pillar?.tracker_score !== undefined
                    ? `${detail?.pillar?.tracker_score}/100 this week so far`
                    : savingPastDay
                      ? `Complete ${activeLabel || "yesterday"} to update this week's score`
                      : "Complete today to start this week's score"}
                </p>
                {detail?.pillar?.completed_days_count !== undefined || detail?.pillar?.streak_days !== undefined ? (
                  <p className="text-xs text-[#8c7f70]">
                    {`${detail?.pillar?.completed_days_count || 0}/7 days complete · ${detail?.pillar?.streak_days || 0} day check-in streak`}
                  </p>
                ) : null}
              </div>
              <button
                type="button"
                onClick={closeTracker}
                className="absolute right-4 top-4 rounded-full border border-[#e7e1d6] px-3 py-2 text-xs uppercase tracking-[0.18em] text-[#5d5348] sm:right-5"
              >
                Close
              </button>
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
                    <p className="text-xs uppercase tracking-[0.22em] text-[#6b6257]">This week</p>
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
                    const targetText =
                      concept.target_source === "okr" && targetLabel
                        ? `${targetLabel} from your current OKR`
                        : targetLabel;
                    return (
                      <div key={conceptKey} className="rounded-2xl border border-[#efe7db] bg-white px-4 py-4">
                        <div className="flex items-start justify-between gap-3">
                          <div>
                            <p className="text-sm font-semibold text-[#1e1b16]">{concept.label}</p>
                            <p className="mt-1 text-xs uppercase tracking-[0.18em] text-[#8c7f70]">{concept.helper}</p>
                            {targetText || okrStatusLabel ? (
                              <div className="mt-2 flex flex-wrap items-center gap-2">
                                {targetText ? <p className="text-xs text-[#6b6257]">{targetText}</p> : null}
                                {concept.target_source === "okr" && okrStatusLabel ? (
                                  <span
                                    className={`rounded-full border px-2 py-1 text-[10px] font-semibold uppercase tracking-[0.14em] ${okrTone(concept.okr_on_track)}`}
                                  >
                                    {`OKR ${okrStatusLabel.toLowerCase()}`}
                                  </span>
                                ) : null}
                              </div>
                            ) : null}
                            {concept.target_source === "okr" && okrStatusDetail ? (
                              <p className="mt-1 text-[11px] text-[#8c7f70]">{`Pace ${okrStatusDetail}`}</p>
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
                          {(concept.options || []).map((option) => {
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
                          })}
                        </div>
                      </div>
                    );
                  })}

                  {saveError ? <p className="text-sm text-[#8a3e1a]">{saveError}</p> : null}
                </div>
                ) : null}
              </div>

            <div className="border-t border-[#efe7db] px-4 py-4 sm:px-5">
              <button
                type="button"
                onClick={() => void saveTracker()}
                disabled={!canSave}
                className="w-full rounded-full border border-[var(--accent)] bg-[var(--accent)] px-4 py-3 text-center text-xs font-semibold uppercase tracking-[0.18em] text-white disabled:cursor-not-allowed disabled:opacity-60"
              >
                {saving
                  ? "Saving tracker…"
                  : savingPastDay
                    ? `Save ${activeLabel ? activeLabel.toLowerCase() : "yesterday"}'s tracker`
                    : "Save today's tracker"}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </>
  );
}
