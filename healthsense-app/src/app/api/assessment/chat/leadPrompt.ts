const NUMBER_WORDS: Record<number, string> = {
  0: "Zero",
  1: "One",
  2: "Two",
  3: "Three",
  4: "Four",
  5: "Five",
};

export const LEAD_Q1_FALLBACK =
  "Q1/15 · Nutrition: In the last 7 days, how many portions of fruit and vegetables did you *eat on average per day*? For reference: 1 portion = 1 apple or banana, 1 fist-sized serving of vegetables, or 1 handful of salad or berries.";

export function buildLeadFirstPrompt(questionText?: string) {
  return {
    kind: "concept_scale",
    section_key: "nutrition",
    section_label: "Nutrition",
    section_index: 1,
    section_total: 5,
    section_question_index: 1,
    section_question_total: 4,
    question_position: 1,
    question_total: 21,
    concept_code: "fruit_veg",
    concept_label: "Fruit & vegetables",
    question: String(questionText || LEAD_Q1_FALLBACK)
      .replace(/^Q\d+\/\d+\s*·\s*Nutrition:\s*/i, "")
      .trim(),
    measure_label: "portions/day",
    hint: "Tap the number that best fits your last 7 days.",
    options: Array.from({ length: 6 }, (_, idx) => ({
      value: String(idx),
      label: NUMBER_WORDS[idx] || String(idx),
    })),
    sections: [
      { key: "nutrition", label: "Nutrition", index: 1, value: 1, answered: 0, total: 4, status: "active" },
      { key: "training", label: "Training", index: 2, value: 0, answered: 0, total: 3, status: "upcoming" },
      { key: "resilience", label: "Resilience", index: 3, value: 0, answered: 0, total: 5, status: "upcoming" },
      { key: "recovery", label: "Recovery", index: 4, value: 0, answered: 0, total: 3, status: "upcoming" },
      { key: "habit_readiness", label: "Habit readiness", index: 5, value: 0, answered: 0, total: 6, status: "upcoming" },
    ],
  };
}
