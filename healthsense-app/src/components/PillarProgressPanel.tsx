"use client";

import { useCallback, useEffect, useRef, useState, type CSSProperties } from "react";
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
import { getPillarPalette } from "@/lib/pillars";
import PillarIcon from "@/components/PillarIcon";
import styles from "./PillarProgressPanel.module.css";

type PillarProgressPanelProps = {
  userId: string;
  initialPillarKey?: string | null;
  onBack: () => void;
  onEditGoals: () => void;
};

type Selection = { pillar: PillarProgressPillar; concept: PillarProgressConcept };

function GuidanceIcon({ kind }: { kind: "step" | "reflection" }) {
  return (
    <svg
      viewBox="0 0 24 24"
      className="h-7 w-7 shrink-0"
      aria-hidden="true"
      focusable="false"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      {kind === "step" ? (
        <>
          <path d="M15.5 3C13.9 3 13 5 13 7.5c0 1.8.8 3 2.5 3s2.5-1.2 2.5-3C18 5 17.1 3 15.5 3Z" />
          <path d="M14 13h3v1.5a1.5 1.5 0 0 1-3 0Z" />
          <path d="M7.5 8C5.9 8 5 10 5 12.5c0 1.8.8 3 2.5 3s2.5-1.2 2.5-3C10 10 9.1 8 7.5 8Z" />
          <path d="M6 18h3v1.5a1.5 1.5 0 0 1-3 0Z" />
        </>
      ) : (
        <>
          <ellipse cx="12" cy="9" rx="9" ry="6" />
          <circle cx="6.5" cy="18" r="1.5" />
          <circle cx="3.5" cy="21" r="0.75" />
        </>
      )}
    </svg>
  );
}

function ProgressCircle({ score, status, context = false }: { score: number | null; status: PillarProgressStatus; context?: boolean }) {
  return (
    <span
      className={`${styles.scoreCircle} flex shrink-0 items-center justify-center rounded-full font-semibold tabular-nums ${context ? "h-12 w-12 border-[3px] text-[17px]" : "h-16 w-16 border-[4px] text-xl"}`}
      style={{ borderColor: progressStatusColor(status, score) }}
      aria-hidden="true"
    >
      <span className="leading-none">{progressScoreLabel(score)}</span>
    </span>
  );
}

function ForwardChevron() {
  return (
    <svg viewBox="0 0 24 24" className="h-5 w-5 shrink-0" aria-hidden="true" focusable="false" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="m9 5 7 7-7 7" />
    </svg>
  );
}

function PillarScoreBreakdown({ pillar }: { pillar: PillarProgressPillar }) {
  return (
    <div className="text-sm leading-6 text-[var(--text-secondary)]">
      <p>{pillar.score_explanation}</p>
      <ul className="mt-3 space-y-2">
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
    </div>
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

export default function PillarProgressPanel({ userId, initialPillarKey = null, onBack, onEditGoals }: PillarProgressPanelProps) {
  const [progress, setProgress] = useState<PillarProgressResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reload, setReload] = useState(0);
  const [selection, setSelection] = useState<Selection | null>(null);
  const [pillarDetail, setPillarDetail] = useState<PillarProgressPillar | null>(null);
  const [guidance, setGuidance] = useState<PillarProgressGuidance | null>(null);
  const [guidanceLoading, setGuidanceLoading] = useState(false);
  const [guidanceError, setGuidanceError] = useState<string | null>(null);
  const guidanceRequestRef = useRef<AbortController | null>(null);
  const guidanceVersionRef = useRef(0);
  const guidanceHeadingRef = useRef<HTMLHeadingElement | null>(null);
  const conceptButtonRefs = useRef<Map<string, HTMLButtonElement>>(new Map());

  useEffect(() => {
    const controller = new AbortController();
    const loadProgress = async () => {
      guidanceVersionRef.current += 1;
      guidanceRequestRef.current?.abort();
      setSelection(null);
      setPillarDetail(null);
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
        if (!controller.signal.aborted) {
          const nextProgress = payload as PillarProgressResponse;
          const requestedPillarKey = String(initialPillarKey || "").trim().toLowerCase();
          setProgress(nextProgress);
          setPillarDetail(nextProgress.pillars.find((pillar) => pillar.pillar_key === requestedPillarKey) ?? null);
        }
      } catch (loadError) {
        if (!controller.signal.aborted) setError(loadError instanceof Error ? loadError.message : "Could not load your progress.");
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    };
    void loadProgress();
    return () => controller.abort();
  }, [initialPillarKey, reload, userId]);

  useEffect(() => () => {
    guidanceVersionRef.current += 1;
    guidanceRequestRef.current?.abort();
  }, []);

  useEffect(() => {
    if (selection || pillarDetail) guidanceHeadingRef.current?.focus();
  }, [selection, pillarDetail]);

  const closeGuidance = useCallback(() => {
    const returnKey = selection
      ? `${selection.pillar.pillar_key}:${selection.concept.concept_key}`
      : pillarDetail ? `pillar:${pillarDetail.pillar_key}` : null;
    guidanceVersionRef.current += 1;
    guidanceRequestRef.current?.abort();
    setSelection(null);
    setPillarDetail(selection?.pillar ?? null);
    setGuidance(null);
    setGuidanceError(null);
    setGuidanceLoading(false);
    requestAnimationFrame(() => {
      if (returnKey) conceptButtonRefs.current.get(returnKey)?.focus();
    });
  }, [pillarDetail, selection]);

  const loadGuidance = useCallback(async (next: Selection) => {
    if (!progress) return;
    guidanceRequestRef.current?.abort();
    const controller = new AbortController();
    guidanceRequestRef.current = controller;
    const version = ++guidanceVersionRef.current;
    setSelection(next);
    setPillarDetail(next.pillar);
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

  const openPillarDetail = useCallback((pillar: PillarProgressPillar) => {
    guidanceVersionRef.current += 1;
    guidanceRequestRef.current?.abort();
    setSelection(null);
    setPillarDetail(pillar);
    setGuidance(null);
    setGuidanceError(null);
    setGuidanceLoading(false);
  }, []);

  const detailOpen = Boolean(selection || pillarDetail);
  const selectionHasScoredAnswers = Boolean(selection && selection.concept.scored_days_count > 0);

  return (
    <section className={`flex h-full min-h-0 flex-col ${detailOpen ? "pb-28 pt-4 sm:pb-32 sm:pt-6" : "pb-[calc(6rem+env(safe-area-inset-bottom))] pt-1 sm:pt-2"}`} aria-label="Pillar progress">
      <div className={`shrink-0 ${detailOpen ? "px-4 pb-3 sm:px-5" : "px-2 pb-1 sm:px-4"}`}>
        <div className="flex min-h-11 items-center justify-between gap-3">
          <button
            type="button"
            onClick={detailOpen ? closeGuidance : onBack}
            className={`flex shrink-0 items-center justify-center rounded-full border border-[var(--border)] bg-[var(--surface)] text-[var(--text-primary)] shadow-[0_10px_26px_-22px_rgba(30,27,22,0.45)] focus-visible:outline-2 focus-visible:outline-offset-2 ${detailOpen ? "min-h-11 gap-2 px-4 py-2" : "h-10 w-10"}`}
            aria-label={selection ? "Back to concepts" : pillarDetail ? "Back to pillars" : "Back to check-ins"}
          >
            <span className="text-3xl leading-none" aria-hidden="true">‹</span>
            {detailOpen ? <span className="text-[14px] font-semibold">{selection ? "Back to concepts" : "Back to pillars"}</span> : null}
          </button>
          {!detailOpen ? <h2 className="min-w-0 flex-1 text-[22px] font-semibold leading-7 tracking-[-0.02em] text-[var(--text-primary)]" style={{ fontFamily: "var(--font-body), system-ui, sans-serif" }}>Pillar progress</h2> : null}
          {!detailOpen ? (
            <button type="button" onClick={onEditGoals} className="min-h-11 shrink-0 px-1 text-[11px] font-semibold text-[var(--text-secondary)] underline underline-offset-4">
              Edit goals
            </button>
          ) : null}
        </div>
      </div>

      <div className={`coach-scrollbar min-h-0 flex-1 overflow-y-auto overscroll-contain ${detailOpen ? "px-4 pb-8 sm:px-5" : "px-2 pb-1 sm:px-4"}`}>
        {selection ? (
          <div className="space-y-4">
            <div className={`${styles.pillarSurface} flex items-center gap-3 rounded-[24px] border px-4 py-3`}>
              <span className="h-7 w-7 shrink-0" style={{ color: getPillarPalette(selection.pillar.pillar_key).accent }}><PillarIcon pillarKey={selection.pillar.pillar_key} className="h-full w-full" /></span>
              <div className="min-w-0 flex-1">
                <p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-[var(--text-secondary)]">{selection.pillar.label}{selection.concept.is_historical ? " · Earlier question" : ""}</p>
                <h2 ref={guidanceHeadingRef} tabIndex={-1} className="mt-1 text-[22px] font-semibold leading-tight text-[var(--text-primary)] focus:outline-none">{selection.concept.label}</h2>
              </div>
              <span role="img" aria-label={`${selection.concept.label}: ${selection.concept.score == null ? "not scored" : `${progressScoreLabel(selection.concept.score)} out of 100`}, ${progressStatusLabel(selection.concept.status, selection.concept.score)}`}><ProgressCircle score={selection.concept.score} status={selection.concept.status} context /></span>
            </div>

            {!selectionHasScoredAnswers ? (
              <div className="rounded-3xl border border-[var(--border)] bg-[var(--surface)] p-5">
                <p className="text-base leading-7 text-[var(--text-primary)]">{selection.concept.helper}</p>
                <Coverage concept={selection.concept} />
                <div className="mt-3 space-y-2 text-sm leading-6 text-[var(--text-secondary)]">
                  <p>{selection.concept.concept_key === "adaptability" && selection.concept.not_applicable_days_count > 0 ? "No challenges reported in your answered check-ins." : "No scored check-ins yet."}</p>
                  <p>{selection.concept.not_applicable_days_count > 0 ? "Answers marked not applicable do not affect your score. " : ""}Guidance will be available once you have a scored check-in for this question.</p>
                </div>
              </div>
            ) : null}

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
                    { title: "One small step", icon: "step" as const, body: guidance.action, animation: styles.guidanceReveal },
                    { title: "A moment to reflect", icon: "reflection" as const, body: guidance.reflection, animation: `${styles.guidanceReveal} ${styles.reflectionReveal}` },
                  ].map((item) => (
                    <div key={`${guidance.pillar_key}:${guidance.concept_key}:${item.title}`} className={`${item.animation} rounded-3xl border border-[var(--border)] bg-[var(--surface)] p-5 sm:p-6`}>
                      <h3 className="flex items-center gap-2 text-base font-semibold text-[var(--text-primary)]">
                        <GuidanceIcon kind={item.icon} />
                        <span>{item.title}</span>
                      </h3>
                      <p className="mt-2 whitespace-pre-line text-base leading-7 text-[var(--text-secondary)]">{item.body}</p>
                    </div>
                  ))}
                </div>
              ) : null}
            </div>

            {!selectionHasScoredAnswers ? <details className="rounded-3xl border border-[var(--border)] bg-[var(--surface)] p-5">
              <summary className="cursor-pointer text-sm font-semibold text-[var(--text-primary)]">Your check-ins this week</summary>
              <ul className="mt-3 divide-y divide-[var(--border)]">
                {selection.concept.days.map((day) => (
                  <li key={day.date} className="flex items-center justify-between gap-4 py-3 text-sm text-[var(--text-secondary)]">
                    <span>{day.label}</span>
                    <span className="text-right">{day.value_label || (day.not_applicable ? "Not scored" : "No check-in")}</span>
                  </li>
                ))}
              </ul>
            </details> : null}
          </div>
        ) : pillarDetail ? (
          <div className="space-y-5">
            <div className={`${styles.pillarSurface} rounded-[28px] p-6`} style={{ "--pillar-background": getPillarPalette(pillarDetail.pillar_key).bg } as CSSProperties}>
              <div className="flex items-center justify-between gap-4">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="h-7 w-7 shrink-0" style={{ color: getPillarPalette(pillarDetail.pillar_key).accent }}><PillarIcon pillarKey={pillarDetail.pillar_key} className="h-full w-full" /></span>
                    <h2 ref={guidanceHeadingRef} tabIndex={-1} className="text-[1.8rem] font-semibold leading-tight focus:outline-none">{pillarDetail.label}</h2>
                  </div>
                  <p className="mt-2 text-[14px] leading-6">{pillarDetail.completed_days_count} of {pillarDetail.elapsed_days} daily check-ins complete</p>
                  <p className="mt-1 text-[12px] font-semibold">{progressStatusLabel(pillarDetail.status, pillarDetail.score)}</p>
                </div>
                <span role="img" aria-label={`${pillarDetail.label}: ${pillarDetail.score == null ? "not scored" : `${progressScoreLabel(pillarDetail.score)} out of 100`}`}><ProgressCircle score={pillarDetail.score} status={pillarDetail.status} /></span>
              </div>
            </div>
            <section aria-label={`${pillarDetail.label} concept scores`} className="space-y-3">
              <div>
                <h3 className="text-base font-semibold text-[var(--text-primary)]">Concept scores</h3>
                <p className="mt-1 text-[13px] leading-5 text-[var(--text-secondary)]">Choose a concept for guidance or your check-ins.</p>
              </div>
              <div className="space-y-2">
                {pillarDetail.concepts.map((concept) => (
                  <button
                    key={concept.concept_key}
                    type="button"
                    ref={(node) => {
                      const key = `${pillarDetail.pillar_key}:${concept.concept_key}`;
                      if (node) conceptButtonRefs.current.set(key, node);
                      else conceptButtonRefs.current.delete(key);
                    }}
                    onClick={() => void loadGuidance({ pillar: pillarDetail, concept })}
                    className="flex min-h-20 w-full items-center gap-3 rounded-2xl border border-[var(--border)] bg-[var(--surface)] px-4 py-3 text-left text-[var(--text-primary)] transition active:scale-[0.99] focus-visible:outline-2 focus-visible:outline-offset-2"
                    aria-label={conceptProgressAriaLabel(concept)}
                  >
                    <ProgressCircle score={concept.score} status={concept.status} context />
                    <span className="min-w-0 flex-1">
                      <span className="block text-[16px] font-semibold leading-snug">{concept.label}</span>
                      <span className="mt-1 block text-[11px] leading-4 text-[var(--text-secondary)]">{progressStatusLabel(concept.status, concept.score)}{concept.is_historical ? " · Earlier question" : ""}</span>
                    </span>
                    <span className="flex shrink-0 items-center gap-1 text-[11px] font-semibold">
                      <span className="max-w-[4rem] leading-tight sm:max-w-none">{concept.scored_days_count > 0 ? "Get guidance" : "View check-ins"}</span>
                      <ForwardChevron />
                    </span>
                  </button>
                ))}
                {!pillarDetail.concepts.length ? <p className="rounded-2xl bg-[var(--surface-muted)] p-4 text-sm text-[var(--text-secondary)]">No concepts are available for this pillar yet.</p> : null}
              </div>
            </section>
            <details className="rounded-3xl border border-[var(--border)] bg-[var(--surface)] p-5">
              <summary className="cursor-pointer text-sm font-semibold text-[var(--text-primary)]">How this score is made</summary>
              <div className="mt-3"><PillarScoreBreakdown pillar={pillarDetail} /></div>
            </details>
            {progress?.rag_explanation ? <p className="px-1 text-xs leading-6 text-[var(--text-secondary)]">{progress.rag_explanation}</p> : null}
          </div>
        ) : (
          <div className="flex h-full min-h-0 flex-col gap-2">
            {progress ? <p className="shrink-0 text-[11px] leading-5 text-[var(--text-secondary)]">{progressWeekLabel(progress.week.start, progress.week.through)} · Week to date · Choose a pillar</p> : null}
            {loading ? <p role="status" className="text-sm text-[var(--text-secondary)]">Loading your progress…</p> : null}
            {error ? (
              <div className="rounded-3xl border border-[var(--border)] bg-[var(--surface)] p-5">
                <p role="alert" className="text-sm text-[var(--text-primary)]">{error}</p>
                <button type="button" onClick={() => setReload((value) => value + 1)} className="mt-4 min-h-11 rounded-full border border-[var(--border-strong)] px-5 py-2 text-sm font-semibold">Try again</button>
              </div>
            ) : null}
            {progress ? (
              <div
                className="grid flex-1 gap-2"
                style={{
                  gridTemplateRows: `repeat(${Math.max(1, progress.pillars.length)}, minmax(76px, 1fr))`,
                  minHeight: Math.max(0, progress.pillars.length * 76 + (progress.pillars.length - 1) * 8),
                }}
              >
                {sortProgressPillars(progress.pillars).map((pillar) => {
                  const palette = getPillarPalette(pillar.pillar_key);
                  return (
                    <article
                      key={pillar.pillar_key}
                      aria-label={`${pillar.label} progress`}
                      className={`${styles.pillarSurface} min-h-[76px] rounded-[18px] border`}
                      style={{ "--pillar-background": palette.bg, "--pillar-border": palette.border } as CSSProperties}
                    >
                      <button
                        type="button"
                        ref={(node) => {
                          const key = `pillar:${pillar.pillar_key}`;
                          if (node) conceptButtonRefs.current.set(key, node);
                          else conceptButtonRefs.current.delete(key);
                        }}
                        onClick={() => openPillarDetail(pillar)}
                        className="flex h-full min-h-[76px] w-full items-center gap-2 rounded-[18px] px-3 py-2 text-left transition active:scale-[0.99] focus-visible:outline-2 focus-visible:outline-offset-2 sm:gap-3 sm:px-4"
                        aria-label={`${pillar.label}: ${pillar.score == null ? "not scored" : `${progressScoreLabel(pillar.score)} out of 100`}, ${progressStatusLabel(pillar.status, pillar.score)}. View concepts`}
                      >
                        <span className="h-7 w-7 shrink-0" style={{ color: palette.accent }}><PillarIcon pillarKey={pillar.pillar_key} className="h-full w-full" /></span>
                        <span className="min-w-0 flex-1">
                          <span className="block text-[17px] font-semibold leading-tight">{pillar.label}</span>
                          <span className="mt-1 block text-[11px] leading-4">{progressStatusLabel(pillar.status, pillar.score)}</span>
                        </span>
                        <ProgressCircle score={pillar.score} status={pillar.status} context />
                        <span className="flex shrink-0 items-center gap-1 text-[11px] font-semibold">
                          <span className="max-w-[4rem] leading-tight sm:max-w-none">View concepts</span>
                          <ForwardChevron />
                        </span>
                      </button>
                    </article>
                  );
                })}
                {!progress.pillars.length ? <p className="rounded-3xl bg-[var(--surface-muted)] p-5 text-base leading-7 text-[var(--text-secondary)]">Choose your pillars in Preferences to start building your progress.</p> : null}
              </div>
            ) : null}
          </div>
        )}
      </div>
    </section>
  );
}
