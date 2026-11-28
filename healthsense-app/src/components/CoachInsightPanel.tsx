"use client";

import { useEffect, useState } from "react";
import type { CoachInsightConcept, CoachInsightResponse, PillarProgressGuidance } from "@/lib/api";
import { requestConceptGuidance } from "@/lib/pillarProgress";
import { getPillarPalette } from "@/lib/pillars";
import PillarIcon from "@/components/PillarIcon";
import ConceptGuidanceSections from "@/components/ConceptGuidanceSections";

const MAX_FOCUS_CONCEPTS = 6;

function evidenceDate(value?: string | null): string | null {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return null;
  const date = new Date(`${value}T12:00:00Z`);
  return Number.isNaN(date.getTime()) || date.toISOString().slice(0, 10) !== value ? null : date.toLocaleDateString("en-GB", {
    day: "numeric", month: "short", timeZone: "UTC",
  });
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
  const offTrack = payload.available_concepts.filter((concept) => concept.status === "off_track");
  const focusCount = review.focus_count ?? review.off_track_count;
  if (!Number.isInteger(focusCount) || focusCount < 0 || focusCount > review.off_track_count) return false;
  if (offTrack.length !== focusCount) return false;
  if (new Set(offTrack.map((concept) => `${concept.pillar_key}:${concept.concept_key}`)).size !== offTrack.length) return false;
  if (!offTrack.every((concept) =>
    typeof concept.concept_key === "string" && Boolean(concept.concept_key.trim()) &&
    typeof concept.pillar_key === "string" && Boolean(concept.pillar_key.trim()) &&
    typeof concept.label === "string" && Boolean(concept.label.trim()) &&
    typeof concept.score === "number" && Number.isFinite(concept.score) && concept.score >= 0 && concept.score < 80
  )) return false;
  // AI responses must match the selection's reporting period before they can be shown.
  if (offTrack.length && (
    !evidenceDate(review.week_start_date) || !evidenceDate(review.through_date) ||
    review.week_start_date! > review.through_date!
  )) return false;
  return review.status === "off_track" ? review.off_track_count > 0 && focusCount > 0 :
    review.status === "on_track" ? review.off_track_count === 0 && review.on_track_count > 0 && review.unlogged_count === 0 :
    review.off_track_count === 0;
}

function focusConcepts(concepts: CoachInsightConcept[]): CoachInsightConcept[] {
  // Rank the complete selection before any guidance requests, including older
  // responses containing more than six concepts. Several can share a pillar.
  return concepts.filter((concept) => concept.status === "off_track")
    .sort((left, right) => left.score - right.score)
    .slice(0, MAX_FOCUS_CONCEPTS);
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

function ConceptGuidance({ userId, concept, weekStart, through, onRefresh }: {
  userId: string;
  concept: CoachInsightConcept;
  weekStart: string;
  through: string;
  onRefresh: () => void;
}) {
  const [guidance, setGuidance] = useState<PillarProgressGuidance | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [retry, setRetry] = useState(0);
  const { pillar_key: pillarKey, concept_key: conceptKey } = concept;
  const palette = getPillarPalette(pillarKey);

  useEffect(() => {
    const controller = new AbortController();
    setGuidance(null);
    setLoading(true);
    setError(null);
    const load = async () => {
      try {
        const payload = await requestConceptGuidance({
          userId, pillarKey, conceptKey, weekStart, through, signal: controller.signal,
        });
        if (!controller.signal.aborted) setGuidance(payload);
      } catch (loadError) {
        if (!controller.signal.aborted) {
          setError(loadError instanceof Error ? loadError.message : "Could not load this guidance.");
        }
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    };
    void load();
    return () => controller.abort();
  }, [userId, pillarKey, conceptKey, weekStart, through, retry]);

  return (
    <article className="space-y-4" aria-label={`${concept.label}: off track`}>
      <div className="flex items-center gap-3 px-1">
        <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full" style={{ color: palette.accent, backgroundColor: palette.bg }}>
          <PillarIcon pillarKey={pillarKey} className="h-6 w-6" />
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-xs text-[var(--text-secondary)]">{concept.pillar_label || palette.label}</p>
          <h3 className="mt-0.5 text-lg font-semibold leading-snug text-[var(--text-primary)]">{concept.label}</h3>
        </div>
      </div>
      <div aria-live="polite" aria-busy={loading}>
        {loading ? <p role="status" className="px-1 text-base leading-7 text-[var(--text-secondary)]">Preparing guidance for {concept.label.toLowerCase()}…</p> : null}
        {error ? (
          <div className="rounded-3xl border border-[var(--border)] bg-[var(--surface)] p-5">
            <p role="alert" className="text-sm leading-6 text-[var(--text-primary)]">{error}</p>
            <div className="mt-4 flex flex-wrap gap-3">
              <button type="button" onClick={() => setRetry((value) => value + 1)} className="min-h-11 rounded-full border border-[var(--border-strong)] px-5 py-2 text-sm font-semibold">Try again</button>
              <button type="button" onClick={onRefresh} className="min-h-11 px-2 text-sm font-semibold underline underline-offset-4">Refresh insights</button>
            </div>
          </div>
        ) : null}
        {guidance ? <ConceptGuidanceSections guidance={guidance} /> : null}
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
  const offTrack = focusConcepts(result.available_concepts || []);
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
            ? `Guidance for your ${offTrack.length === 1 ? "lowest-scoring concept" : `${offTrack.length} lowest-scoring concepts`} this week.`
            : review.status === "on_track"
              ? "Your recorded concepts are on track so far this week. Keep your current rhythm."
              : allNotApplicable
                ? "Your answers this week mark these concepts as not applicable. No guidance is needed."
                : review.on_track_count > 0
                  ? "Your scored concepts are on track. Some concepts do not yet have scored data to assess."
                  : "There isn't enough scored check-in data this week to identify concepts needing support yet."}
        </p>
      </div>
      {offTrack.map((concept) => (
        <ConceptGuidance
          key={`${userId}:${review.week_start_date}:${review.through_date}:${concept.pillar_key}:${concept.concept_key}`}
          userId={userId}
          concept={concept}
          weekStart={review.week_start_date!}
          through={review.through_date!}
          onRefresh={() => setReload((value) => value + 1)}
        />
      ))}
    </section>
  );
}
