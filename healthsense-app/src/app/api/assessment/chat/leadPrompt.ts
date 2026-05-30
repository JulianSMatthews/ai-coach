export const LEAD_Q1_FALLBACK = "Get your HealthSense Score and Personal Plan";

export function buildLeadFirstPrompt(_questionText?: string) {
  return {
    kind: "pillar_reflection",
    section_key: "lead_intro",
    section_label: "",
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
      { value: "continue_assessment", label: "Press here to continue" },
    ],
    sections: [],
  };
}
