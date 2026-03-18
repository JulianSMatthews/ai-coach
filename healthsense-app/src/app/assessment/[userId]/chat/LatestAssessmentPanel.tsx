import type { AssessmentResponse } from "@/lib/api";
import { getPillarPalette } from "@/lib/pillars";
import { ScoreRing } from "@/components/ui";

type LatestAssessmentPanelProps = {
  assessment: AssessmentResponse;
};

type ResultPillar = {
  pillar_key: string;
  label: string;
  score: number;
};

function normalizePillars(assessment: AssessmentResponse): ResultPillar[] {
  return Array.isArray(assessment.pillars)
    ? assessment.pillars.flatMap((pillar) => {
        const key = String(pillar?.pillar_key || "").trim();
        const label = String(pillar?.pillar_name || "").trim();
        const score = Number(pillar?.score);
        if (!key || !label || !Number.isFinite(score)) {
          return [];
        }
        return [{ pillar_key: key, label, score: Math.round(score) }];
      })
    : [];
}

export default function LatestAssessmentPanel({ assessment }: LatestAssessmentPanelProps) {
  const pillars = normalizePillars(assessment).sort((a, b) => b.score - a.score);

  if (!pillars.length) {
    return null;
  }

  return (
    <section className="rounded-[28px] border border-[#e7e1d6] bg-[#fffaf3] px-4 py-5 shadow-[0_30px_80px_-60px_rgba(30,27,22,0.45)] sm:px-5 sm:py-6">
      <div className="grid grid-cols-2 gap-3">
        {pillars.map((pillar) => {
          const palette = getPillarPalette(pillar.pillar_key);
          return (
            <div key={pillar.pillar_key} className="rounded-2xl border border-[#efe7db] bg-white px-3 py-4">
              <div className="flex flex-col items-center text-center">
                <ScoreRing value={pillar.score} tone={palette.accent} />
                <p className="mt-3 text-sm font-semibold text-[#1e1b16]">{pillar.label}</p>
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}
