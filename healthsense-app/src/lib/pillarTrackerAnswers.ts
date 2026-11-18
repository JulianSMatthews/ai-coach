import type { PillarTrackerConcept } from "./api";

export const TRACKER_TEXT_MAX_LENGTH = 2000;
export type PillarTrackerDraft = Record<string, number | string>;

export function trackerDraftFromConcepts(concepts: PillarTrackerConcept[]): PillarTrackerDraft {
  const draft: PillarTrackerDraft = {};
  for (const concept of concepts) {
    const key = String(concept.concept_key || "").trim();
    if (!key) continue;
    if (concept.input_type === "text") {
      if (typeof concept.value_text === "string") draft[key] = concept.value_text;
      continue;
    }
    const raw = concept.value;
    if (raw == null || String(raw).trim() === "") continue;
    const value = Number(raw);
    if (Number.isFinite(value)) draft[key] = value;
  }
  return draft;
}

export function isTrackerAnswerComplete(
  concept: PillarTrackerConcept,
  value: number | string | undefined,
): boolean {
  if (!String(concept.concept_key || "").trim()) return false;
  if (concept.input_type === "text") {
    return typeof value === "string" && value.trim().length > 0 && value.length <= TRACKER_TEXT_MAX_LENGTH;
  }
  return typeof value === "number" && Number.isFinite(value)
    && (concept.options || []).some((option) => Number(option.value) === value);
}

export function trackerEntriesFromDraft(concepts: PillarTrackerConcept[], draft: PillarTrackerDraft) {
  return concepts.map((concept) => {
    const key = String(concept.concept_key || "").trim();
    return concept.input_type === "text"
      ? { concept_key: key, text: String(draft[key] ?? "").trim() }
      : { concept_key: key, value: draft[key] };
  });
}
