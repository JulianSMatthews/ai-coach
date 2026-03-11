"use client";

import { ProgressBar } from "@/components/ui";

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
  onSelect: (option: AssessmentPromptOption) => void;
  onRedo: () => void;
  onRestart: () => void;
};

function helperText(prompt: AssessmentCurrentPrompt): string {
  if (prompt.kind === "readiness_scale") {
    return "One = Strongly disagree. Three = Unsure. Five = Strongly agree.";
  }
  if (prompt.measure_label) {
    return `Measure: ${prompt.measure_label}`;
  }
  return "Tap the number that best fits your last 7 days.";
}

export default function AssessmentPromptCard({ prompt, busy = false, onSelect, onRedo, onRestart }: Props) {
  const overallTone = prompt.kind === "readiness_scale" ? "#d3541b" : "var(--accent)";

  return (
    <section className="rounded-[28px] border border-[#e7e1d6] bg-[#fffaf3] p-5 shadow-[0_30px_80px_-60px_rgba(30,27,22,0.45)] sm:p-6">
      <div className="space-y-5">
        <div className="space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <p className="text-xs uppercase tracking-[0.26em] text-[#6b6257]">Assessment chat</p>
              <h2 className="mt-1 text-2xl text-[#1e1b16]">{prompt.section_label}</h2>
            </div>
            <div className="rounded-2xl border border-[#efe7db] bg-white px-4 py-3 text-right">
              <p className="text-[11px] uppercase tracking-[0.24em] text-[#8c7f70]">Question</p>
              <p className="mt-1 text-lg font-semibold text-[#1e1b16]">
                {prompt.question_position}/{prompt.question_total}
              </p>
            </div>
          </div>
          <ProgressBar value={prompt.question_position} max={prompt.question_total} tone={overallTone} />
        </div>

        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
          {prompt.sections.map((section) => {
            const isActive = section.status === "active";
            const tone = isActive ? overallTone : section.status === "complete" ? "#0ba360" : "#d8cdbc";
            return (
              <div
                key={section.key}
                className={
                  isActive
                    ? "rounded-2xl border border-[#f5d0a0] bg-white px-4 py-3"
                    : "rounded-2xl border border-[#efe7db] bg-white/80 px-4 py-3"
                }
              >
                <div className="flex items-center justify-between gap-3">
                  <p className="text-[11px] uppercase tracking-[0.2em] text-[#6b6257]">{section.label}</p>
                  <p className="text-xs font-semibold text-[#3c332b]">
                    {section.value}/{section.total}
                  </p>
                </div>
                <ProgressBar value={section.value} max={Math.max(section.total, 1)} tone={tone} />
              </div>
            );
          })}
        </div>

        <div className="rounded-[24px] border border-[#efe7db] bg-white px-5 py-6 sm:px-6 sm:py-8">
          <div className="space-y-3">
            <p className="text-xs uppercase tracking-[0.22em] text-[#6b6257]">
              {prompt.section_label} {prompt.section_question_index}/{prompt.section_question_total}
            </p>
            {prompt.concept_label ? <p className="text-sm font-semibold uppercase tracking-[0.16em] text-[#d3541b]">{prompt.concept_label}</p> : null}
            <h3 className="text-xl leading-snug text-[#1e1b16] sm:text-[1.75rem]">{prompt.question}</h3>
            <p className="text-sm text-[#6b6257]">{prompt.hint || helperText(prompt)}</p>
          </div>

          <div className="mt-6 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
            {prompt.options.map((option) => (
              <button
                key={`${prompt.section_key}-${option.value}`}
                type="button"
                onClick={() => onSelect(option)}
                disabled={busy}
                className="rounded-2xl border border-[#e7e1d6] bg-[#fffaf0] px-4 py-5 text-left transition hover:border-[var(--accent)] hover:bg-white disabled:cursor-not-allowed disabled:opacity-60"
              >
                <span className="block text-lg font-semibold text-[#1e1b16]">{option.label}</span>
              </button>
            ))}
          </div>

          <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
            <p className="text-xs text-[#8c7f70]">{helperText(prompt)}</p>
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
      </div>
    </section>
  );
}
