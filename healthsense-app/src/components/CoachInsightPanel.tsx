"use client";

import { useEffect, useState } from "react";
import type { CoachInsightConcept, CoachInsightResponse } from "@/lib/api";
import { getPillarPalette } from "@/lib/pillars";
import PillarIcon from "@/components/PillarIcon";
import GuidanceIcon from "@/components/GuidanceIcon";

const CONCEPT_INSIGHT_MAX_WORDS = 100;

function limitWords(text: string, maxWords: number): string {
  const value = text.trim();
  if (maxWords <= 0) return "";
  const words = [...value.matchAll(/\S+/g)];
  if (words.length <= maxWords) return value;
  const lastWord = words[maxWords - 1];
  const excerpt = value.slice(0, (lastWord.index ?? 0) + lastWord[0].length);
  const sentenceEnd = [...excerpt.matchAll(/[.!?]["'’”)\]]*(?=\s|$)/g)].pop();
  return sentenceEnd
    ? excerpt.slice(0, (sentenceEnd.index ?? 0) + sentenceEnd[0].length)
    : `${excerpt.replace(/[,;:]+$/, "")}…`;
}

function reviewIsValid(payload: CoachInsightResponse | null, userId: string): payload is CoachInsightResponse {
  const review = payload?.review;
  if (
    !payload || String(payload.user_id) !== userId || !review ||
    !["off_track", "on_track", "insufficient_data"].includes(review.status) ||
    !Array.isArray(payload.available_concepts)
  ) return false;
  const counts = [review.off_track_count, review.on_track_count, review.unlogged_count, review.not_applicable_count];
  if (![review.reviewed_count, ...counts].every((count) => Number.isInteger(count) && count >= 0)) return false;
  if (counts.reduce((total, count) => total + count, 0) !== review.reviewed_count) return false;
  if (payload.available_concepts.some((concept) => !concept || typeof concept !== "object")) return false;
  const offTrack = payload.available_concepts.filter((concept) => concept?.status === "off_track");
  return offTrack.length === review.off_track_count && offTrack.every((concept) =>
    typeof concept.concept_key === "string" && Boolean(concept.concept_key.trim()) &&
    typeof concept.pillar_key === "string" && Boolean(concept.pillar_key.trim()) &&
    typeof concept.label === "string" && Boolean(concept.label.trim()) &&
    typeof concept.guidance === "string" && Boolean(concept.guidance.trim()) &&
    (concept.reflection == null || typeof concept.reflection === "string")
  ) && (
    review.status === "off_track" ? review.off_track_count > 0 :
    review.status === "on_track" ? review.off_track_count === 0 && review.on_track_count > 0 && review.unlogged_count === 0 :
    review.off_track_count === 0
  );
}

function evidenceDate(value?: string | null): string | null {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return null;
  const date = new Date(`${value}T12:00:00Z`);
  return Number.isNaN(date.getTime()) || date.toISOString().slice(0, 10) !== value ? null : date.toLocaleDateString("en-GB", {
    day: "numeric", month: "short", timeZone: "UTC",
  });
}

function evidenceDateRange(start?: string | null, end?: string | null): string | null {
  const first = evidenceDate(start);
  const last = evidenceDate(end);
  if (!first) return last;
  if (!last || start === end) return first;
  return start && end && start.slice(0, 7) === end.slice(0, 7)
    ? `${Number(start.slice(8, 10))}–${last}`
    : `${first}–${last}`;
}

function ConceptGuidance({ concept }: { concept: CoachInsightConcept }) {
  const palette = getPillarPalette(concept.pillar_key);
  const reflectionLabel = limitWords((concept.label || "this concept").toLowerCase(), 14);
  const reflection = limitWords(
    concept.reflection?.trim() || `What would help you work towards your existing ${reflectionLabel} target this week?`,
    25,
  );
  const guidance = limitWords(concept.guidance || "", CONCEPT_INSIGHT_MAX_WORDS - reflection.split(/\s+/).length);
  return (
    <article className="overflow-hidden rounded-[24px] border border-[var(--border)] bg-[var(--surface)]" aria-label={`${concept.label}: off track`}>
      <div className="flex items-center gap-3 border-b border-[var(--border)] px-5 py-4">
        <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full" style={{ color: palette.accent, backgroundColor: palette.bg }}>
          <PillarIcon pillarKey={concept.pillar_key || ""} className="h-6 w-6" />
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-xs text-[var(--text-secondary)]">{concept.pillar_label || palette.label}</p>
          <h3 className="mt-0.5 text-lg font-semibold leading-snug text-[var(--text-primary)]">{concept.label}</h3>
        </div>
      </div>
      <div className="space-y-4 px-5 py-5">
        <dl className="grid gap-3 text-sm sm:grid-cols-2">
          <div><dt className="text-xs text-[var(--text-secondary)]">Score to date</dt><dd className="mt-1 text-lg font-semibold tabular-nums text-[var(--text-primary)]">{concept.score == null ? "—" : `${concept.score} / 100`}</dd></div>
          {concept.target_label ? <div><dt className="text-xs text-[var(--text-secondary)]">Your target</dt><dd className="mt-1 font-medium text-[var(--text-primary)]">{concept.target_label}</dd></div> : null}
        </dl>
        <div>
          <h4 className="text-[var(--text-primary)]"><GuidanceIcon kind="step" /><span className="sr-only">One small step</span></h4>
          <p className="mt-3 whitespace-pre-line text-lg leading-8 text-[var(--text-primary)] sm:text-xl">{guidance}</p>
        </div>
        <div className="border-t border-[var(--border)] pt-5">
          <h4 className="text-[var(--text-primary)]"><GuidanceIcon kind="reflection" /><span className="sr-only">A moment to reflect</span></h4>
          <p className="mt-3 whitespace-pre-line text-lg leading-8 text-[var(--text-primary)] sm:text-xl">{reflection}</p>
        </div>
      </div>
    </article>
  );
}

export default function CoachInsightPanel({ userId }: { userId: string }) {
  const [result, setResult] = useState<CoachInsightResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [reload, setReload] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(false);
    setResult(null);
    const load = async () => {
      try {
        const params = new URLSearchParams({ userId });
        const response = await fetch(`/api/coach-insight?${params}`, { cache: "no-store", signal: controller.signal });
        const payload: CoachInsightResponse | null = await response.json().catch(() => null);
        if (!response.ok || !reviewIsValid(payload, userId)) throw new Error("Insight unavailable");
        if (!controller.signal.aborted) setResult(payload);
      } catch {
        if (!controller.signal.aborted) setError(true);
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    };
    void load();
    return () => controller.abort();
  }, [reload, userId]);

  if (loading || (!error && String(result?.user_id) !== userId)) {
    return <p role="status" className="rounded-[24px] border border-[var(--border)] bg-[var(--surface)] px-5 py-8 text-sm text-[var(--text-secondary)]">Reviewing all your concepts…</p>;
  }
  if (error || !result?.review) {
    return (
      <div role="alert" className="rounded-[24px] border border-[var(--border)] bg-[var(--surface)] p-5">
        <p className="text-sm leading-6 text-[var(--text-secondary)]">Could not load your insights. Please try again.</p>
        <button type="button" className="mt-4 rounded-full bg-[var(--action-primary-bg)] px-5 py-3 text-sm font-semibold text-[var(--action-primary-text)]" onClick={() => setReload((value) => value + 1)}>Try again</button>
      </div>
    );
  }

  const review = result.review;
  const offTrack = (result.available_concepts || []).filter((concept) => concept.status === "off_track");
  const weekRange = evidenceDateRange(review.week_start_date, review.through_date);
  const allNotApplicable = review.not_applicable_count > 0 && review.unlogged_count === 0 && review.on_track_count === 0 && review.off_track_count === 0;
  return (
    <section aria-label="Concept insights" className="space-y-5">
      <div className="rounded-[24px] border border-[var(--border)] bg-[var(--surface)] p-5">
        <p className="text-xs font-medium uppercase tracking-[0.15em] text-[var(--text-secondary)]">Week to date{weekRange ? ` · ${weekRange}` : ""}</p>
        <h2 className="mt-2 text-xl font-semibold text-[var(--text-primary)]">
          {review.status === "off_track" ? "Where to focus" : review.status === "on_track" ? "You're on track" : allNotApplicable ? "No guidance needed" : "More data needed"}
        </h2>
        <p className="mt-2 text-sm leading-6 text-[var(--text-secondary)]">
          {review.status === "off_track"
            ? "Here are your next steps for concepts needing support this week."
            : review.status === "on_track"
              ? "Your recorded concepts are on track so far this week. Keep your current rhythm."
              : allNotApplicable
                ? "Your answers this week mark these concepts as not applicable. No guidance is needed."
                : review.on_track_count > 0
                  ? "Your scored concepts are on track. Some concepts do not yet have scored data to assess."
                  : "There isn't enough scored check-in data this week to identify concepts needing support yet."}
        </p>
      </div>
      {offTrack.map((concept) => <ConceptGuidance key={`${concept.pillar_key}:${concept.concept_key}`} concept={concept} />)}
    </section>
  );
}
