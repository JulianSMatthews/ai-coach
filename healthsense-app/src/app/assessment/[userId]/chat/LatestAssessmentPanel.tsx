"use client";

import { useState } from "react";
import type {
  PillarTrackerDetailResponse,
  PillarTrackerPillar,
  PillarTrackerSummaryResponse,
} from "@/lib/api";
import { getPillarPalette } from "@/lib/pillars";
import { ScoreRing } from "@/components/ui";

type LatestAssessmentPanelProps = {
  userId: string;
  initialSummary: PillarTrackerSummaryResponse;
};

const PILLAR_ORDER = ["nutrition", "training", "resilience", "recovery"];

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

function circleDayTone(targetMet?: boolean | null): string {
  if (targetMet === true) return "border-[#d5e8bf] bg-[#f2fae8] text-[#335f16]";
  if (targetMet === false) return "border-[#f2dccb] bg-[#fff1ea] text-[#8a3e1a]";
  return "border-[#ece5d9] bg-white text-[#8c7f70]";
}

function completeDayTone(complete?: boolean, isToday?: boolean): string {
  if (complete) return "border-[#d5e8bf] bg-[#f2fae8] text-[#335f16]";
  if (isToday) return "border-[#f3d8c9] bg-[#fff5ef] text-[#8a3e1a]";
  return "border-[#ece5d9] bg-white text-[#8c7f70]";
}

export default function LatestAssessmentPanel({ userId, initialSummary }: LatestAssessmentPanelProps) {
  const [summary, setSummary] = useState<PillarTrackerSummaryResponse>(initialSummary);
  const [selectedPillarKey, setSelectedPillarKey] = useState<string | null>(null);
  const [detail, setDetail] = useState<PillarTrackerDetailResponse | null>(null);
  const [activePanel, setActivePanel] = useState<"habits" | "insight" | "ask">("habits");
  const [draft, setDraft] = useState<Record<string, number>>({});
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [saving, setSaving] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);

  const pillars = sortPillars(Array.isArray(summary.pillars) ? summary.pillars : []);
  const strongestPillar = [...pillars].sort((a, b) => Number(b.score || 0) - Number(a.score || 0))[0] || null;
  const weakestPillar = [...pillars].sort((a, b) => Number(a.score || 0) - Number(b.score || 0))[0] || null;
  const longestStreak = pillars.reduce((best, pillar) => Math.max(best, Number(pillar.streak_days || 0)), 0);
  const completedDaysTotal = pillars.reduce((total, pillar) => total + Number(pillar.completed_days_count || 0), 0);
  const concepts = Array.isArray(detail?.concepts) ? detail?.concepts : [];
  const canSave =
    !saving &&
    concepts.length > 0 &&
    concepts.every((concept) => {
      const conceptKey = String(concept.concept_key || "").trim();
      return conceptKey && Number.isFinite(Number(draft[conceptKey]));
    });

  const openTracker = async (pillarKey: string) => {
    setSelectedPillarKey(pillarKey);
    setDetail(null);
    setDraft({});
    setDetailError(null);
    setSaveError(null);
    setLoadingDetail(true);
    try {
      const res = await fetch(`/api/pillar-tracker/${encodeURIComponent(pillarKey)}?userId=${encodeURIComponent(userId)}`, {
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

  const closeTracker = () => {
    setSelectedPillarKey(null);
    setDetail(null);
    setDraft({});
    setDetailError(null);
    setSaveError(null);
    setLoadingDetail(false);
    setSaving(false);
  };

  const focusChatInput = () => {
    if (typeof window === "undefined") return;
    const input = document.getElementById("assessment-chat-input") as HTMLTextAreaElement | null;
    if (!input) return;
    input.scrollIntoView({ behavior: "smooth", block: "center" });
    window.setTimeout(() => input.focus(), 120);
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
          score_date: detail.pillar.today,
          entries,
        }),
      });
      const text = await res.text().catch(() => "");
      if (!res.ok) {
        throw new Error(normalizeError(text, "Failed to save the pillar tracker."));
      }
      const payload = (text ? (JSON.parse(text) as PillarTrackerDetailResponse) : {}) as PillarTrackerDetailResponse;
      setDetail(payload);
      setSummary((current) => ({
        ...current,
        pillars: sortPillars(
          (current.pillars || []).map((pillar) =>
            String(pillar.pillar_key || "").trim().toLowerCase() ===
            String(payload.pillar?.pillar_key || "").trim().toLowerCase()
              ? {
                  ...pillar,
                  score: payload.pillar?.score ?? pillar.score,
                  tracker_score: payload.pillar?.tracker_score ?? pillar.tracker_score,
                  baseline_score: payload.pillar?.baseline_score ?? pillar.baseline_score,
                  source: payload.pillar?.source ?? pillar.source,
                  completed_days_count: payload.pillar?.completed_days_count ?? pillar.completed_days_count,
                  streak_days: payload.pillar?.streak_days ?? pillar.streak_days,
                }
              : pillar,
          ),
        ),
      }));
    } catch (error) {
      setSaveError(error instanceof Error ? error.message : String(error));
    } finally {
      setSaving(false);
    }
  };

  return (
    <>
      <section className="rounded-[28px] border border-[#e7e1d6] bg-[#fffaf3] px-4 py-5 shadow-[0_30px_80px_-60px_rgba(30,27,22,0.45)] sm:px-5 sm:py-6">
        <div className="mb-4 grid grid-cols-3 gap-2">
          {[
            { key: "habits", label: "Habits" },
            { key: "insight", label: "Insight" },
            { key: "ask", label: "Ask" },
          ].map((item) => {
            const active = activePanel === item.key;
            return (
              <button
                key={item.key}
                type="button"
                onClick={() => {
                  setActivePanel(item.key as "habits" | "insight" | "ask");
                  if (item.key === "ask") {
                    focusChatInput();
                  }
                }}
                className={`rounded-full px-3 py-2 text-xs font-semibold uppercase tracking-[0.16em] transition ${
                  active
                    ? "border border-[var(--accent)] bg-[var(--accent)] text-white"
                    : "border border-[#d9cdbb] bg-white text-[#5d5348]"
                }`}
              >
                {item.label}
              </button>
            );
          })}
        </div>

        {activePanel === "habits" ? (
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
        ) : null}

        {activePanel === "insight" ? (
          <div className="space-y-3">
            <div className="rounded-2xl border border-[#efe7db] bg-white px-4 py-4">
              <p className="text-xs uppercase tracking-[0.22em] text-[#6b6257]">This week</p>
              <p className="mt-2 text-sm text-[#3c332b]">
                {strongestPillar && weakestPillar
                  ? `Your strongest tracked pillar so far is ${strongestPillar.label} and the area needing most attention is ${weakestPillar.label}.`
                  : "Complete your first habit tracker to unlock your weekly insight."}
              </p>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="rounded-2xl border border-[#efe7db] bg-white px-4 py-4 text-center">
                <p className="text-xs uppercase tracking-[0.18em] text-[#6b6257]">Longest streak</p>
                <p className="mt-2 text-2xl font-semibold text-[#1e1b16]">{longestStreak}</p>
              </div>
              <div className="rounded-2xl border border-[#efe7db] bg-white px-4 py-4 text-center">
                <p className="text-xs uppercase tracking-[0.18em] text-[#6b6257]">Habit days logged</p>
                <p className="mt-2 text-2xl font-semibold text-[#1e1b16]">{completedDaysTotal}</p>
              </div>
            </div>
          </div>
        ) : null}

        {activePanel === "ask" ? (
          <div className="rounded-2xl border border-[#efe7db] bg-white px-4 py-5">
            <p className="text-sm text-[#3c332b]">
              Ask Gia anything about your habits, weekly progress, or what to focus on next.
            </p>
            <button
              type="button"
              onClick={focusChatInput}
              className="mt-4 rounded-full border border-[var(--accent)] bg-[var(--accent)] px-4 py-2 text-xs font-semibold uppercase tracking-[0.18em] text-white"
            >
              Jump to chat
            </button>
          </div>
        ) : null}
      </section>

      {selectedPillarKey ? (
        <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/40 px-3 py-3 sm:items-center sm:p-6">
          <div className="flex max-h-[92vh] w-full max-w-2xl flex-col overflow-hidden rounded-[28px] border border-[#e7e1d6] bg-white shadow-[0_30px_80px_-60px_rgba(30,27,22,0.6)]">
            <div className="flex items-start justify-between gap-3 border-b border-[#efe7db] px-4 py-4 sm:px-5">
              <div className="space-y-1">
                <p className="text-xs uppercase tracking-[0.22em] text-[#6b6257]">
                  {detail?.pillar?.label || selectedPillarKey.replace(/_/g, " ")}
                </p>
                <p className="text-sm text-[#6b6257]">
                  {detail?.pillar?.tracker_score !== null && detail?.pillar?.tracker_score !== undefined
                    ? `${detail?.pillar?.tracker_score}/100 this week so far`
                    : "Complete today to start this week's score"}
                </p>
                {detail?.pillar?.completed_days_count !== undefined || detail?.pillar?.streak_days !== undefined ? (
                  <p className="text-xs text-[#8c7f70]">
                    {`${detail?.pillar?.completed_days_count || 0}/7 days complete · ${detail?.pillar?.streak_days || 0} day streak`}
                  </p>
                ) : null}
              </div>
              <button
                type="button"
                onClick={closeTracker}
                className="rounded-full border border-[#e7e1d6] px-3 py-2 text-xs uppercase tracking-[0.18em] text-[#5d5348]"
              >
                Close
              </button>
            </div>

            <div className="flex-1 overflow-y-auto px-4 py-4 sm:px-5">
              {loadingDetail ? <p className="text-sm text-[#6b6257]">Loading tracker…</p> : null}
              {detailError ? <p className="text-sm text-[#8a3e1a]">{detailError}</p> : null}

              {detail && !loadingDetail ? (
                <div className="space-y-5">
                  <div className="rounded-2xl border border-[#efe7db] bg-[#fffaf3] px-4 py-4">
                    <p className="text-xs uppercase tracking-[0.22em] text-[#6b6257]">This week</p>
                    <div className="mt-3 grid grid-cols-7 gap-2">
                      {(detail.days || []).map((day) => (
                        <div
                          key={day.date}
                          className={`rounded-xl border px-2 py-2 text-center text-[11px] ${completeDayTone(day.complete, day.is_today)}`}
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
                            {targetText ? (
                              <p className="mt-2 text-xs text-[#6b6257]">
                                {targetText}
                              </p>
                            ) : null}
                          </div>
                          <p className="text-xs text-[#8c7f70]">{`${concept.streak_days || 0} day streak`}</p>
                        </div>

                        <div className="mt-3 grid grid-cols-7 gap-2">
                          {(concept.week || []).map((day) => (
                            <div
                              key={`${conceptKey}-${day.date}`}
                              className={`rounded-xl border px-2 py-2 text-center text-[11px] ${circleDayTone(day.target_met)}`}
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
                {saving ? "Saving tracker…" : "Save today's tracker"}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </>
  );
}
