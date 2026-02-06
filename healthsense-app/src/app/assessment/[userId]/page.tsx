import type { CSSProperties } from "react";
import { getAssessment, getUserStatus } from "@/lib/api";
import { getPillarPalette } from "@/lib/pillars";
import { Badge, Card, PageShell, ProgressBar, ScoreRing, SectionHeader, StatPill } from "@/components/ui";
import CarouselDots from "@/components/CarouselDots";
import TextScale from "@/components/TextScale";
import AppNav from "@/components/AppNav";

type PageProps = {
  params: Promise<{ userId: string }>;
  searchParams: Promise<{ run_id?: string }>;
};

export default async function AssessmentPage(props: PageProps) {
  const { userId } = await props.params;
  const { run_id } = await props.searchParams;
  const status = await getUserStatus(userId);
  const textScale = status.coaching_preferences?.text_scale
    ? Number.parseFloat(status.coaching_preferences.text_scale)
    : undefined;
  const promptState = (status.prompt_state_override || "").toLowerCase();
  const promptBadge =
    promptState && promptState !== "live"
      ? `${promptState.charAt(0).toUpperCase()}${promptState.slice(1)} mode`
      : "";
  let data: Awaited<ReturnType<typeof getAssessment>> | null = null;
  let missing = false;
  try {
    data = await getAssessment(userId, run_id);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    if (message.includes("404") && message.toLowerCase().includes("assessment run not found")) {
      missing = true;
      data = {};
    } else {
      throw error;
    }
  }
  const safeData = data ?? {};
  const user = safeData.user || {};
  const scores = safeData.scores || {};
  const pillars = safeData.pillars || [];
  const okrs = safeData.okrs || [];
  const narratives = safeData.narratives || {};
  const readiness = safeData.readiness || null;
  const readinessBreakdown = safeData.readiness_breakdown || [];
  const readinessResponses = safeData.readiness_responses || [];
  const reportedAt = safeData.meta?.reported_at;
  const narrativesCached = safeData.meta?.narratives_cached;
  const scoreAudio = narratives.score_audio_url || "";
  const okrAudio = narratives.okr_audio_url || "";
  const coachingAudio = narratives.coaching_audio_url || "";
  const formatDateUk = (value?: string) => {
    if (!value) return "";
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) return value;
    return new Intl.DateTimeFormat("en-GB", {
      dateStyle: "medium",
      timeZone: "Europe/London",
    }).format(parsed);
  };
  const assessmentDate = reportedAt ? formatDateUk(reportedAt) : "";
  const displayName = [user.display_name, user.first_name, user.surname].filter(Boolean).join(" ").trim() || "User";
  const displayNameUpper = displayName.toUpperCase();
  const formatPct = (value: number | null | undefined) => (value === null || value === undefined ? "--" : Math.round(value));
  const readinessPct = (value?: number | null) => {
    if (value === null || value === undefined) return null;
    return Math.round((Number(value) / 5) * 100);
  };
  const formatReadiness = (value?: number | null) => {
    const pct = readinessPct(value);
    return pct === null ? "--" : String(pct);
  };
  const readinessTone = (label?: string) => {
    const key = (label || "").toLowerCase();
    if (key === "high") return "#0ba360";
    if (key === "moderate") return "#f6d365";
    if (key === "low") return "#f76b1c";
    return "var(--accent)";
  };
  const readinessAnswerLabel = (value: number | string | null | undefined) => {
    const num = typeof value === "number" ? value : Number(value);
    const labels: Record<number, string> = {
      1: "Strongly disagree",
      2: "Disagree",
      3: "Unsure",
      4: "Agree",
      5: "Strongly agree",
    };
    if (!Number.isFinite(num) || !labels[num]) return value === undefined || value === null ? "--" : String(value);
    return `${num} · ${labels[num]}`;
  };

  if (missing) {
    return (
      <PageShell>
        <AppNav userId={userId} promptBadge={promptBadge} />
        <SectionHeader
          eyebrow="Assessment"
          title={displayNameUpper}
          subtitle={assessmentDate}
          side={<StatPill label="Combined" value="--" />}
        />
        <Card className="shadow-[0_20px_70px_-50px_rgba(30,27,22,0.35)]">
          <h2 className="text-xl">No assessment run found</h2>
          <p className="mt-2 text-sm text-[#6b6257]">
            There isn’t a completed assessment for this user yet. Ask your coach or admin to start a new assessment
            and check back once it’s finished.
          </p>
        </Card>
      </PageShell>
    );
  }

  return (
    <PageShell>
      <TextScale defaultScale={textScale} />
      <AppNav userId={userId} promptBadge={promptBadge} />
      <SectionHeader
        eyebrow="Assessment"
        title={displayNameUpper}
        subtitle={assessmentDate}
        side={
          <StatPill
            label="Combined"
            value={formatPct(scores.combined)}
            accent="#d3541b"
            bg="#ffe6d1"
            border="#f5d0a0"
          />
        }
      />
      {narrativesCached === false ? (
        <Card className="border border-[#e7e1d6] bg-[#fffaf0] text-sm text-[#6b6257]">
          Reviewing your results and generating a report…
        </Card>
      ) : null}

      <section id="overview" className="grid gap-6 lg:grid-cols-[1.2fr_0.8fr]">
        <Card className="shadow-[0_20px_70px_-50px_rgba(30,27,22,0.35)]">
          <h2 className="text-xl">How you’re doing</h2>
          {scoreAudio ? (
            <div className="mt-4">
              <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Listen</p>
              <audio controls className="mt-2 w-full">
                <source src={scoreAudio} />
              </audio>
            </div>
          ) : null}
          <div className="mt-4 hidden space-y-3 text-sm text-[#3c332b] md:block" dangerouslySetInnerHTML={{ __html: narratives.score_html || "<p>No narrative available.</p>" }} />
          <details className="mt-4 text-sm text-[#3c332b] md:hidden">
            <summary className="cursor-pointer text-xs uppercase tracking-[0.2em] text-[var(--accent)]">
              Read
            </summary>
            <div className="mt-3 space-y-3" dangerouslySetInnerHTML={{ __html: narratives.score_html || "<p>No narrative available.</p>" }} />
          </details>
        </Card>
      </section>

      <section id="scores" className="grid gap-6 lg:grid-cols-[1fr_1fr]">
        <Card>
          <h2 className="text-xl">Score breakdown</h2>
          <div className="mt-4 space-y-4 text-sm">
            {(scores.rows || []).length ? (
              (scores.rows || []).map((row) => {
                const palette = getPillarPalette(row.label);
                return (
                  <div key={row.label} className="rounded-2xl border border-[#efe7db] bg-[#fffaf0] px-4 py-3">
                    <div className="flex items-center justify-between gap-3">
                      <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">{row.label}</p>
                      <p className="text-sm font-semibold text-[#1e1b16]">{formatPct(row.value)}%</p>
                    </div>
                    <ProgressBar value={Number(row.value ?? 0)} tone={palette.accent} />
                  </div>
                );
              })
            ) : (
              <p className="text-sm text-[#6b6257]">No score breakdown yet.</p>
            )}
          </div>
        </Card>
      </section>

      <section id="okrs" className="grid gap-6 lg:grid-cols-[1fr_1fr]">
        <Card>
          <h2 className="text-xl">Your OKR focus</h2>
          {okrAudio ? (
            <div className="mt-4">
              <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Listen</p>
              <audio controls className="mt-2 w-full">
                <source src={okrAudio} />
              </audio>
            </div>
          ) : null}
          <div className="mt-4 hidden space-y-3 text-sm text-[#3c332b] md:block" dangerouslySetInnerHTML={{ __html: narratives.okr_html || "<p>No OKR narrative available.</p>" }} />
          <details className="mt-4 text-sm text-[#3c332b] md:hidden">
            <summary className="cursor-pointer text-xs uppercase tracking-[0.2em] text-[var(--accent)]">
              Read
            </summary>
            <div className="mt-3 space-y-3" dangerouslySetInnerHTML={{ __html: narratives.okr_html || "<p>No OKR narrative available.</p>" }} />
          </details>
        </Card>
        <Card>
          <h2 className="text-xl">Habit readiness</h2>
          {coachingAudio ? (
            <div className="mt-4">
              <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Listen</p>
              <audio controls className="mt-2 w-full">
                <source src={coachingAudio} />
              </audio>
            </div>
          ) : null}
          <div className="mt-4 hidden space-y-3 text-sm text-[#3c332b] md:block" dangerouslySetInnerHTML={{ __html: narratives.coaching_html || "<p>No habit readiness notes yet.</p>" }} />
          <details className="mt-4 text-sm text-[#3c332b] md:hidden">
            <summary className="cursor-pointer text-xs uppercase tracking-[0.2em] text-[var(--accent)]">
              Read
            </summary>
            <div className="mt-3 space-y-3" dangerouslySetInnerHTML={{ __html: narratives.coaching_html || "<p>No habit readiness notes yet.</p>" }} />
          </details>
        </Card>
      </section>

      <section
        id="pillars"
        className="flex flex-nowrap gap-6 overflow-x-auto pb-2 snap-x snap-mandatory scroll-smooth"
        style={{ scrollSnapType: "x mandatory" }}
      >
        {pillars.map((pillar: any) => {
          const okr = okrs.find((o: any) => o.pillar_key === pillar.pillar_key);
          const conceptScores = pillar.concept_scores || {};
          const conceptLabels = pillar.concept_labels || {};
          const palette = getPillarPalette(pillar.pillar_key || pillar.pillar_name);
          const cardStyle = {
            borderColor: palette.border,
            background: palette.bg,
            "--accent": palette.accent,
          } as CSSProperties;
          const conceptEntries = Object.keys(conceptScores).map((key) => ({
            key,
            label: conceptLabels[key] || key,
            value: conceptScores[key],
          }));
          return (
            <Card
              key={pillar.pillar_key}
              className="min-w-full snap-start sm:min-w-[85%]"
              data-carousel-item
              style={{
                scrollSnapStop: "always",
                ...cardStyle,
              }}
            >
              <div className="flex items-start justify-between gap-4">
                <div>
                  <h3 className="text-lg">{pillar.pillar_name}</h3>
                  <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Score</p>
                </div>
                <ScoreRing value={Number(pillar.score ?? 0)} tone={palette.accent} />
              </div>
              <ProgressBar value={Number(pillar.score ?? 0)} tone={palette.accent} />
              {conceptEntries.length ? (
                <div className="mt-4 space-y-3">
                  {conceptEntries.map((concept) => (
                    <div key={concept.key} className="rounded-2xl border border-[#efe7db] bg-[#fffaf0] px-4 py-3 text-sm">
                      <div className="flex items-center justify-between gap-3">
                        <p className="text-xs uppercase tracking-[0.18em] text-[#6b6257]">{concept.label}</p>
                        <p className="text-sm font-semibold text-[#1e1b16]">{formatPct(concept.value)}%</p>
                      </div>
                      <ProgressBar value={Number(concept.value ?? 0)} tone={palette.accent} />
                    </div>
                  ))}
                </div>
              ) : null}
              <div className="mt-4 text-sm text-[#3c332b]">
                <p className="font-semibold text-[#1e1b16]">Objective</p>
                <p>{okr?.objective || "No objective yet."}</p>
              </div>
              <div className="mt-3 text-sm">
                <p className="font-semibold text-[#1e1b16]">Key results</p>
                <ul className="mt-2 list-disc space-y-1 pl-5 text-[#3c332b]">
                  {(okr?.key_results || []).map((kr: string) => (
                    <li key={kr}>{kr}</li>
                  ))}
                </ul>
              </div>
              {(pillar.qa_samples || []).length ? (
                <details className="mt-4 rounded-2xl border border-[#efe7db] bg-white p-4">
                  <summary className="cursor-pointer text-xs uppercase tracking-[0.2em] text-[var(--accent)]">
                    Review your responses
                  </summary>
                  <div className="mt-3 space-y-3 text-sm text-[#3c332b]">
                    {(pillar.qa_samples || []).map((qa: any, idx: number) => (
                      <div key={`${qa.question}-${idx}`} className="rounded-2xl border border-[#efe7db] bg-[#fffaf0] p-3">
                        <div className="rounded-xl border border-[#efe7db] bg-white p-3">
                          <p className="text-xs uppercase tracking-[0.18em] text-[#6b6257]">Question</p>
                          <p className="mt-1 text-sm text-[#1e1b16]">{qa.question}</p>
                        </div>
                        <div className="mt-2 rounded-xl border border-[#efe7db] bg-white p-3">
                          <p className="text-xs uppercase tracking-[0.18em] text-[#6b6257]">Answer</p>
                          <p className="mt-1 text-sm text-[#1e1b16]">{qa.answer}</p>
                        </div>
                      </div>
                    ))}
                  </div>
                </details>
              ) : null}
            </Card>
          );
        })}
        <Card
          className="min-w-full snap-start sm:min-w-[85%]"
          data-carousel-item
          style={{ scrollSnapStop: "always" }}
        >
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div>
              <h3 className="text-lg">Habit readiness</h3>
              <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Profile</p>
            </div>
            {readiness ? (
              <ScoreRing
                value={readinessPct(readiness.score ?? 0) ?? 0}
                max={100}
                tone={readinessTone(readiness.label)}
              />
            ) : null}
          </div>
          {readiness ? (
            <>
              <p className="mt-3 text-2xl font-semibold">
                {formatReadiness(readiness.score)}% · {readiness.label}
              </p>
              <p className="mt-2 text-sm text-[#3c332b]">{readiness.note}</p>
            </>
          ) : (
            <p className="mt-4 text-sm text-[#6b6257]">No habit readiness profile yet.</p>
          )}
          {readinessBreakdown.length ? (
            <div className="mt-4 space-y-3 text-sm">
              {readinessBreakdown.map((row: any) => (
                <div key={row.key || row.label} className="rounded-2xl border border-[#efe7db] bg-[#fffaf0] px-4 py-3">
                  <div className="flex items-center justify-between gap-3">
                    <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">{row.label}</p>
                    <p className="text-sm font-semibold text-[#1e1b16]">{formatReadiness(row.value)}%</p>
                  </div>
                  <ProgressBar value={readinessPct(row.value ?? 0) ?? 0} max={100} tone={readinessTone(readiness?.label)} />
                </div>
              ))}
            </div>
          ) : null}
          {readinessResponses.length ? (
            <details className="mt-4 rounded-2xl border border-[#efe7db] bg-white p-4">
              <summary className="cursor-pointer text-xs uppercase tracking-[0.2em] text-[var(--accent)]">
                Review your responses
              </summary>
              <div className="mt-3 space-y-3 text-sm text-[#3c332b]">
                {readinessResponses.map((qa: any, idx: number) => (
                  <div key={`${qa.key || qa.question}-${idx}`} className="rounded-2xl border border-[#efe7db] bg-[#fffaf0] p-3">
                    <div className="rounded-xl border border-[#efe7db] bg-white p-3">
                      <p className="text-xs uppercase tracking-[0.18em] text-[#6b6257]">Question</p>
                      <p className="mt-1 text-sm text-[#1e1b16]">{qa.question}</p>
                    </div>
                    <div className="mt-2 rounded-xl border border-[#efe7db] bg-white p-3">
                      <p className="text-xs uppercase tracking-[0.18em] text-[#6b6257]">Answer</p>
                      <p className="mt-1 text-sm text-[#1e1b16]">{readinessAnswerLabel(qa.answer)}</p>
                    </div>
                  </div>
                ))}
              </div>
            </details>
          ) : null}
        </Card>
      </section>
      {pillars.length ? <CarouselDots containerId="pillars" count={pillars.length + 1} /> : null}

    </PageShell>
  );
}
