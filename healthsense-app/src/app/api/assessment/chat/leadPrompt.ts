export const LEAD_Q1_FALLBACK =
  "Which of these areas of your health feels most consistent for you?";

export function buildLeadFirstPrompt(_questionText?: string) {
  return {
    kind: "pillar_reflection",
    section_key: "reflection",
    section_label: "Assessment",
    section_index: 0,
    section_total: 5,
    section_question_index: 0,
    section_question_total: 0,
    question_position: 0,
    question_total: 21,
    question: LEAD_Q1_FALLBACK,
    measure_label: null,
    hint: null,
    options: [
      { value: "nutrition", label: "Nutrition" },
      { value: "training", label: "Training" },
      { value: "recovery", label: "Recovery" },
      { value: "resilience", label: "Resilience" },
    ],
    sections: [],
  };
}
