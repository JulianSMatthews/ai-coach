import type { AssessmentResponse } from "@/lib/api";
import { getPillarPalette } from "@/lib/pillars";
import { ProgressBar, ScoreRing } from "@/components/ui";
import LeadAssessmentBranding from "./LeadAssessmentBranding";

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

function formatDateUk(value?: string | null): string {
  if (!value) return "";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "";
  return new Intl.DateTimeFormat("en-GB", {
    dateStyle: "medium",
    timeZone: "Europe/London",
  }).format(parsed);
}

function summariseText(value?: string | null): string {
  const text = String(value || "").trim().replace(/\s+/g, " ");
  if (!text) return "";
  if (text.length <= 220) return text;
  return `${text.slice(0, 217).trim()}...`;
}

export default function LatestAssessmentPanel({ assessment }: LatestAssessmentPanelProps) {
  const combined = Math.round(
    Number(assessment.scores?.combined ?? assessment.run?.combined_overall ?? 0) || 0,
  );
  const pillars = normalizePillars(assessment).sort((a, b) => b.score - a.score);
  const reportedAt = formatDateUk(assessment.meta?.reported_at || assessment.run?.finished_at || null);
  const avatarUrl = String(assessment.narratives?.completion_summary_avatar_url || "").trim();
  const audioUrl = String(assessment.narratives?.completion_summary_audio_url || "").trim();
  const summaryText = summariseText(assessment.narratives?.completion_summary_text);
  const avatarStatus = String(assessment.narratives?.completion_summary_avatar_status || "").trim().toLowerCase();
  const avatarError = String(assessment.narratives?.completion_summary_avatar_error || "").trim();
  const summaryPending =
    Boolean(assessment.meta?.completion_summary_pending) ||
    avatarStatus === "queued" ||
    avatarStatus === "notstarted" ||
    avatarStatus === "running";

  if (!combined && !pillars.length && !avatarUrl && !audioUrl && !summaryText) {
    return null;
  }

  return (
    <section className="rounded-[28px] border border-[#e7e1d6] bg-[#fffaf3] px-4 py-5 shadow-[0_30px_80px_-60px_rgba(30,27,22,0.45)] sm:px-5 sm:py-6">
      <div className="space-y-4">
        <div className="flex items-start justify-between gap-3">
          <div>
            <p className="text-xs uppercase tracking-[0.22em] text-[#6b6257]">Latest assessment</p>
            {reportedAt ? <p className="mt-1 text-sm text-[#8c7f70]">{reportedAt}</p> : null}
          </div>
        </div>

        {avatarUrl ? (
          <div className="rounded-2xl border border-[#efe7db] bg-white p-2">
            <video
              controls
              preload="metadata"
              playsInline
              className="w-full rounded-[20px] border border-[#efe7db] bg-[#f6efe5]"
            >
              <source src={avatarUrl} type="video/mp4" />
            </video>
          </div>
        ) : summaryPending ? (
          <div className="rounded-2xl border border-[#efe7db] bg-white px-4 py-4">
            <p className="text-sm text-[#6b6257]">
              We are preparing your latest personalised summary video. Your latest scores are ready below.
            </p>
          </div>
        ) : summaryText ? (
          <div className="rounded-2xl border border-[#efe7db] bg-white px-4 py-4">
            <p className="text-sm leading-6 text-[#3c332b]">{summaryText}</p>
          </div>
        ) : audioUrl ? (
          <div className="rounded-2xl border border-[#efe7db] bg-white px-4 py-4">
            <p className="text-xs uppercase tracking-[0.18em] text-[#6b6257]">Summary audio</p>
            <audio className="mt-3 w-full" controls preload="metadata">
              <source src={audioUrl} type="audio/mpeg" />
            </audio>
          </div>
        ) : avatarError ? (
          <div className="rounded-2xl border border-[#f0d5cb] bg-white px-4 py-4">
            <p className="text-sm text-[#8a3e1a]">{avatarError}</p>
          </div>
        ) : null}

        <div className="rounded-3xl border border-[#efe7db] bg-white px-4 py-5">
          <div className="flex items-center gap-4">
            <LeadAssessmentBranding titleLines={[]} logoClassName="h-10 w-10 flex-none" />
            <div className="min-w-0 flex-1 space-y-2">
              <div className="flex items-end justify-between gap-3">
                <div>
                  <p className="text-xs uppercase tracking-[0.22em] text-[#6b6257]">HealthSense Score</p>
                  <p className="mt-1 text-4xl font-semibold text-[#1e1b16]">{combined}</p>
                </div>
                <p className="text-xs font-semibold uppercase tracking-[0.18em] text-[#8c7f70]">out of 100</p>
              </div>
              <ProgressBar value={combined} max={100} tone="var(--accent)" />
            </div>
          </div>
        </div>

        {pillars.length ? (
          <div className="grid grid-cols-2 gap-3">
            {pillars.map((pillar) => {
              const palette = getPillarPalette(pillar.pillar_key);
              return (
                <div
                  key={pillar.pillar_key}
                  className="rounded-2xl border border-[#efe7db] bg-white px-3 py-4"
                >
                  <div className="flex flex-col items-center text-center">
                    <ScoreRing value={pillar.score} tone={palette.accent} />
                    <p className="mt-3 text-sm font-semibold text-[#1e1b16]">{pillar.label}</p>
                  </div>
                </div>
              );
            })}
          </div>
        ) : null}
      </div>
    </section>
  );
}
