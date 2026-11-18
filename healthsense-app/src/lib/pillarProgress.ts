import type {
  PillarProgressGuidance,
  PillarProgressConcept,
  PillarProgressPillar,
  PillarProgressStatus,
} from "@/lib/api";

const PILLAR_ORDER = ["reflection", "purpose", "resilience", "recovery", "nutrition", "training"];

const CONCEPT_SHORT_LABELS: Record<string, [string, string?]> = {
  emotional_awareness: ["Awareness", "Aware"],
  mindfulness_presence: ["Presence", "Here"],
  pattern_recognition: ["Learning", "Learn"],
  self_awareness: ["Self", "Self"],
  meaning_fulfilment: ["Meaning", "Meaning"],
  values_alignment: ["Values", "Values"],
  contribution_connection: ["Contribute", "Give"],
  direction_vision: ["Direction", "Aim"],
  emotional_regulation: ["Balance", "Calm"],
  positive_connection: ["Enjoy", "Enjoy"],
  adaptability: ["Adapt", "Adapt"],
  support_connection: ["Support", "Help"],
  stress_recovery: ["Reset", "Reset"],
  optimism_perspective: ["Outlook", "Hope"],
  support_openness: ["Reach out", "Reach"],
  sleep_duration: ["Sleep", "Sleep"],
  sleep_quality: ["Rested", "Rest"],
  bedtime_consistency: ["Bedtime", "Time"],
  heat_exposure: ["Heat", "Heat"],
  cold_exposure: ["Cold", "Cold"],
  magnesium: ["Magnesium", "Mg"],
  protein_intake: ["Protein", "Prot"],
  fruit_veg: ["Fruit & veg", "F&V"],
  hydration: ["Water", "Water"],
  processed_food: ["Processed", "UPF"],
  alcohol_units: ["Alcohol", "Alc"],
  fasting_adherence: ["Fasting", "Fast"],
  omega_3: ["Omega 3", "ω3"],
  vitamin_d: ["Vitamin D", "D"],
  cardio_frequency: ["Cardio", "Cardio"],
  strength_training: ["Strength", "Lift"],
  flexibility_mobility: ["Mobility", "Move"],
  creatine: ["Creatine", "Cr"],
};

export function conceptProgressShortLabel(concept: Pick<PillarProgressConcept, "concept_key" | "label">, dense = false): string {
  const labels = CONCEPT_SHORT_LABELS[concept.concept_key];
  if (labels) return dense ? labels[1] || labels[0] : labels[0];
  if (!dense || concept.label.length <= 5) return concept.label;
  return concept.label.split(/\s+/).map((word) => word[0]).join("").slice(0, 4);
}

export function sortProgressPillars(pillars: PillarProgressPillar[]): PillarProgressPillar[] {
  return [...pillars].sort((left, right) => {
    const rank = (key: string) => {
      const index = PILLAR_ORDER.indexOf(key);
      return index < 0 ? PILLAR_ORDER.length : index;
    };
    return rank(left.pillar_key) - rank(right.pillar_key);
  });
}

export function progressScoreLabel(score: number | null | undefined): string {
  return typeof score === "number" && Number.isFinite(score)
    ? String(Math.round(Math.max(0, Math.min(100, score))))
    : "—";
}

export function progressStatusLabel(status: PillarProgressStatus, score?: number | null): string {
  if (score == null || !Number.isFinite(score) || status === "grey") return "Not scored";
  if (status === "green") return "On track";
  if (status === "amber") return "Building";
  return "Needs attention";
}

export function progressStatusColor(status: PillarProgressStatus, score?: number | null): string {
  if (score == null || !Number.isFinite(score) || status === "grey") return "#858078";
  if (status === "green") return "#4e7a1f";
  if (status === "amber") return "#b57617";
  return "#bb4d43";
}

export function conceptProgressAriaLabel(concept: PillarProgressConcept): string {
  const status = progressStatusLabel(concept.status, concept.score);
  const score = concept.score == null ? "" : `, ${progressScoreLabel(concept.score)} out of 100`;
  return `${concept.label}: ${status}${score}. ${concept.scored_days_count > 0 ? "Get guidance" : "View check-ins"}`;
}

export function progressWeekLabel(start: string, through: string): string {
  const format = (value: string) => {
    const date = new Date(`${value}T12:00:00Z`);
    return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString("en-GB", {
      day: "numeric", month: "short", timeZone: "UTC",
    });
  };
  return start === through ? format(start) : `${format(start)} – ${format(through)}`;
}

export async function requestConceptGuidance(
  selection: {
    userId: string;
    pillarKey: string;
    conceptKey: string;
    weekStart: string;
    through: string;
    signal: AbortSignal;
  },
  fetcher: typeof fetch = fetch,
): Promise<PillarProgressGuidance> {
  const response = await fetcher("/api/pillar-progress/coaching", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      userId: selection.userId,
      pillarKey: selection.pillarKey,
      conceptKey: selection.conceptKey,
    }),
    cache: "no-store",
    signal: selection.signal,
  });
  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    throw new Error(typeof payload?.error === "string" ? payload.error : "Guidance is unavailable. Please try again.");
  }
  if (
    payload?.source !== "ai" ||
    payload.pillar_key !== selection.pillarKey ||
    payload.concept_key !== selection.conceptKey ||
    payload.week_start !== selection.weekStart ||
    payload.through !== selection.through ||
    ![payload.insight, payload.action, payload.reflection].every((value) => typeof value === "string" && value.trim())
  ) {
    throw new Error("Your check-ins may have changed. Go back and refresh your progress before trying again.");
  }
  return payload as PillarProgressGuidance;
}
