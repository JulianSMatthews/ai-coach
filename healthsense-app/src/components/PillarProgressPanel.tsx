"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type {
  PillarProgressConcept,
  PillarProgressGuidance,
  PillarProgressPillar,
  PillarProgressResponse,
  PillarProgressStatus,
} from "@/lib/api";
import {
  conceptProgressAriaLabel,
  progressScoreLabel,
  progressStatusColor,
  progressStatusLabel,
  progressWeekLabel,
  requestConceptGuidance,
  sortProgressPillars,
} from "@/lib/pillarProgress";

type PillarProgressPanelProps = {
  userId: string;
  onBack: () => void;
  onEditGoals: () => void;
};

type Selection = { pillar: PillarProgressPillar; concept: PillarProgressConcept };

function ProgressCircle({ score, status }: { score: number | null; status: PillarProgressStatus }) {
  return (
    <span
      className="flex h-16 w-16 shrink-0 items-center justify-center rounded-full border-[4px] bg-[var(--surface)] text-xl font-semibold tabular-nums text-[var(--text-primary)]"
      style={{ borderColor: progressStatusColor(status, score) }}
      aria-hidden="true"
    >
      {progressScoreLabel(score)}
    </span>
  );
}

function Coverage({ concept }: { concept: PillarProgressConcept }) {
  return (
    <p className="mt-1 text-xs leading-5 text-[var(--text-secondary)]">
      {concept.answered_days_count} of {concept.elapsed_days} days answered
      {concept.not_applicable_days_count > 0 ? ` · ${concept.not_applicable_days_count} not scored` : ""}
    </p>
  );
}

export default function PillarProgressPanel({ userId, onBack, onEditGoals }: PillarProgressPanelProps) {
  const [progress, setProgress] = useState<PillarProgressResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reload, setReload] = useState(0);
  const [selection, setSelection] = useState<Selection | null>(null);
  const [guidance, setGuidance] = useState<PillarProgressGuidance | null>(null);
  const [guidanceLoading, setGuidanceLoading] = useState(false);
  const [guidanceError, setGuidanceError] = useState<string | null>(null);
  const guidanceRequestRef = useRef<AbortController | null>(null);
  const guidanceVersionRef = useRef(0);
  const guidanceHeadingRef = useRef<HTMLHeadingElement | null>(null);
  const lastConceptKeyRef = useRef<string | null>(null);
  const conceptButtonRefs = useRef<Map<string, HTMLButtonElement>>(new Map());

  useEffect(() => {
    const controller = new AbortController();
    const loadProgress = async () => {
      guidanceVersionRef.current += 1;
      guidanceRequestRef.current?.abort();
      setSelection(null);
      setGuidance(null);
      setGuidanceError(null);
      setGuidanceLoading(false);
      setLoading(true);
      setError(null);
      setProgress(null);
      try {
        const params = new URLSearchParams({ userId });
        const response = await fetch(`/api/pillar-progress?${params}`, {
          cache: "no-store", signal: controller.signal,
        });
        const payload = await response.json().catch(() => null);
        if (!response.ok) throw new Error(typeof payload?.error === "string" ? payload.error : "Could not load your progress.");
        if (String(payload?.user_id) !== userId || !Array.isArray(payload?.pillars) || !payload?.week?.start || !payload?.week?.through) {
          throw new Error("Could not load your progress. Please try again.");
        }
        if (!controller.signal.aborted) setProgress(payload as PillarProgressResponse);
      } catch (loadError) {
        if (!controller.signal.aborted) setError(loadError instanceof Error ? loadError.message : "Could not load your progress.");
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    };
    void loadProgress();
    return () => controller.abort();
  }, [reload, userId]);

  useEffect(() => () => {
    guidanceVersionRef.current += 1;
    guidanceRequestRef.current?.abort();
  }, []);

  useEffect(() => {
    if (selection) guidanceHeadingRef.current?.focus();
  }, [selection]);

  const closeGuidance = useCallback(() => {
    guidanceVersionRef.current += 1;
    guidanceRequestRef.current?.abort();
    setSelection(null);
    setGuidance(null);
    setGuidanceError(null);
    setGuidanceLoading(false);
    requestAnimationFrame(() => {
      const key = lastConceptKeyRef.current;
      if (key) conceptButtonRefs.current.get(key)?.focus();
    });
  }, []);

  const loadGuidance = useCallback(async (next: Selection) => {
    if (!progress) return;
    guidanceRequestRef.current?.abort();
    const controller = new AbortController();
    guidanceRequestRef.current = controller;
    const version = ++guidanceVersionRef.current;
    setSelection(next);
    setGuidance(null);
    setGuidanceError(null);
    setGuidanceLoading(next.concept.scored_days_count > 0);
    if (next.concept.scored_days_count === 0) return;
    try {
      const payload = await requestConceptGuidance({
        userId,
        pillarKey: next.pillar.pillar_key,
        conceptKey: next.concept.concept_key,
        weekStart: progress.week.start,
        through: progress.week.through,
        signal: controller.signal,
      });
      if (!controller.signal.aborted && guidanceVersionRef.current === version) setGuidance(payload);
    } catch (loadError) {
      if (!controller.signal.aborted && guidanceVersionRef.current === version) {
        setGuidanceError(loadError instanceof Error ? loadError.message : "Could not load this guidance.");
      }
    } finally {
      if (!controller.signal.aborted && guidanceVersionRef.current === version) setGuidanceLoading(false);
    }
  }, [progress, userId]);

  return (
    <section className="flex h-full min-h-0 flex-col pb-28 pt-4 sm:pb-32 sm:pt-6" aria-label="Pillar progress">
      <div className="shrink-0 px-4 pb-3 sm:px-5">
        <div className="flex items-center justify-between gap-4">
          <button
            type="button"
            onClick={selection ? closeGuidance : onBack}
            className="flex h-12 w-12 items-center justify-center rounded-full border border-[var(--border)] bg-[var(--surface)] text-[var(--text-primary)] shadow-[0_10px_26px_-22px_rgba(30,27,22,0.45)] focus-visible:outline-2 focus-visible:outline-offset-2"
            aria-label={selection ? "Back to pillar progress" : "Back to check-ins"}
          >
            <span className="text-3xl leading-none" aria-hidden="true">‹</span>
          </button>
          {!selection ? (
            <button type="button" onClick={onEditGoals} className="min-h-11 px-2 text-sm font-semibold text-[var(--text-secondary)] underline underline-offset-4">
              Edit goals
            </button>
          ) : null}
        </div>
      </div>

      <div className="coach-scrollbar min-h-0 flex-1 overflow-y-auto overscroll-contain px-4 pb-8 sm:px-5">
        {selection ? (
          <div className="space-y-5">
            <div className="rounded-[28px] bg-[var(--surface-muted)] p-6">
              <p className="text-xs font-semibold uppercase tracking-[0.16em] text-[var(--text-secondary)]">{selection.pillar.label}</p>
              <div className="mt-3 flex items-start justify-between gap-4">
                <div className="min-w-0">
                  <h2 ref={guidanceHeadingRef} tabIndex={-1} className="text-[1.8rem] font-semibold leading-tight text-[var(--text-primary)] focus:outline-none">{selection.concept.label}</h2>
                  <p className="mt-2 text-base leading-7 text-[var(--text-secondary)]">{selection.concept.helper}</p>
                </div>
                <ProgressCircle score={selection.concept.score} status={selection.concept.status} />
              </div>
              <p className="mt-3 text-sm font-semibold text-[var(--text-primary)]">{progressStatusLabel(selection.concept.status, selection.concept.score)}</p>
              <Coverage concept={selection.concept} />
              {selection.concept.scored_days_count === 0 ? (
                <div className="mt-3 space-y-2 text-sm leading-6 text-[var(--text-secondary)]">
                  <p>{selection.concept.concept_key === "adaptability" && selection.concept.not_applicable_days_count > 0 ? "No challenges reported in your answered check-ins." : "No scored check-ins yet."}</p>
                  <p>{selection.concept.not_applicable_days_count > 0 ? "Answers marked not applicable do not affect your score. " : ""}Guidance will be available once you have a scored check-in for this question.</p>
                </div>
              ) : null}
            </div>

            <div aria-live="polite" aria-busy={guidanceLoading}>
              {guidanceLoading ? <p className="px-1 text-base leading-7 text-[var(--text-secondary)]">Preparing guidance for {selection.concept.label.toLowerCase()}…</p> : null}
              {guidanceError ? (
                <div className="rounded-3xl border border-[var(--border)] bg-[var(--surface)] p-5">
                  <p role="alert" className="text-sm leading-6 text-[var(--text-primary)]">{guidanceError}</p>
                  <div className="mt-4 flex flex-wrap gap-3">
                    <button type="button" onClick={() => void loadGuidance(selection)} className="min-h-11 rounded-full border border-[var(--border-strong)] px-5 py-2 text-sm font-semibold">Try again</button>
                    <button type="button" onClick={() => { closeGuidance(); setReload((value) => value + 1); }} className="min-h-11 px-2 text-sm font-semibold underline underline-offset-4">Refresh progress</button>
                  </div>
                </div>
              ) : null}
              {guidance ? (
                <div className="space-y-4">
                  {[
                    { title: "Your insight", body: guidance.insight },
                    { title: "One small step", body: guidance.action },
                    { title: "A moment to reflect", body: guidance.reflection },
                  ].map((item) => (
                    <div key={item.title} className="rounded-3xl border border-[var(--border)] bg-[var(--surface)] p-5 sm:p-6">
                      <h3 className="text-base font-semibold text-[var(--text-primary)]">{item.title}</h3>
                      <p className="mt-2 whitespace-pre-line text-base leading-7 text-[var(--text-secondary)]">{item.body}</p>
                    </div>
                  ))}
                </div>
              ) : null}
            </div>

            <details className="rounded-3xl border border-[var(--border)] bg-[var(--surface)] p-5">
              <summary className="cursor-pointer text-sm font-semibold text-[var(--text-primary)]">Your check-ins this week</summary>
              <ul className="mt-3 divide-y divide-[var(--border)]">
                {selection.concept.days.map((day) => (
                  <li key={day.date} className="flex items-center justify-between gap-4 py-3 text-sm text-[var(--text-secondary)]">
                    <span>{day.label}</span>
                    <span className="text-right">{day.value_label || (day.not_applicable ? "Not scored" : "No check-in")}</span>
                  </li>
                ))}
              </ul>
            </details>
          </div>
        ) : (
          <div className="space-y-5">
            <div>
              <h2 className="text-[1.9rem] font-semibold leading-tight text-[var(--text-primary)]">Pillar progress</h2>
              <p className="mt-2 text-base leading-7 text-[var(--text-secondary)]">Tap a question’s circle for guidance based on your check-ins so far this week.</p>
              {progress ? <p className="mt-2 text-sm font-semibold text-[var(--text-primary)]">{progressWeekLabel(progress.week.start, progress.week.through)} · Week to date</p> : null}
            </div>
            {loading ? <p role="status" className="text-sm text-[var(--text-secondary)]">Loading your progress…</p> : null}
            {error ? (
              <div className="rounded-3xl border border-[var(--border)] bg-[var(--surface)] p-5">
                <p role="alert" className="text-sm text-[var(--text-primary)]">{error}</p>
                <button type="button" onClick={() => setReload((value) => value + 1)} className="mt-4 min-h-11 rounded-full border border-[var(--border-strong)] px-5 py-2 text-sm font-semibold">Try again</button>
              </div>
            ) : null}
            {progress ? (
              <>
                {sortProgressPillars(progress.pillars).map((pillar) => (
                  <article key={pillar.pillar_key} className="overflow-hidden rounded-[28px] border border-[var(--border)] bg-[var(--surface)]">
                    <div className="border-b border-[var(--border)] bg-[var(--surface-muted)] p-5 sm:p-6">
                      <div className="flex items-center justify-between gap-4">
                        <div>
                          <h3 className="text-xl font-semibold text-[var(--text-primary)]">{pillar.label}</h3>
                          <p className="mt-1 text-sm text-[var(--text-secondary)]">{pillar.completed_days_count} of {pillar.elapsed_days} daily check-ins complete</p>
                          <p className="mt-1 text-xs font-semibold text-[var(--text-secondary)]">{progressStatusLabel(pillar.status, pillar.score)}</p>
                        </div>
                        <span role="img" aria-label={`${pillar.label} score: ${progressScoreLabel(pillar.score)} out of 100, ${progressStatusLabel(pillar.status, pillar.score)}`}><ProgressCircle score={pillar.score} status={pillar.status} /></span>
                      </div>
                      <details className="mt-3 text-sm leading-6 text-[var(--text-secondary)]">
                        <summary className="cursor-pointer">How this score is made</summary>
                        <p className="mt-2">{pillar.score_explanation}</p>
                        <ul className="mt-2 space-y-1">
                          {pillar.concepts.map((concept) => (
                            <li key={concept.concept_key} className="flex justify-between gap-4">
                              <span>{concept.label}</span>
                              <span className="shrink-0 tabular-nums">{concept.contribution_points == null ? "Not scored" : `${Number(concept.contribution_points.toFixed(2))} points`}</span>
                            </li>
                          ))}
                          {pillar.rounding_adjustment != null && pillar.rounding_adjustment !== 0 ? (
                            <li className="flex justify-between gap-4">
                              <span>Rounding</span>
                              <span className="shrink-0 tabular-nums">{pillar.rounding_adjustment > 0 ? "+" : ""}{Number(pillar.rounding_adjustment.toFixed(2))} points</span>
                            </li>
                          ) : null}
                          <li className="flex justify-between gap-4 border-t border-[var(--border)] pt-2 font-semibold text-[var(--text-primary)]">
                            <span>Pillar total</span>
                            <span className="shrink-0 tabular-nums">{progressScoreLabel(pillar.score)}{pillar.score == null ? "" : " / 100"}</span>
                          </li>
                        </ul>
                      </details>
                    </div>
                    <div className="divide-y divide-[var(--border)] px-5 sm:px-6">
                      {pillar.concepts.map((concept) => {
                        const statusLabel = progressStatusLabel(concept.status, concept.score);
                        return (
                          <div key={concept.concept_key} className="flex items-center justify-between gap-4 py-5">
                            <div className="min-w-0">
                              <h4 className="text-base font-semibold leading-6 text-[var(--text-primary)]">{concept.label}</h4>
                              {concept.is_historical ? <p className="mt-1 text-xs text-[var(--text-secondary)]">Earlier question · part of this week’s score</p> : null}
                              <p className="mt-1 text-sm leading-6 text-[var(--text-secondary)]">{concept.helper}</p>
                              <Coverage concept={concept} />
                              <p className="mt-1 text-xs font-semibold text-[var(--text-primary)]">{statusLabel}</p>
                            </div>
                            <button
                              type="button"
                              ref={(node) => {
                                const key = `${pillar.pillar_key}:${concept.concept_key}`;
                                if (node) conceptButtonRefs.current.set(key, node);
                                else conceptButtonRefs.current.delete(key);
                              }}
                              onClick={() => { lastConceptKeyRef.current = `${pillar.pillar_key}:${concept.concept_key}`; void loadGuidance({ pillar, concept }); }}
                              className="shrink-0 rounded-full transition active:scale-95 focus-visible:outline-2 focus-visible:outline-offset-4"
                              aria-label={conceptProgressAriaLabel(concept)}
                            >
                              <ProgressCircle score={concept.score} status={concept.status} />
                            </button>
                          </div>
                        );
                      })}
                    </div>
                  </article>
                ))}
                {!progress.pillars.length ? <p className="rounded-3xl bg-[var(--surface-muted)] p-5 text-base leading-7 text-[var(--text-secondary)]">Choose your pillars in Preferences to start building your progress.</p> : null}
                {progress.rag_explanation ? (
                  <details className="rounded-2xl border border-[var(--border)] px-4 py-3 text-xs leading-6 text-[var(--text-secondary)]">
                    <summary className="cursor-pointer font-semibold">What the colours mean</summary>
                    <p className="mt-2">{progress.rag_explanation}</p>
                  </details>
                ) : null}
                <p className="pb-2 text-xs leading-6 text-[var(--text-secondary)]">Scores run from 0 to 100. Grey means no scored answer yet. Missing check-ins and answers marked not applicable are not scored.</p>
              </>
            ) : null}
          </div>
        )}
      </div>
    </section>
  );
}
