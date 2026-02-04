export type PillarKey = "nutrition" | "recovery" | "training" | "resilience" | "habit_forming";

export type PillarMeta = {
  key: PillarKey;
  label: string;
  note: string;
  accent: string;
  bg: string;
  border: string;
  icon: string;
};

export const PILLARS: PillarMeta[] = [
  {
    key: "nutrition",
    label: "Nutrition",
    note: "Fuel, hydration, and consistency.",
    accent: "#f59f21",
    bg: "#fff4e6",
    border: "#f3b04a",
    icon: "/icons/pillar-nutrition.svg",
  },
  {
    key: "recovery",
    label: "Recovery",
    note: "Sleep, recovery rituals, and restoration.",
    accent: "#c9764f",
    bg: "#fff1ea",
    border: "#e3a688",
    icon: "/icons/pillar-recovery.svg",
  },
  {
    key: "training",
    label: "Training",
    note: "Strength, mobility, and movement.",
    accent: "#68b32e",
    bg: "#f2fae8",
    border: "#a7d37f",
    icon: "/icons/pillar-training.svg",
  },
  {
    key: "resilience",
    label: "Resilience",
    note: "Stress, mindset, and connection.",
    accent: "#44abc3",
    bg: "#e9f6fa",
    border: "#87cfe0",
    icon: "/icons/pillar-resilience.svg",
  },
  {
    key: "habit_forming",
    label: "Habit forming",
    note: "Routines, cues, and consistency.",
    accent: "#c54817",
    bg: "#fff0e8",
    border: "#efb199",
    icon: "/icons/pillar-habit-forming.svg",
  },
];

const pillarMap = new Map<PillarKey, PillarMeta>(PILLARS.map((pillar) => [pillar.key, pillar]));

const normalizeKey = (key?: string | null) => {
  if (!key) return "";
  return key.toLowerCase().replace(/\s+/g, "_").replace(/-+/g, "_");
};

export const getPillarMeta = (key?: string | null) => {
  const normalized = normalizeKey(key) as PillarKey;
  return pillarMap.get(normalized) || null;
};

export const getPillarPalette = (key?: string | null) => {
  const meta = getPillarMeta(key);
  if (!meta) {
    return {
      label: key || "",
      accent: "#d3541b",
      bg: "#f8fafc",
      border: "#e4e7ec",
      dot: "#98a2b3",
      icon: "",
    };
  }
  return {
    label: meta.label,
    accent: meta.accent,
    bg: meta.bg,
    border: meta.border,
    dot: meta.accent,
    icon: meta.icon,
  };
};
