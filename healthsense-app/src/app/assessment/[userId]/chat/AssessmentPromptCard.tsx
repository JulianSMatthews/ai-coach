"use client";

import type { ReactNode } from "react";
import { getPillarPalette } from "@/lib/pillars";
import { ProgressBar, ScoreRing } from "@/components/ui";
import LeadAssessmentBranding from "./LeadAssessmentBranding";

export type AssessmentPromptOption = {
  value: string;
  label: string;
  detail?: string | null;
};

export type AssessmentPromptSection = {
  key: string;
  label: string;
  index: number;
  value: number;
  answered: number;
  total: number;
  status: "complete" | "active" | "upcoming";
};

export type AssessmentCurrentPrompt = {
  kind: "concept_scale" | "readiness_scale" | "pillar_reflection" | "pillar_result";
  section_key: string;
  section_label: string;
  section_index: number;
  section_total: number;
  section_question_index: number;
  section_question_total: number;
  question_position: number;
  question_total: number;
  concept_code?: string;
  concept_label?: string;
  question: string;
  measure_label?: string | null;
  hint?: string | null;
  result_preview?: {
    combined?: number | null;
    pillars: Array<{
      pillar_key: string;
      label: string;
      score?: number | null;
      complete?: boolean | null;
    }>;
    readiness?: {
      label: string;
      score?: number | null;
      complete?: boolean | null;
    } | null;
    latest_pillar_key?: string | null;
    latest_pillar_label?: string | null;
    latest_pillar_score?: number | null;
  } | null;
  options: AssessmentPromptOption[];
  sections: AssessmentPromptSection[];
};

export type AssessmentIntroAvatar = {
  url?: string | null;
  title?: string | null;
  script?: string | null;
  posterUrl?: string | null;
};

type Props = {
  prompt: AssessmentCurrentPrompt;
  busy?: boolean;
  selectedValue?: string | null;
  showLeadBranding?: boolean;
  introAvatar?: AssessmentIntroAvatar | null;
  introAvatarEnabledOverride?: boolean | null;
  onSelect: (option: AssessmentPromptOption) => void;
  onRedo: () => void;
  onRestart: () => void;
};

function helperText(): string | null {
  return null;
}

function isRedundantHint(text: string | null | undefined): boolean {
  const normalized = String(text || "").trim().toLowerCase();
  return normalized === "tap the number that best fits your last 7 days.";
}

function sectionPct(section: AssessmentPromptSection): number {
  const total = Number(section.total || 0);
  const value = Number(section.value || section.answered || 0);
  if (total <= 0) {
    return section.status === "complete" ? 100 : 0;
  }
  return Math.max(0, Math.min(100, (value / total) * 100));
}

function promptHint(prompt: AssessmentCurrentPrompt): string | null {
  const hint = String(prompt.hint || "").trim();
  if (hint && !isRedundantHint(hint)) {
    return hint;
  }
  return helperText();
}

function normalizePreviewScore(value: number | null | undefined): number | null {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return null;
  return Math.max(0, Math.min(100, Math.round(parsed)));
}

function previewPillarExtremes(
  pillars: Array<{ pillar_key: string; label: string; score?: number | null; complete?: boolean | null }>,
): {
  strongest: { label: string; score: number } | null;
  weakest: { label: string; score: number } | null;
} {
  const completed = pillars
    .map((pillar) => ({
      label: String(pillar.label || "").trim(),
      score: normalizePreviewScore(pillar.score),
    }))
    .filter(
      (pillar): pillar is { label: string; score: number } =>
        Boolean(pillar.label) && pillar.score !== null,
    );
  if (!completed.length) {
    return { strongest: null, weakest: null };
  }
  const sorted = [...completed].sort((a, b) => a.score - b.score);
  return {
    weakest: sorted[0] || null,
    strongest: sorted[sorted.length - 1] || null,
  };
}

function sortPreviewPillars(
  pillars: Array<{ pillar_key: string; label: string; score?: number | null; complete?: boolean | null }>,
): Array<{ pillar_key: string; label: string; score?: number | null; complete?: boolean | null }> {
  return [...pillars].sort((a, b) => {
    const aScore = normalizePreviewScore(a.score);
    const bScore = normalizePreviewScore(b.score);
    if (aScore === null && bScore === null) return 0;
    if (aScore === null) return 1;
    if (bScore === null) return -1;
    return bScore - aScore;
  });
}

function renderFormattedQuestion(text: string): ReactNode {
  const raw = String(text || "");
  if (!raw.includes("*")) return raw;
  const parts = raw.split(/(\*[^*]+\*)/g).filter(Boolean);
  return parts.map((part, idx) => {
    if (part.startsWith("*") && part.endsWith("*") && part.length > 2) {
      return <strong key={`strong-${idx}`} className="font-bold">{part.slice(1, -1)}</strong>;
    }
    return <span key={`text-${idx}`}>{part}</span>;
  });
}

const LEAD_INTRO_PREVIEW: NonNullable<AssessmentCurrentPrompt["result_preview"]> = {
  combined: 66,
  pillars: [
    { pillar_key: "nutrition", label: "Nutrition", score: 48, complete: true },
    { pillar_key: "training", label: "Training", score: 72, complete: true },
    { pillar_key: "recovery", label: "Recovery", score: 69, complete: true },
    { pillar_key: "resilience", label: "Resilience", score: 75, complete: true },
  ],
  readiness: null,
};

const INTRO_AVATAR_ENABLED = ["1", "true", "yes", "on"].includes(
  String(process.env.NEXT_PUBLIC_ASSESSMENT_INTRO_AVATAR_ENABLED || "").trim().toLowerCase(),
);
const INTRO_AVATAR_URL = String(process.env.NEXT_PUBLIC_ASSESSMENT_INTRO_AVATAR_URL || "").trim();
const INTRO_AVATAR_POSTER = String(process.env.NEXT_PUBLIC_ASSESSMENT_INTRO_AVATAR_POSTER || "").trim();
export default function AssessmentPromptCard({
  prompt,
  busy = false,
  selectedValue = null,
  showLeadBranding = false,
  introAvatar = null,
  introAvatarEnabledOverride = null,
  onSelect,
  onRedo,
  onRestart,
}: Props) {
  const tone = prompt.kind === "readiness_scale" ? "#d3541b" : "var(--accent)";
  const hint = promptHint(prompt);
  const isIntroPrompt = prompt.kind === "pillar_reflection";
  const isPillarResultPrompt = prompt.kind === "pillar_result";
  const showSectionProgress = !isIntroPrompt && !isPillarResultPrompt && prompt.sections.length > 0;
  const showQuestionProgress = !isIntroPrompt && !isPillarResultPrompt && prompt.section_question_total > 0;
  const showPromptActions = !isIntroPrompt && !isPillarResultPrompt;
  const showPromptHeader =
    showSectionProgress ||
    showQuestionProgress ||
    Boolean(String(prompt.section_label || "").trim()) ||
    Boolean(String(prompt.concept_label || "").trim());
  const showLeadIntroPreview = prompt.section_key === "lead_intro";
  const promptPreview = showLeadIntroPreview ? LEAD_INTRO_PREVIEW : prompt.result_preview;
  const showScorePreview = Boolean(promptPreview?.pillars?.length);
  const combinedPreviewScore = normalizePreviewScore(promptPreview?.combined);
  const previewExtremes = promptPreview ? previewPillarExtremes(promptPreview.pillars) : { strongest: null, weakest: null };
  const sortedPreviewPillars = promptPreview ? sortPreviewPillars(promptPreview.pillars) : [];
  const completedPreviewPillarCount = promptPreview
    ? promptPreview.pillars.filter((pillar) => normalizePreviewScore(pillar.score) !== null).length
    : 0;
  const showPreviewExtremes = Boolean(
    previewExtremes.strongest &&
      previewExtremes.weakest &&
      (showLeadIntroPreview || completedPreviewPillarCount >= 2),
  );
  const introAvatarUrl = String(introAvatar?.url || INTRO_AVATAR_URL || "").trim();
  const introAvatarPoster = String(introAvatar?.posterUrl || INTRO_AVATAR_POSTER || "").trim();
  const introAvatarEnabled =
    typeof introAvatarEnabledOverride === "boolean" ? introAvatarEnabledOverride : INTRO_AVATAR_ENABLED;
  const showIntroAvatar = showLeadIntroPreview && introAvatarEnabled && Boolean(introAvatarUrl);
  const singleOptionPrompt = prompt.options.length === 1;

  return (
    <section className="w-full rounded-[28px] border border-[#e7e1d6] bg-[#fffaf3] px-4 py-6 shadow-[0_30px_80px_-60px_rgba(30,27,22,0.45)] sm:px-6 sm:py-8">
      <div className="space-y-5">
        {showLeadBranding && !showIntroAvatar ? (
          <div className="border-b border-[#eadfce] pb-5">
            <LeadAssessmentBranding
              className={
                showLeadIntroPreview
                  ? "text-[1.75rem] font-medium leading-[1.05] sm:text-[2.35rem]"
                  : ""
              }
              logoClassName={
                showLeadIntroPreview
                  ? "h-10 w-10 flex-none sm:h-12 sm:w-12"
                  : "h-8 w-8 flex-none sm:h-9 sm:w-9"
              }
              titleLines={
                showLeadIntroPreview
                  ? ["HealthSense measures four pillars of health to find the one limiting your progress."]
                  : undefined
              }
            />
          </div>
        ) : null}
        {showPromptHeader ? (
          <div className="space-y-3">
            {showSectionProgress ? (
              <div
                className="grid gap-2"
                style={{ gridTemplateColumns: `repeat(${prompt.sections.length}, minmax(0, 1fr))` }}
                aria-label="Overall assessment progress"
              >
                {prompt.sections.map((section) => (
                  <div key={section.key} className="h-2 overflow-hidden rounded-full bg-[#eadfce]">
                    <div
                      className="h-full rounded-full"
                      style={{
                        width: `${sectionPct(section)}%`,
                        background: tone,
                      }}
                    />
                  </div>
                ))}
              </div>
            ) : null}
            {String(prompt.section_label || "").trim() || String(prompt.concept_label || "").trim() ? (
              <div className="flex flex-wrap items-end justify-between gap-3">
                <div>
                  {String(prompt.section_label || "").trim() ? (
                    <h2 className="text-2xl text-[#1e1b16]">{prompt.section_label}</h2>
                  ) : null}
                  {prompt.concept_label ? (
                    <p className="mt-1 text-sm font-semibold uppercase tracking-[0.16em] text-[#d3541b]">{prompt.concept_label}</p>
                  ) : null}
                  {prompt.measure_label ? (
                    <p className="mt-2 max-w-2xl text-sm text-[#6b6257]">{prompt.measure_label}</p>
                  ) : null}
                </div>
              </div>
            ) : null}
            {showQuestionProgress ? (
              <ProgressBar value={prompt.section_question_index} max={prompt.section_question_total} tone={tone} />
            ) : null}
          </div>
        ) : null}

        {!showScorePreview ? (
          <div className="space-y-4">
            <h3 className="text-xl leading-snug text-[#1e1b16] sm:text-[1.75rem]">{renderFormattedQuestion(prompt.question)}</h3>
            {hint ? <p className="text-sm whitespace-pre-line text-[#6b6257]">{hint}</p> : null}
          </div>
        ) : null}

        {showScorePreview && promptPreview ? (
          <div className="rounded-[28px] border border-[#e7e1d6] bg-white px-4 py-5 shadow-[0_30px_80px_-60px_rgba(30,27,22,0.35)] sm:px-6 sm:py-6">
            <div className="space-y-5">
              {showIntroAvatar ? (
                <video
                  autoPlay
                  controls
                  muted
                  playsInline
                  preload="auto"
                  poster={introAvatarPoster || undefined}
                  className="w-full rounded-2xl border border-[#efe7db] bg-[#f7f4ee]"
                >
                  <source src={introAvatarUrl} />
                </video>
              ) : null}
              <div className="space-y-4">
                <div className="rounded-3xl border border-[#efe7db] bg-[#fffaf3] px-5 py-5">
                  <div className="flex items-center gap-4">
                    <LeadAssessmentBranding
                      titleLines={[]}
                      logoClassName="h-11 w-11 flex-none sm:h-12 sm:w-12"
                    />
                    <div className="min-w-0 flex-1 space-y-2">
                      <p className="text-xs uppercase tracking-[0.22em] text-[#6b6257]">
                        {showLeadIntroPreview ? "Example HealthSense Score" : "HealthSense Score"}
                      </p>
                      <p className="text-4xl font-semibold text-[#1e1b16]">
                        {combinedPreviewScore ?? "--"}
                      </p>
                      <ProgressBar value={combinedPreviewScore ?? 0} max={100} tone="var(--accent)" />
                    </div>
                  </div>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3 sm:gap-4">
                {sortedPreviewPillars.map((pillar) => {
                  const palette = getPillarPalette(pillar.pillar_key);
                  const pillarScore = normalizePreviewScore(pillar.score);
                  const isComplete = pillar.complete !== false && pillarScore !== null;
                  const isStrongest =
                    showPreviewExtremes &&
                    isComplete &&
                    previewExtremes.strongest?.label === pillar.label &&
                    pillarScore === previewExtremes.strongest.score;
                  const isWeakest =
                    showPreviewExtremes &&
                    isComplete &&
                    previewExtremes.weakest?.label === pillar.label &&
                    pillarScore === previewExtremes.weakest.score;
                  return (
                    <div key={pillar.pillar_key} className="rounded-2xl border border-[#efe7db] bg-[#fffaf3] px-4 py-5">
                      <div className="flex flex-col items-center text-center">
                        <ScoreRing value={pillarScore ?? 0} tone={isComplete ? palette.accent : "#d8d0c2"} />
                        <p className="mt-3 text-sm font-semibold text-[#1e1b16]">
                          {pillar.label}
                          {isStrongest ? <strong> (strongest)</strong> : null}
                          {isWeakest ? <strong> (weakest)</strong> : null}
                        </p>
                        {!isComplete ? (
                          <p className="mt-1 text-xs font-semibold uppercase tracking-[0.18em] text-[#8c7f70]">
                            Pending
                          </p>
                        ) : null}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          </div>
        ) : null}

        <div className={singleOptionPrompt ? "grid grid-cols-1 gap-3" : "grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4"}>
          {prompt.options.map((option) => {
            const isSelected = selectedValue === option.value;
            return (
              <button
                key={`${prompt.section_key}-${option.value}`}
                type="button"
                onClick={() => onSelect(option)}
                disabled={busy}
                className={
                  isSelected
                    ? `rounded-2xl border border-[var(--accent)] bg-white px-4 py-5 text-[var(--accent)] transition disabled:cursor-not-allowed disabled:opacity-70 ${singleOptionPrompt ? "text-center" : "text-left"}`
                    : `rounded-2xl border border-[var(--accent)] bg-[var(--accent)] px-4 py-5 text-white transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60 ${singleOptionPrompt ? "text-center" : "text-left"}`
                }
              >
                <span
                  className={
                    isSelected
                      ? `block text-lg font-semibold text-[var(--accent)] ${singleOptionPrompt ? "text-center" : ""}`
                      : `block text-lg font-semibold text-white ${singleOptionPrompt ? "text-center" : ""}`
                  }
                >
                  {option.label}
                </span>
              </button>
            );
          })}
        </div>

        {showPromptActions ? (
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                onClick={onRedo}
                disabled={busy}
                className="rounded-full border border-[#e0d4c3] bg-white px-4 py-2 text-xs uppercase tracking-[0.18em] text-[#3c332b] disabled:cursor-not-allowed disabled:opacity-60"
              >
                Redo
              </button>
              <button
                type="button"
                onClick={onRestart}
                disabled={busy}
                className="rounded-full border border-[#e0d4c3] bg-[#fff3dc] px-4 py-2 text-xs uppercase tracking-[0.18em] text-[#3c332b] disabled:cursor-not-allowed disabled:opacity-60"
              >
                Restart
              </button>
            </div>
          </div>
        ) : null}
      </div>
    </section>
  );
}
