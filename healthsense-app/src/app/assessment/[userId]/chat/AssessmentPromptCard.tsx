"use client";

import type { ReactNode } from "react";
import { ProgressBar } from "@/components/ui";
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
  kind: "concept_scale" | "readiness_scale";
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
  options: AssessmentPromptOption[];
  sections: AssessmentPromptSection[];
};

type Props = {
  prompt: AssessmentCurrentPrompt;
  busy?: boolean;
  selectedValue?: string | null;
  showLeadBranding?: boolean;
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

export default function AssessmentPromptCard({
  prompt,
  busy = false,
  selectedValue = null,
  showLeadBranding = false,
  onSelect,
  onRedo,
  onRestart,
}: Props) {
  const tone = prompt.kind === "readiness_scale" ? "#d3541b" : "var(--accent)";
  const hint = promptHint(prompt);

  return (
    <section className="w-full rounded-[28px] border border-[#e7e1d6] bg-[#fffaf3] px-4 py-6 shadow-[0_30px_80px_-60px_rgba(30,27,22,0.45)] sm:px-6 sm:py-8">
      <div className="space-y-5">
        {showLeadBranding ? (
          <div className="border-b border-[#eadfce] pb-5">
            <LeadAssessmentBranding />
          </div>
        ) : null}
        <div className="space-y-3">
          {prompt.sections.length ? (
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
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div>
              <h2 className="text-2xl text-[#1e1b16]">{prompt.section_label}</h2>
              {prompt.concept_label ? (
                <p className="mt-1 text-sm font-semibold uppercase tracking-[0.16em] text-[#d3541b]">{prompt.concept_label}</p>
              ) : null}
            </div>
          </div>
          <ProgressBar value={prompt.section_question_index} max={prompt.section_question_total} tone={tone} />
        </div>

        <div className="space-y-4">
          <h3 className="text-xl leading-snug text-[#1e1b16] sm:text-[1.75rem]">{renderFormattedQuestion(prompt.question)}</h3>
          {hint ? <p className="text-sm text-[#6b6257]">{hint}</p> : null}
        </div>

        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
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
                    ? "rounded-2xl border border-[var(--accent)] bg-white px-4 py-5 text-left text-[var(--accent)] transition disabled:cursor-not-allowed disabled:opacity-70"
                    : "rounded-2xl border border-[var(--accent)] bg-[var(--accent)] px-4 py-5 text-left text-white transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60"
                }
              >
                <span className={isSelected ? "block text-lg font-semibold text-[var(--accent)]" : "block text-lg font-semibold text-white"}>
                  {option.label}
                </span>
              </button>
            );
          })}
        </div>

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
      </div>
    </section>
  );
}
