"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type ChangeEvent } from "react";
import type {
  AppleHealthRestingHeartRateResponse,
  BiometricMetricKey,
  BiometricSourceSummary,
  // Keep tracker responses local to this panel.
  PillarTrackerDetailResponse,
  PillarTrackerPillar,
  PillarTrackerSummaryResponse,
  UrineTestMarker,
  UrineTestResponse,
  WeeklyObjectiveConcept,
  WeeklyObjectivePillarConfig,
  WeeklyObjectiveWellbeingItem,
  WeeklyObjectivesResponse,
} from "@/lib/api";
import {
  canUseAppleHealth,
  getAppleHealthAuthorizationStatus,
  requestAppleHealthAuthorization,
  syncAppleHealthRestingHeartRate,
  type AppleHealthAuthorizationState,
} from "@/lib/appleHealth";
import { dispatchPillarTrackerOverallScore } from "@/lib/pillarTrackerSummary";
import { readStoredThemePreference } from "@/lib/theme";
import { getPillarMeta, getPillarPalette } from "@/lib/pillars";
import { ScoreRing } from "@/components/ui";

type LatestAssessmentPanelProps = {
  userId: string;
  initialSummary: PillarTrackerSummaryResponse;
  initialAssessmentReviewed?: boolean;
  initialInteractionDaysCount?: number | null;
  isAdminUser?: boolean;
};

type TrackerReturnSurface = "tracking" | "habits" | "insight" | "ask";
type MorningSequenceState = "idle" | "in_progress" | "completed";
type DisplayTheme = "light" | "dark";
type ObjectivesSectionKey = "reflection" | "purpose" | "nutrition" | "training" | "resilience" | "recovery" | "wellbeing";
type UrineCaptureState = "ready" | "timing" | "saving" | "queued" | "analysed" | "review" | "error";
type BiomarkerExplanationKey = "training_readiness" | "rhr" | "hrv" | "activity_status" | "active_minutes" | "steps" | "urine";
type BiomarkerExplanationTone = "purple" | "green" | "amber" | "red" | "neutral";
type TrainingReadinessStatus = "ready" | "moderate" | "low" | "unknown";
type ActivityStatus = "high" | "moderate" | "low" | "unknown";
type ActivityAlignmentStatus = "aligned" | "above_readiness" | "below_readiness" | "unknown";
type BiomarkerExplanationScaleRow = {
  marker: string;
  status: string;
  meaning: string;
  dotClassName?: string;
  tone?: BiomarkerExplanationTone;
};
type StreakCalendarDay = {
  key: string;
  iso: string;
  dayNumber: number;
  inMonth: boolean;
  isToday: boolean;
  isFuture: boolean;
};

const PILLAR_ORDER = ["reflection", "purpose", "resilience", "recovery", "nutrition", "training"];
const DEFAULT_SETUP_PILLARS = ["reflection", "purpose", "resilience", "recovery"];
const SETUP_SELECTABLE_PILLAR_ORDER = ["reflection", "purpose", "resilience", "recovery"];
const PILLAR_PREF_KEYS: Record<string, string> = {
  reflection: "home_pillar_reflection",
  purpose: "home_pillar_purpose",
  resilience: "home_pillar_resilience",
  recovery: "home_pillar_recovery",
  nutrition: "home_pillar_nutrition",
  training: "home_pillar_training",
};
const PILLAR_SETUP_COPY: Record<string, string> = {
  reflection: "Understand what you are noticing, feeling, and learning from the patterns in your day.",
  purpose: "Stay close to meaning, direction, values, and the choices that make the day feel worthwhile.",
  resilience: "Work with pressure, emotional steadiness, support, and the way you recover your perspective.",
  recovery: "Build awareness around sleep, rest, rhythm, and the conditions that help your body reset.",
  nutrition: "Track the food and hydration signals that shape energy, appetite, and consistency.",
  training: "Use movement, strength, cardio, and mobility as part of a balanced weekly rhythm.",
};
const SETUP_GUIDE_CARDS = [
  {
    icon: "checkin",
    title: "Check in",
    body: "Each selected pillar becomes a daily cue card. Tap Today, Yesterday, or Last week to answer the pillar questions.",
  },
  {
    icon: "targets",
    title: "Weekly targets",
    body: "Targets set the weekly context for each question. They can stay simple at first and be adjusted as your routine becomes clearer.",
  },
  {
    icon: "scoring",
    title: "Scoring",
    body: "Scores are feedback signals, not grades. They help CoachSense notice patterns and generate more relevant reflections.",
  },
  {
    icon: "lessons",
    title: "Lessons",
    body: "Your learning journey moves through concept units. The units follow the pillars and questions you choose here.",
  },
];
const MORNING_SEQUENCE_STORAGE_PREFIX = "hs:morning-sequence-complete";
const URINE_CAPTURE_TIMER_SECONDS = 60;
const URINE_RECENT_CAPTURE_WINDOW_MS = 5 * 60 * 1000;
const URINE_TEST_MAX_PHOTO_BYTES = 8 * 1024 * 1024;
const BIOMETRICS_ENABLED = ["1", "true", "yes", "on"].includes(
  String(process.env.NEXT_PUBLIC_BIOMETRICS_ENABLED || "").trim().toLowerCase(),
);
const DEFAULT_WEEKLY_TARGET_DAYS = 5;
const BIOMETRIC_SOURCE_ORDER: Array<{ key: BiometricMetricKey; label: string }> = [
  { key: "resting_hr", label: "Resting HR" },
  { key: "hrv", label: "HRV" },
  { key: "steps", label: "Steps" },
  { key: "exercise_minutes", label: "Exercise minutes" },
];
const BIOMETRIC_CONNECT_OPTIONS = [
  { provider: "oura", label: "Oura", connectable: true },
  { provider: "whoop", label: "WHOOP", connectable: true },
  { provider: "fitbit", label: "Fitbit", connectable: true },
  { provider: "garmin", label: "Garmin", connectable: false },
];
const HOME_PILLAR_QUOTE_FALLBACKS: Record<string, string> = {
  reflection: "Notice one honest signal today and let it guide your next choice.",
  purpose: "Purpose becomes clearer when today reflects what matters, not just what needs doing.",
  resilience: "Pause early, respond deliberately, and protect your calm under pressure.",
  recovery: "Give your body enough space to reset before asking for more.",
  nutrition: "Make the next meal simple, steady, and supportive of your energy.",
  training: "Move with intent today; consistency is the part that compounds.",
};
const HOME_PILLAR_FALLBACK_QUOTES = new Set(
  Object.values(HOME_PILLAR_QUOTE_FALLBACKS).map((item) => item.trim().toLowerCase()),
);
const URINE_SCREENING_MARKERS = [
  { key: "concentration", label: "Hydration" },
  { key: "uti", label: "UTI Signs" },
  { key: "protein", label: "Protein" },
  { key: "blood", label: "Blood" },
  { key: "glucose", label: "Glucose" },
  { key: "ketones", label: "Ketones" },
] as const;

function resolveRestingHeartRateBoxTone(theme: DisplayTheme): string {
  return theme === "dark"
    ? "border-[var(--border)] bg-[var(--surface)] text-[var(--text-primary)]"
    : "border-[#e7e1d6] bg-[var(--surface)] text-[var(--text-secondary)]";
}

function resolveRestingHeartRateMetricTone(
  theme: DisplayTheme,
  status?: string | null,
): string {
  if (status === "optimum") {
    return theme === "dark" ? "text-[#c7b0ff]" : "text-[#6b4cc2]";
  }
  if (status === "elevated") {
    return theme === "dark" ? "text-[#ffd3ad]" : "text-[#b55d1c]";
  }
  return theme === "dark" ? "text-[#d9f0c5]" : "text-[#3f7a2a]";
}

function resolveRestingHeartRateValue(value?: number | null): string | null {
  const resolved = Number(value);
  if (!Number.isFinite(resolved) || resolved <= 0) return null;
  return String(Math.round(resolved));
}

function resolveHeartRateVariabilityValue(value?: number | null): string | null {
  const resolved = Number(value);
  if (!Number.isFinite(resolved) || resolved <= 0) return null;
  return String(Math.round(resolved));
}

function resolveRestingHeartRateTrendLabel(label?: string | null): string {
  const resolved = String(label || "").trim();
  if (!resolved) return "normal";
  return resolved.toLowerCase();
}

function resolveRestingHeartRateCompactTrendLabel(label?: string | null): string {
  const resolved = resolveRestingHeartRateTrendLabel(label);
  if (resolved === "optimal") return "opt";
  if (resolved === "elevated") return "elev";
  if (resolved === "suppressed") return "supp";
  return "norm";
}

function formatBiometricDayLabel(value?: string | null): string {
  const token = String(value || "").trim();
  if (!token) return "—";
  const parsed = new Date(`${token}T12:00:00`);
  if (Number.isNaN(parsed.getTime())) return token;
  return parsed.toLocaleDateString("en-GB", { weekday: "short" });
}

function formatBiometricDayNumber(value?: string | null): string {
  const token = String(value || "").trim();
  if (!token) return "—";
  const parsed = new Date(`${token}T12:00:00`);
  if (Number.isNaN(parsed.getTime())) return token;
  return parsed.toLocaleDateString("en-GB", { day: "numeric" });
}

function formatJournalDate(value?: string | null): string {
  const token = String(value || "").trim();
  if (!token) return "";
  const parsed = new Date(`${token}T12:00:00`);
  if (Number.isNaN(parsed.getTime())) return token;
  return parsed.toLocaleDateString("en-GB", {
    weekday: "short",
    day: "numeric",
    month: "short",
  });
}

function initialSetupPillarSelections(summary?: PillarTrackerSummaryResponse | null, includeAllPillars = false): Record<string, boolean> {
  const activeKeys = new Set(
    (Array.isArray(summary?.pillars) ? summary?.pillars : [])
      .map((pillar) => String(pillar?.pillar_key || "").trim().toLowerCase())
      .filter(Boolean),
  );
  const selectablePillars = includeAllPillars ? PILLAR_ORDER : SETUP_SELECTABLE_PILLAR_ORDER;
  const source = activeKeys.size ? activeKeys : new Set(includeAllPillars ? PILLAR_ORDER : DEFAULT_SETUP_PILLARS);
  return Object.fromEntries(
    PILLAR_ORDER.map((pillarKey) => [
      pillarKey,
      selectablePillars.includes(pillarKey) && source.has(pillarKey),
    ]),
  );
}

function resolveWeeklyObjectiveDraftValue(concept?: WeeklyObjectiveConcept | null): number | null {
  const selectedValue = Number(concept?.selected_value);
  if (Number.isFinite(selectedValue) && selectedValue > 0) return selectedValue;
  const defaultOption = (concept?.options || []).find((option) => Number(option?.value) === DEFAULT_WEEKLY_TARGET_DAYS);
  return defaultOption ? DEFAULT_WEEKLY_TARGET_DAYS : null;
}

function buildDefaultWeeklyObjectiveTargets(
  pillar?: WeeklyObjectivePillarConfig | null,
): Record<string, number | null> {
  const targets: Record<string, number | null> = {};
  (pillar?.concepts || []).forEach((concept) => {
    const conceptKey = String(concept?.concept_key || "").trim();
    if (!conceptKey) return;
    targets[conceptKey] = resolveWeeklyObjectiveDraftValue(concept);
  });
  return targets;
}

function formatCompactStepCount(value?: number | null): string {
  const resolved = Number(value);
  if (!Number.isFinite(resolved) || resolved < 0) return "—";
  const thousands = resolved / 1000;
  const decimals = thousands >= 100 ? 0 : 1;
  return thousands.toFixed(decimals).replace(/\.0$/, "");
}

type StepsStatus = "base" | "strong" | "optimal" | null;

function resolveStepsStatus(value?: number | null): StepsStatus {
  const resolved = Number(value);
  if (!Number.isFinite(resolved) || resolved < 5000) return null;
  if (resolved >= 10000) return "optimal";
  if (resolved >= 7500) return "strong";
  return "base";
}

function resolveStepsMetricTone(theme: DisplayTheme, status: StepsStatus): string {
  if (status === "optimal") {
    return theme === "dark" ? "text-[#c7b0ff]" : "text-[#6b4cc2]";
  }
  if (status === "strong") {
    return theme === "dark" ? "text-[#d9f0c5]" : "text-[#3f7a2a]";
  }
  if (status === "base") {
    return theme === "dark" ? "text-[#ffd3ad]" : "text-[#b55d1c]";
  }
  return theme === "dark" ? "text-[var(--text-primary)]" : "text-[var(--text-secondary)]";
}

function resolveCompactStepsStatusLabel(status: StepsStatus): string {
  if (status === "optimal") return "opt";
  if (status === "strong") return "str";
  if (status === "base") return "base";
  return "";
}

function resolveStepsStatusDescription(status: StepsStatus): string {
  if (status === "optimal") return "optimal";
  if (status === "strong") return "strong";
  if (status === "base") return "base";
  return "below base";
}

function formatFullStepCount(value?: number | null): string | null {
  const resolved = Number(value);
  if (!Number.isFinite(resolved) || resolved < 0) return null;
  return Math.round(resolved).toLocaleString("en-GB");
}

function formatActiveMinutes(value?: number | null): string {
  const resolved = Number(value);
  if (!Number.isFinite(resolved) || resolved < 0) return "—";
  return String(Math.round(resolved));
}

function resolveActiveMinutesStatus(value?: number | null): StepsStatus {
  const resolved = Number(value);
  if (!Number.isFinite(resolved) || resolved < 10) return null;
  if (resolved >= 30) return "optimal";
  if (resolved >= 20) return "strong";
  return "base";
}

function resolveActiveMinutesStatusDescription(status: StepsStatus): string {
  if (status === "optimal") return "optimal";
  if (status === "strong") return "strong";
  if (status === "base") return "base";
  return "below base";
}

function formatFullActiveMinutes(value?: number | null): string | null {
  const resolved = Number(value);
  if (!Number.isFinite(resolved) || resolved < 0) return null;
  return Math.round(resolved).toLocaleString("en-GB");
}

function normalizeBiometricSourceRows(
  sources?: Partial<Record<BiometricMetricKey, BiometricSourceSummary>> | null,
): Array<{ key: BiometricMetricKey; label: string; source: BiometricSourceSummary }> {
  return BIOMETRIC_SOURCE_ORDER.map((item) => ({
    ...item,
    source: (sources?.[item.key] || {
      metric: item.key,
      label: item.label,
      enabled: true,
      has_data: false,
      confidence: "unknown",
      connection_options: BIOMETRIC_CONNECT_OPTIONS,
    }) as BiometricSourceSummary,
  }));
}

function resolveBiometricSourceTone(theme: DisplayTheme, source?: BiometricSourceSummary | null): string {
  if (source?.enabled === false) {
    return theme === "dark"
      ? "border-[var(--border)] bg-[var(--surface-muted)] text-[var(--text-secondary)]"
      : "border-[#e7e1d6] bg-[#f7f1e8] text-[var(--text-secondary)]";
  }
  const confidence = String(source?.confidence || "").trim().toLowerCase();
  if (confidence === "high") {
    return theme === "dark"
      ? "border-[#6f9f52] bg-[#182417] text-[#d9f0c5]"
      : "border-[#cfe5c4] bg-[#f4fbf0] text-[#3f7a2a]";
  }
  if (confidence === "medium") {
    return theme === "dark"
      ? "border-[#b98138] bg-[#2b2114] text-[#ffd3ad]"
      : "border-[#f0d4ad] bg-[#fff8ef] text-[#9b5b18]";
  }
  if (confidence === "low") {
    return theme === "dark"
      ? "border-[#b98138] bg-[#2b2114] text-[#ffd3ad]"
      : "border-[#f0d4ad] bg-[#fff8ef] text-[#9b5b18]";
  }
  return theme === "dark"
    ? "border-[var(--border)] bg-[var(--surface)] text-[var(--text-primary)]"
    : "border-[#e7e1d6] bg-[var(--surface)] text-[var(--text-secondary)]";
}

function shouldShowBiometricConnectionOptions(source?: BiometricSourceSummary | null): boolean {
  if (!source || source.enabled === false) return false;
  const confidence = String(source.confidence || "").trim().toLowerCase();
  return source.has_data === false || confidence === "low" || confidence === "unknown" || !confidence;
}

function formatBiometricSourceLabel(source?: BiometricSourceSummary | null): string {
  const label = String(source?.source_label || "").trim();
  if (label) return label;
  const device = String(source?.device_label || "").trim();
  if (device) return device;
  return "No source detected";
}

function resolveTrainingReadinessStatus(
  hrvStatus?: string | null,
  restingHeartRateStatus?: string | null,
): TrainingReadinessStatus {
  const resolvedHrvStatus = String(hrvStatus || "").trim().toLowerCase();
  const resolvedRestingHeartRateStatus = String(restingHeartRateStatus || "").trim().toLowerCase();
  const hrvAvailable = ["optimum", "normal", "elevated"].includes(resolvedHrvStatus);
  const restingHeartRateAvailable = ["optimum", "normal", "elevated"].includes(resolvedRestingHeartRateStatus);
  if (!hrvAvailable && !restingHeartRateAvailable) {
    return "unknown";
  }
  if (!hrvAvailable) {
    if (resolvedRestingHeartRateStatus === "optimum") return "ready";
    if (resolvedRestingHeartRateStatus === "elevated") return "low";
    return "moderate";
  }
  if (!restingHeartRateAvailable) {
    if (resolvedHrvStatus === "optimum") return "ready";
    if (resolvedHrvStatus === "elevated") return "low";
    return "moderate";
  }
  const hrvAboveNormal = resolvedHrvStatus === "optimum";
  const hrvDown = resolvedHrvStatus === "elevated";
  const restingHeartRateAtOrBelowNormal =
    resolvedRestingHeartRateStatus === "optimum" || resolvedRestingHeartRateStatus === "normal";
  const restingHeartRateElevated = resolvedRestingHeartRateStatus === "elevated";
  if (hrvAboveNormal && restingHeartRateAtOrBelowNormal) return "ready";
  if (hrvDown && restingHeartRateElevated) return "low";
  return "moderate";
}

function resolveTrainingReadinessLabel(status: TrainingReadinessStatus): string {
  if (status === "ready") return "Ready";
  if (status === "low") return "Low";
  if (status === "unknown") return "No data";
  return "Moderate";
}

function resolveTrainingReadinessAction(status: TrainingReadinessStatus): string {
  if (status === "ready") return "Push intensity";
  if (status === "low") return "Recover / avoid intensity";
  if (status === "unknown") return "Sync HRV and Resting HR";
  return "Train, but control intensity";
}

function normalizeTrainingReadinessStatus(value?: string | null): TrainingReadinessStatus {
  const resolved = String(value || "").trim().toLowerCase();
  if (resolved === "ready" || resolved === "moderate" || resolved === "low") return resolved;
  return "unknown";
}

function normalizeActivityStatus(value?: string | null): ActivityStatus {
  const resolved = String(value || "").trim().toLowerCase();
  if (resolved === "high" || resolved === "moderate" || resolved === "low") return resolved;
  return "unknown";
}

function normalizeActivityAlignmentStatus(value?: string | null): ActivityAlignmentStatus {
  const resolved = String(value || "").trim().toLowerCase();
  if (resolved === "aligned" || resolved === "above_readiness" || resolved === "below_readiness") return resolved;
  return "unknown";
}

function resolveActivityStatus(value?: { steps?: number | null; active_minutes?: number | null } | null): ActivityStatus {
  const steps = Number(value?.steps);
  const activeMinutes = Number(value?.active_minutes);
  const hasSteps = Number.isFinite(steps) && steps >= 0;
  const hasActiveMinutes = Number.isFinite(activeMinutes) && activeMinutes >= 0;
  if (!hasSteps && !hasActiveMinutes) return "unknown";
  if ((hasActiveMinutes && activeMinutes >= 30) || (hasSteps && steps >= 10000)) return "high";
  if ((hasActiveMinutes && activeMinutes >= 20) || (hasSteps && steps >= 7500)) return "moderate";
  return "low";
}

function resolveActivityStatusLabel(status: ActivityStatus): string {
  if (status === "high") return "High";
  if (status === "moderate") return "Moderate";
  if (status === "low") return "Low";
  return "No data";
}

function resolveActivityAlignmentLabel(status: ActivityAlignmentStatus): string {
  if (status === "aligned") return "Aligned";
  if (status === "above_readiness") return "Activity above readiness";
  if (status === "below_readiness") return "Activity below readiness";
  return "No alignment yet";
}

function resolveReadinessLevel(status: TrainingReadinessStatus): number | null {
  if (status === "ready") return 3;
  if (status === "moderate") return 2;
  if (status === "low") return 1;
  return null;
}

function resolveActivityLevel(status: ActivityStatus): number | null {
  if (status === "high") return 3;
  if (status === "moderate") return 2;
  if (status === "low") return 1;
  return null;
}

function resolveActivityAlignmentStatusFromLevels(
  readinessStatus: TrainingReadinessStatus,
  status: ActivityStatus,
): ActivityAlignmentStatus {
  const readinessLevel = resolveReadinessLevel(readinessStatus);
  const activityLevel = resolveActivityLevel(status);
  if (readinessLevel === null || activityLevel === null) return "unknown";
  if (activityLevel === readinessLevel) return "aligned";
  return activityLevel > readinessLevel ? "above_readiness" : "below_readiness";
}

function resolveTrainingReadinessCircleTone(theme: DisplayTheme, status?: string | null): string {
  const resolved = normalizeTrainingReadinessStatus(status);
  if (resolved === "ready") {
    return theme === "dark" ? "border-[#405b35] bg-[#1f2b1d] text-[#d9f0c5]" : "border-[#cfe7ba] bg-[#f2fae8] text-[#335f16]";
  }
  if (resolved === "low") {
    return theme === "dark" ? "border-[#4f3f84] bg-[#211a35] text-[#d8c9ff]" : "border-[#ded4ff] bg-[#f5f0ff] text-[#5a3da7]";
  }
  if (resolved === "moderate") {
    return theme === "dark" ? "border-[#6b5133] bg-[#2e241a] text-[#ffd3ad]" : "border-[#f2dccb] bg-[#fff4ea] text-[#8a5a1a]";
  }
  return theme === "dark" ? "border-[var(--border)] bg-[var(--surface)] text-[var(--text-secondary)]" : "border-[#ece5d9] bg-[var(--surface)] text-[var(--text-tertiary)]";
}

function resolveActivityCircleTone(theme: DisplayTheme, status?: string | null): string {
  const resolved = normalizeActivityStatus(status);
  if (resolved === "high") {
    return theme === "dark" ? "border-[#4f3f84] bg-[#211a35] text-[#d8c9ff]" : "border-[#ded4ff] bg-[#f5f0ff] text-[#5a3da7]";
  }
  if (resolved === "moderate") {
    return theme === "dark" ? "border-[#405b35] bg-[#1f2b1d] text-[#d9f0c5]" : "border-[#cfe7ba] bg-[#f2fae8] text-[#335f16]";
  }
  if (resolved === "low") {
    return theme === "dark" ? "border-[#6b5133] bg-[#2e241a] text-[#ffd3ad]" : "border-[#f2dccb] bg-[#fff4ea] text-[#8a5a1a]";
  }
  return theme === "dark" ? "border-[var(--border)] bg-[var(--surface)] text-[var(--text-secondary)]" : "border-[#ece5d9] bg-[var(--surface)] text-[var(--text-tertiary)]";
}

function resolveStatusShortLabel(value?: string | null): string {
  const resolved = String(value || "").trim().toLowerCase();
  if (resolved === "ready") return "ready";
  if (resolved === "high") return "high";
  if (resolved === "moderate") return "mod";
  if (resolved === "low") return "low";
  return "—";
}

function resolveUrineCaptureTone(theme: DisplayTheme, state: UrineCaptureState): string {
  if (state === "analysed") {
    return theme === "dark"
      ? "border-[#405b35] bg-[#1f2b1d] text-[#d9f0c5]"
      : "border-[#d5e8bf] bg-[#f2fae8] text-[#335f16]";
  }
  if (state === "error") {
    return theme === "dark"
      ? "border-[#674033] bg-[#2c1d1a] text-[#ffb7a1]"
      : "border-[#efc4b6] bg-[#fff0eb] text-[#9b3218]";
  }
  if (state === "queued" || state === "timing" || state === "saving" || state === "review") {
    return theme === "dark"
      ? "border-[#5f4938] bg-[#2d241c] text-[#ffd3ad]"
      : "border-[#f2dccb] bg-[#fff4ea] text-[#b55d1c]";
  }
  return theme === "dark"
    ? "border-[var(--border)] bg-[var(--surface)] text-[var(--text-secondary)]"
    : "border-[#e7e1d6] bg-[var(--surface)] text-[var(--text-tertiary)]";
}

function formatCapturedAt(value: Date): string {
  return value.toLocaleString("en-GB", {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function parseTimestampMs(value?: string | null): number | null {
  const token = String(value || "").trim();
  if (!token) return null;
  const parsed = new Date(token);
  const timeMs = parsed.getTime();
  return Number.isFinite(timeMs) ? timeMs : null;
}

function readFileAsDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(new Error("Unable to read the photo."));
    reader.readAsDataURL(file);
  });
}

function normalizeUrineMarkerStatus(markerKey: string, rawStatus: unknown): string {
  const key = String(markerKey || "").trim().toLowerCase();
  const status = String(rawStatus || "")
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9+]+/g, "_")
    .replace(/^_+|_+$/g, "");
  if (!status) return "";
  if (status === "ready" || status === "queued") return status;
  if (["review", "needs_review", "uncertain", "unknown", "cannot_read", "not_visible"].includes(status)) {
    return "review";
  }
  if (key === "concentration") {
    if (["well", "dilute", "very_dilute", "very_low", "overhydrated", "well_hydrated"].includes(status)) {
      return "well";
    }
    if (["ok", "balanced", "normal", "clear", "hydrated", "in_range"].includes(status)) {
      return "ok";
    }
    if (["low", "concentrated", "high", "very_high", "dehydrated", "underhydrated"].includes(status)) {
      return "low";
    }
  }
  if (key === "uti") {
    if (["clear", "negative", "neg", "none", "normal", "ok"].includes(status)) return "clear";
    if (["watch", "trace", "small", "trace_small"].includes(status)) return "watch";
    if (["flagged", "positive", "pos", "moderate", "large", "moderate_large", "raised", "high"].includes(status)) {
      return "flagged";
    }
  }
  if (key === "protein" || key === "blood") {
    if (["clear", "negative", "neg", "none", "normal", "ok"].includes(status)) return "clear";
    if (["trace", "small", "trace_small", "non_hemolyzed", "non_haemolyzed"].includes(status)) return "trace";
    if (["flagged", "positive", "pos", "moderate", "large", "moderate_large", "raised", "high", "1+", "2+", "3+"].includes(status)) {
      return "flagged";
    }
  }
  if (key === "glucose") {
    if (["clear", "negative", "neg", "none", "normal", "ok"].includes(status)) return "clear";
    if (["raised", "positive", "pos", "trace", "small", "moderate", "large", "high", "1+", "2+", "3+"].includes(status)) {
      return "raised";
    }
  }
  if (key === "ketones") {
    if (["clear", "negative", "neg", "none", "normal", "ok"].includes(status)) return "clear";
    if (["trace", "small", "trace_small"].includes(status)) return "trace";
    if (["raised", "positive", "pos", "moderate", "large", "moderate_large", "high", "1+", "2+", "3+"].includes(status)) {
      return "raised";
    }
  }
  return status;
}

function normalizeUrineMarkers(markers?: UrineTestMarker[] | null): UrineTestMarker[] {
  const markerMap = new Map<string, UrineTestMarker>();
  (Array.isArray(markers) ? markers : []).forEach((marker) => {
    const markerKey = String(marker?.key || "").trim().toLowerCase();
    if (markerKey) markerMap.set(markerKey, marker);
  });
  return URINE_SCREENING_MARKERS.map((marker) => {
    const saved = markerMap.get(marker.key);
    const status =
      normalizeUrineMarkerStatus(marker.key, saved?.status) ||
      normalizeUrineMarkerStatus(marker.key, saved?.status_label) ||
      "ready";
    return {
      key: marker.key,
      label: marker.label,
      status,
      status_label: status,
      tone: saved?.tone || "neutral",
      source_analytes: saved?.source_analytes || [],
      status_options: saved?.status_options || [],
    };
  });
}

function formatUrineTileLabel(marker: UrineTestMarker): string {
  const markerKey = String(marker?.key || "").trim().toLowerCase();
  if (markerKey === "concentration") return "Hyd.";
  if (markerKey === "uti") return "UTI";
  if (markerKey === "protein") return "Prot.";
  if (markerKey === "blood") return "Blood";
  if (markerKey === "glucose") return "Gluc.";
  if (markerKey === "ketones") return "Ket.";
  return String(marker?.label || "").trim() || markerKey;
}

function resolveUrineMarkerTone(
  theme: DisplayTheme,
  marker: UrineTestMarker,
  context?: { glucoseRaised?: boolean; ketogenicDietActive?: boolean },
): string {
  const markerKey = String(marker?.key || "").trim().toLowerCase();
  const status = formatUrineStatusLabel(marker);
  const glucoseRaised = Boolean(context?.glucoseRaised);
  const ketogenicDietActive = Boolean(context?.ketogenicDietActive);
  if (markerKey === "concentration" && status === "well") {
    return theme === "dark"
      ? "border-[#57447a] bg-[#251f32] text-[#d8c9ff]"
      : "border-[#d8cbff] bg-[#f4efff] text-[#6b4cc2]";
  }
  if (markerKey === "concentration" && status === "ok") {
    return theme === "dark"
      ? "border-[#405b35] bg-[#1f2b1d] text-[#d9f0c5]"
      : "border-[#d5e8bf] bg-[#f2fae8] text-[#335f16]";
  }
  if (markerKey === "concentration" && status === "low") {
    return theme === "dark"
      ? "border-[#5f4938] bg-[#2d241c] text-[#ffd3ad]"
      : "border-[#f2dccb] bg-[#fff4ea] text-[#8a5a1a]";
  }
  if (markerKey === "uti" && status === "clear") {
    return theme === "dark"
      ? "border-[#405b35] bg-[#1f2b1d] text-[#d9f0c5]"
      : "border-[#d5e8bf] bg-[#f2fae8] text-[#335f16]";
  }
  if (markerKey === "uti" && status === "watch") {
    return theme === "dark"
      ? "border-[#5f4938] bg-[#2d241c] text-[#ffd3ad]"
      : "border-[#f2dccb] bg-[#fff4ea] text-[#8a5a1a]";
  }
  if (markerKey === "uti" && status === "flagged") {
    return theme === "dark"
      ? "border-[#674033] bg-[#2c1d1a] text-[#ffb7a1]"
      : "border-[#efc4b6] bg-[#fff0eb] text-[#9b3218]";
  }
  if (markerKey === "glucose" && status === "clear") {
    return theme === "dark"
      ? "border-[#405b35] bg-[#1f2b1d] text-[#d9f0c5]"
      : "border-[#d5e8bf] bg-[#f2fae8] text-[#335f16]";
  }
  if (markerKey === "glucose" && status === "raised") {
    return theme === "dark"
      ? "border-[#674033] bg-[#2c1d1a] text-[#ffb7a1]"
      : "border-[#efc4b6] bg-[#fff0eb] text-[#9b3218]";
  }
  if (markerKey === "ketones" && glucoseRaised && (status === "trace" || status === "raised")) {
    return theme === "dark"
      ? "border-[#674033] bg-[#2c1d1a] text-[#ffb7a1]"
      : "border-[#efc4b6] bg-[#fff0eb] text-[#9b3218]";
  }
  if (markerKey === "ketones" && ketogenicDietActive && status === "clear") {
    return theme === "dark"
      ? "border-[#5f4938] bg-[#2d241c] text-[#ffd3ad]"
      : "border-[#f2dccb] bg-[#fff4ea] text-[#8a5a1a]";
  }
  if (markerKey === "ketones" && ketogenicDietActive && status === "trace") {
    return theme === "dark"
      ? "border-[#405b35] bg-[#1f2b1d] text-[#d9f0c5]"
      : "border-[#d5e8bf] bg-[#f2fae8] text-[#335f16]";
  }
  if (markerKey === "ketones" && ketogenicDietActive && status === "raised") {
    return theme === "dark"
      ? "border-[#57447a] bg-[#251f32] text-[#d8c9ff]"
      : "border-[#d8cbff] bg-[#f4efff] text-[#6b4cc2]";
  }
  if (status === "clear" || status === "ok" || status === "well") {
    return theme === "dark"
      ? "border-[#405b35] bg-[#1f2b1d] text-[#d9f0c5]"
      : "border-[#d5e8bf] bg-[#f2fae8] text-[#335f16]";
  }
  if (status === "flagged") {
    return theme === "dark"
      ? "border-[#674033] bg-[#2c1d1a] text-[#ffb7a1]"
      : "border-[#efc4b6] bg-[#fff0eb] text-[#9b3218]";
  }
  if (status === "watch" || status === "trace" || status === "raised" || status === "low" || status === "queued" || status === "review") {
    return theme === "dark"
      ? "border-[#5f4938] bg-[#2d241c] text-[#ffd3ad]"
      : "border-[#f2dccb] bg-[#fff4ea] text-[#8a5a1a]";
  }
  return theme === "dark"
    ? "border-[var(--border)] bg-[var(--surface)] text-[var(--text-secondary)]"
    : "border-[#e7e1d6] bg-[var(--surface)] text-[var(--text-tertiary)]";
}

function formatUrineStatusLabel(marker: UrineTestMarker): string {
  const markerKey = String(marker?.key || "").trim().toLowerCase();
  const status = normalizeUrineMarkerStatus(markerKey, marker?.status);
  const statusLabel = normalizeUrineMarkerStatus(markerKey, marker?.status_label);
  return status || statusLabel || "ready";
}

function formatUrineDisplayStatusLabel(marker: UrineTestMarker): string {
  const markerKey = String(marker?.key || "").trim().toLowerCase();
  const label = formatUrineStatusLabel(marker);
  if (markerKey === "concentration") {
    if (label === "well") return "Well";
    if (label === "ok") return "OK";
    if (label === "low") return "Low";
  }
  return label;
}

function formatUrineExplanationStatusLabel(marker: UrineTestMarker): string {
  const label = formatUrineDisplayStatusLabel(marker);
  if (!label || label === "—") return "—";
  if (label === "OK") return label;
  return `${label.charAt(0).toUpperCase()}${label.slice(1)}`;
}

function formatUrineTestDayMonth(urineTest?: UrineTestResponse | null): { day: string; month: string } {
  const token = String(urineTest?.captured_at || urineTest?.sample_date || "").trim();
  if (!token) return { day: "—", month: "" };
  const parsed = new Date(token.includes("T") ? token : `${token}T12:00:00`);
  if (Number.isNaN(parsed.getTime())) return { day: token, month: "" };
  return {
    day: parsed.toLocaleDateString("en-GB", { day: "numeric" }),
    month: parsed.toLocaleDateString("en-GB", { month: "short" }),
  };
}

function resolveUrineStatusDotTone(
  theme: DisplayTheme,
  marker: UrineTestMarker,
  context?: { glucoseRaised?: boolean; ketogenicDietActive?: boolean },
): string {
  const markerKey = String(marker?.key || "").trim().toLowerCase();
  const status = formatUrineStatusLabel(marker);
  const glucoseRaised = Boolean(context?.glucoseRaised);
  const ketogenicDietActive = Boolean(context?.ketogenicDietActive);
  if (markerKey === "concentration" && status === "well") {
    return theme === "dark" ? "border-[#d8c9ff] bg-[#8d72df]" : "border-[#7c62cf] bg-[#6b4cc2]";
  }
  if (markerKey === "concentration" && status === "ok") {
    return theme === "dark" ? "border-[#6e8c55] bg-[#d9f0c5]" : "border-[#8db66b] bg-[#69a23a]";
  }
  if (markerKey === "concentration" && status === "low") {
    return theme === "dark" ? "border-[#ffd3ad] bg-[#e8a867]" : "border-[#d9a25f] bg-[#f0b35f]";
  }
  if (markerKey === "uti" && status === "clear") {
    return theme === "dark" ? "border-[#6e8c55] bg-[#d9f0c5]" : "border-[#8db66b] bg-[#69a23a]";
  }
  if (markerKey === "uti" && status === "watch") {
    return theme === "dark" ? "border-[#ffd3ad] bg-[#e8a867]" : "border-[#d9a25f] bg-[#f0b35f]";
  }
  if (markerKey === "uti" && status === "flagged") {
    return theme === "dark" ? "border-[#ffb7a1] bg-[#ef6d4c]" : "border-[#d66a48] bg-[#c54817]";
  }
  if (markerKey === "glucose" && status === "clear") {
    return theme === "dark" ? "border-[#6e8c55] bg-[#d9f0c5]" : "border-[#8db66b] bg-[#69a23a]";
  }
  if (markerKey === "glucose" && status === "raised") {
    return theme === "dark" ? "border-[#ffb7a1] bg-[#ef6d4c]" : "border-[#d66a48] bg-[#c54817]";
  }
  if (markerKey === "ketones" && glucoseRaised && (status === "trace" || status === "raised")) {
    return theme === "dark" ? "border-[#ffb7a1] bg-[#ef6d4c]" : "border-[#d66a48] bg-[#c54817]";
  }
  if (markerKey === "ketones" && ketogenicDietActive && status === "clear") {
    return theme === "dark" ? "border-[#ffd3ad] bg-[#e8a867]" : "border-[#d9a25f] bg-[#f0b35f]";
  }
  if (markerKey === "ketones" && ketogenicDietActive && status === "trace") {
    return theme === "dark" ? "border-[#6e8c55] bg-[#d9f0c5]" : "border-[#8db66b] bg-[#69a23a]";
  }
  if (markerKey === "ketones" && ketogenicDietActive && status === "raised") {
    return theme === "dark" ? "border-[#d8c9ff] bg-[#8d72df]" : "border-[#7c62cf] bg-[#6b4cc2]";
  }
  if (status === "clear" || status === "ok" || status === "well") {
    return theme === "dark" ? "border-[#6e8c55] bg-[#d9f0c5]" : "border-[#8db66b] bg-[#69a23a]";
  }
  if (status === "flagged" || status === "raised") {
    return theme === "dark" ? "border-[#ffb7a1] bg-[#ef6d4c]" : "border-[#d66a48] bg-[#c54817]";
  }
  if (status === "watch" || status === "trace" || status === "low" || status === "review") {
    return theme === "dark" ? "border-[#ffd3ad] bg-[#e8a867]" : "border-[#d9a25f] bg-[#f0b35f]";
  }
  return theme === "dark" ? "border-[var(--border)] bg-[#6b6257]" : "border-[var(--border)] bg-[#d8d0c5]";
}

function resolveUrineResultMessage(urineTest?: UrineTestResponse | null): string | null {
  const payload = urineTest?.result_payload;
  if (!payload || typeof payload !== "object") return null;
  const notes = Array.isArray(payload.notes) ? payload.notes : [];
  const firstNote = notes.map((note) => String(note || "").trim()).find(Boolean);
  if (firstNote) return firstNote;
  const screeningNote = String(payload.screening_note || "").trim();
  return screeningNote || null;
}

function resolveBiomarkerExplanationTone(theme: DisplayTheme, tone: BiomarkerExplanationTone = "neutral"): string {
  if (tone === "purple") {
    return theme === "dark"
      ? "border-[#57447a] bg-[#251f32] text-[#d8c9ff]"
      : "border-[#d8cbff] bg-[#f4efff] text-[#6b4cc2]";
  }
  if (tone === "green") {
    return theme === "dark"
      ? "border-[#405b35] bg-[#1f2b1d] text-[#d9f0c5]"
      : "border-[#d5e8bf] bg-[#f2fae8] text-[#335f16]";
  }
  if (tone === "amber") {
    return theme === "dark"
      ? "border-[#5f4938] bg-[#2d241c] text-[#ffd3ad]"
      : "border-[#f2dccb] bg-[#fff4ea] text-[#8a5a1a]";
  }
  if (tone === "red") {
    return theme === "dark"
      ? "border-[#674033] bg-[#2c1d1a] text-[#ffb7a1]"
      : "border-[#efc4b6] bg-[#fff0eb] text-[#9b3218]";
  }
  return theme === "dark"
    ? "border-[var(--border)] bg-[var(--surface)] text-[var(--text-secondary)]"
    : "border-[#e7e1d6] bg-[var(--surface)] text-[var(--text-tertiary)]";
}

function urineStatusDot(
  theme: DisplayTheme,
  markerKey: string,
  status: string,
  context?: { glucoseRaised?: boolean; ketogenicDietActive?: boolean },
): string {
  return resolveUrineStatusDotTone(
    theme,
    { key: markerKey, status, status_label: status },
    context,
  );
}

function BiomarkerExplanationCard({
  className = "mt-4",
  description,
  result,
  scaleRows,
  showMarkerColumn = true,
  theme,
  title,
}: {
  className?: string;
  description?: string;
  result: string;
  scaleRows: BiomarkerExplanationScaleRow[];
  showMarkerColumn?: boolean;
  theme: DisplayTheme;
  title: string;
}) {
  const cardToneClassName =
    theme === "dark"
      ? "border-[var(--border)] bg-[var(--surface)] text-[var(--text-secondary)]"
      : "border-[var(--border)] bg-[#fffaf3] text-[var(--text-secondary)]";
  const titleToneClassName = theme === "dark" ? "text-[var(--text-primary)]" : "text-[var(--text-primary)]";
  const tableToneClassName =
    theme === "dark" ? "border-[var(--border)] bg-[#151a24]" : "border-[var(--border)] bg-[var(--surface)]";
  const headerToneClassName =
    theme === "dark"
      ? "border-[var(--border)] bg-[#1c2230] text-[var(--text-secondary)]"
      : "border-[var(--border)] bg-[#fff7ec] text-[var(--text-tertiary)]";
  const rowBorderClassName = theme === "dark" ? "border-[var(--border)]" : "border-[#f3eadf]";
  const markerTextClassName = theme === "dark" ? "text-[var(--text-primary)]" : "text-[var(--text-primary)]";
  const meaningTextClassName = theme === "dark" ? "text-[var(--text-secondary)]" : "text-[var(--text-secondary)]";
  return (
    <div className={`${className} rounded-2xl border px-4 py-3 text-sm ${cardToneClassName}`}>
      <p className={`font-semibold ${titleToneClassName}`}>{title}</p>
      {description ? <p className="mt-2">{description}</p> : null}
      <p className="mt-2">{result}</p>
      <div className={`mt-4 overflow-x-auto rounded-2xl border ${tableToneClassName}`}>
        <table className={`w-full ${showMarkerColumn ? "min-w-[32rem]" : "min-w-[24rem]"} border-collapse text-left`}>
          <thead>
            <tr className={`border-b text-[10px] font-semibold uppercase tracking-[0.16em] ${headerToneClassName}`}>
              {showMarkerColumn ? <th className="px-3 py-2 font-semibold">Marker</th> : null}
              <th className="px-3 py-2 font-semibold">Status</th>
              <th className="px-3 py-2 font-semibold">Meaning</th>
            </tr>
          </thead>
          <tbody>
            {scaleRows.map((row, index) => (
              <tr key={`${row.marker}-${row.status}-${index}`} className={`border-b last:border-b-0 ${rowBorderClassName}`}>
                {showMarkerColumn ? (
                  <td className={`px-3 py-2 align-middle text-xs font-semibold ${markerTextClassName}`}>
                    {row.marker}
                  </td>
                ) : null}
                <td className="px-3 py-2 align-middle">
                  <span
                    className={`inline-flex min-h-9 min-w-[4.5rem] items-center justify-center gap-2 rounded-xl border px-2 py-1 text-[10px] font-semibold uppercase tracking-[0.12em] ${resolveBiomarkerExplanationTone(theme, row.tone)}`}
                  >
                    {row.dotClassName ? <span className={`block h-4 w-4 rounded-full border-2 ${row.dotClassName}`} /> : null}
                    {row.status}
                  </span>
                </td>
                <td className={`px-3 py-2 align-middle text-xs leading-relaxed ${meaningTextClassName}`}>
                  {row.meaning}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function BiometricStatusCircle({
  detail,
  label,
  metricDate,
  status,
  toneClassName,
}: {
  detail?: string | null;
  label: string;
  metricDate: string;
  status?: string | null;
  toneClassName: string;
}) {
  const resolvedLabel = label || "—";
  const hasStatus = Boolean(String(status || "").trim()) && String(status || "").trim().toLowerCase() !== "unknown";
  return (
    <div className="flex min-w-0 flex-col items-center text-center">
      <p className="text-[10px] font-semibold leading-none text-[var(--text-tertiary)]">{formatBiometricDayLabel(metricDate)}</p>
      <p className="mt-1 text-[10px] leading-none text-[var(--text-tertiary)]">{formatBiometricDayNumber(metricDate)}</p>
      <div
        className={`mt-2 flex h-10 w-10 items-center justify-center rounded-full border text-[8px] font-semibold uppercase leading-none sm:h-11 sm:w-11 ${toneClassName}`}
      >
        {hasStatus ? resolvedLabel : "—"}
      </div>
      {detail ? <p className="mt-2 min-h-[1.75rem] text-[9px] leading-tight text-[var(--text-secondary)]">{detail}</p> : null}
    </div>
  );
}

function formatIsoLocalDay(value: Date): string {
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, "0");
  const day = String(value.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function parseIsoLocalDay(value?: string | null): Date | null {
  const token = String(value || "").trim();
  const match = token.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!match) return null;
  const year = Number.parseInt(match[1] || "", 10);
  const month = Number.parseInt(match[2] || "", 10) - 1;
  const day = Number.parseInt(match[3] || "", 10);
  const parsed = new Date(year, month, day, 12, 0, 0, 0);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

function addLocalDays(date: Date, days: number): Date {
  const next = new Date(date);
  next.setDate(next.getDate() + days);
  return next;
}

function monthStart(date: Date): Date {
  return new Date(date.getFullYear(), date.getMonth(), 1, 12, 0, 0, 0);
}

function formatStreakMonthLabel(date: Date): string {
  return date.toLocaleDateString("en-GB", { month: "long", year: "numeric" });
}

function buildStreakCalendarDays(monthDate: Date, todayIso: string): StreakCalendarDay[] {
  const start = monthStart(monthDate);
  const startOffset = (start.getDay() + 6) % 7;
  const gridStart = addLocalDays(start, -startOffset);
  const todayDate = parseIsoLocalDay(todayIso) || parseIsoLocalDay(formatIsoLocalDay(new Date())) || new Date();
  const daysInMonth = new Date(start.getFullYear(), start.getMonth() + 1, 0).getDate();
  const cellCount = Math.ceil((startOffset + daysInMonth) / 7) * 7;
  return Array.from({ length: cellCount }, (_, index) => {
    const date = addLocalDays(gridStart, index);
    const iso = formatIsoLocalDay(date);
    return {
      key: iso,
      iso,
      dayNumber: date.getDate(),
      inMonth: date.getMonth() === start.getMonth(),
      isToday: iso === formatIsoLocalDay(todayDate),
      isFuture: date.getTime() > todayDate.getTime(),
    };
  });
}

function collectTrackerCompletionDates(summary?: PillarTrackerSummaryResponse | null): string[] {
  const dates = new Set<string>();
  const today = String(summary?.today || "").trim();
  if (summary?.today_complete && today) {
    dates.add(today);
  }
  const pillars = Array.isArray(summary?.pillars) ? summary.pillars : [];
  for (const pillar of pillars) {
    if (pillar?.today_complete && today) {
      dates.add(today);
    }
    const options = Array.isArray(pillar?.checkin_options) ? pillar.checkin_options : [];
    for (const option of options) {
      const optionDate = String(option?.date || "").trim();
      if (option?.complete && optionDate) {
        dates.add(optionDate);
      }
    }
  }
  return Array.from(dates);
}

function resolveBiometricEndDay(...values: Array<string | null | undefined>): string {
  const today = new Date();
  let latest: Date | null = new Date(`${formatIsoLocalDay(today)}T12:00:00`);
  values.forEach((value) => {
    const token = String(value || "").trim();
    if (!token) return;
    const parsed = new Date(`${token}T12:00:00`);
    if (Number.isNaN(parsed.getTime())) return;
    if (!latest || parsed.getTime() > latest.getTime()) {
      latest = parsed;
    }
  });
  return latest ? formatIsoLocalDay(latest) : formatIsoLocalDay(new Date());
}

function buildBiometricWeek<T extends { metric_date?: string | null }>(
  history: T[],
  endDayToken?: string | null,
): Array<{ metric_date: string; item: T | null }> {
  const byDay = new Map<string, T>();
  history.forEach((item) => {
    const token = String(item?.metric_date || "").trim();
    if (!token) return;
    byDay.set(token, item);
  });
  const resolvedEndDay = resolveBiometricEndDay(endDayToken);
  const endDate = new Date(`${resolvedEndDay}T12:00:00`);
  if (Number.isNaN(endDate.getTime())) return [];
  const items: Array<{ metric_date: string; item: T | null }> = [];
  for (let offset = 6; offset >= 0; offset -= 1) {
    const current = new Date(endDate);
    current.setDate(endDate.getDate() - offset);
    const metricDate = formatIsoLocalDay(current);
    items.push({
      metric_date: metricDate,
      item: byDay.get(metricDate) || null,
    });
  }
  return items;
}

function isDailyCheckInComplete(summary?: PillarTrackerSummaryResponse | null): boolean {
  if (!summary) return false;
  if (summary.today_complete === true) return true;
  const totalPillars = Number(summary.total_pillars);
  const completedPillars = Number(summary.today_completed_pillars_count);
  if (Number.isFinite(totalPillars) && totalPillars > 0 && Number.isFinite(completedPillars)) {
    return completedPillars >= totalPillars;
  }
  const pillars = Array.isArray(summary.pillars) ? summary.pillars : [];
  return pillars.length > 0 && pillars.every((pillar) => pillar?.today_complete === true);
}

function readMorningSequenceState(
  userId: string,
  dayToken: string | null | undefined,
): MorningSequenceState {
  if (typeof window === "undefined") return "idle";
  const normalizedUserId = String(userId || "").trim();
  const normalizedDayToken = String(dayToken || "").trim();
  if (!normalizedUserId || !normalizedDayToken) return "idle";
  try {
    const raw = String(
      window.localStorage.getItem(
        `${MORNING_SEQUENCE_STORAGE_PREFIX}:${normalizedUserId}:${normalizedDayToken}`,
      ) || "",
    )
      .trim()
      .toLowerCase();
    if (raw === "completed" || raw === "1") return "completed";
    if (raw === "in_progress") return "in_progress";
    return "idle";
  } catch {
    return "idle";
  }
}

function resolveSummaryPanelVisible(
  summary: PillarTrackerSummaryResponse,
  sequenceState: MorningSequenceState,
): boolean {
  if (Array.isArray(summary.pillars) && summary.pillars.length > 0) return true;
  if (sequenceState === "completed") return true;
  if (sequenceState === "in_progress") return true;
  return isDailyCheckInComplete(summary);
}

function resolveCurrentDisplayTheme(): DisplayTheme {
  if (typeof document !== "undefined") {
    const resolved = String(document.documentElement.dataset.theme || "").trim().toLowerCase();
    if (resolved === "light" || resolved === "dark") {
      return resolved;
    }
  }
  const stored = readStoredThemePreference();
  return stored === "light" ? "light" : "dark";
}

function sortPillars(pillars: PillarTrackerPillar[]): PillarTrackerPillar[] {
  return [...pillars].sort((a, b) => {
    const left = PILLAR_ORDER.indexOf(String(a.pillar_key || "").trim().toLowerCase());
    const right = PILLAR_ORDER.indexOf(String(b.pillar_key || "").trim().toLowerCase());
    return (left === -1 ? 99 : left) - (right === -1 ? 99 : right);
  });
}

function normalizeError(text: string, fallback: string): string {
  if (!text) return fallback;
  try {
    const parsed = JSON.parse(text) as { error?: string };
    return String(parsed.error || fallback);
  } catch {
    return text;
  }
}

function resolveScore(value?: number | null): number | null {
  const resolved = Number(value);
  if (!Number.isFinite(resolved)) return null;
  return Math.max(0, Math.min(100, Math.round(resolved)));
}

function resolvePillarDisplayScore(pillar: PillarTrackerPillar): number | null {
  return resolveScore(pillar.tracker_score ?? pillar.score);
}

function circleDayTone(theme: DisplayTheme, status?: string | null, isActive?: boolean): string {
  const activeRing = isActive
    ? theme === "dark"
      ? " ring-1 ring-[#f2dccb]"
      : " ring-1 ring-[#8c7b65]"
    : "";
  if (status === "success") {
    return theme === "dark"
      ? `border-[#7fbf5a] bg-[#24401f] text-[#e4ffd6]${activeRing}`
      : `border-[#79b84a] bg-[#dff5cf] text-[#1f5a14]${activeRing}`;
  }
  if (status === "warning") {
    return theme === "dark"
      ? `border-[#d89a54] bg-[#44301d] text-[#ffe0b8]${activeRing}`
      : `border-[#d28a35] bg-[#ffead1] text-[#794712]${activeRing}`;
  }
  if (status === "danger") {
    return theme === "dark"
      ? `border-[#f07b61] bg-[#4a211b] text-[#ffd7cf]${activeRing}`
      : `border-[#d25b3f] bg-[#ffe1d8] text-[#8f2414]${activeRing}`;
  }
  return theme === "dark"
    ? `border-[var(--border)] bg-[var(--surface)] text-[var(--text-secondary)]${activeRing}`
    : `border-[#ece5d9] bg-[var(--surface)] text-[var(--text-tertiary)]${activeRing}`;
}

function WeeklyScoreRing({ value, tone, compact = false }: { value?: number | null; tone: string; compact?: boolean }) {
  const resolved = resolveScore(value);
  if (resolved !== null) {
    return (
      <div className={compact ? "origin-center scale-[0.78] sm:scale-100" : ""}>
        <ScoreRing value={resolved} tone={tone} />
      </div>
    );
  }
  return (
    <div className={compact ? "origin-center scale-[0.78] sm:scale-100" : ""}>
      <div className="relative flex h-[84px] w-[84px] items-center justify-center">
        <div className="h-[84px] w-[84px] rounded-full border-[8px] border-[var(--border)]" />
        <span className="absolute text-lg font-semibold text-[var(--text-tertiary)]">—</span>
      </div>
    </div>
  );
}

function resolveHomePillarQuote(pillar: PillarTrackerPillar, pillarKey: string): string {
  const quote = String(pillar.daily_quote || "").trim();
  if (quote) return quote;
  return HOME_PILLAR_QUOTE_FALLBACKS[pillarKey] || "Take one small step today that supports your wellbeing.";
}

function InsightIcon({ className = "h-5 w-5 text-[var(--accent)]" }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      className={className}
      aria-hidden="true"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M12 3a7 7 0 0 0-4 12.7c.6.4 1 1 1.2 1.7h5.6c.2-.7.6-1.3 1.2-1.7A7 7 0 0 0 12 3Z" />
      <path d="M9.5 21h5" />
      <path d="M10 18.5h4" />
    </svg>
  );
}

function BiometricsIcon({ className = "h-5 w-5 text-[var(--accent)]" }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      className={className}
      aria-hidden="true"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M4 14.5h3l1.8-5 3.1 9 2.1-6h6" />
      <path d="M7.5 5.5a3.5 3.5 0 0 1 5 0L12 6l-.5-.5a3.5 3.5 0 0 1 5 0c1.4 1.4 1.4 3.6 0 5L12 15l-4.5-4.5a3.5 3.5 0 0 1 0-5Z" />
      <path d="M18.5 17.5a2.5 2.5 0 0 0-5 0c0 1.9 2.5 4 2.5 4s2.5-2.1 2.5-4Z" />
    </svg>
  );
}

function SetupSwipeHint() {
  return (
    <span
      className="absolute bottom-5 right-5 flex h-12 w-12 items-center justify-center rounded-full border border-[var(--border)] bg-[var(--surface)] text-[var(--text-primary)] shadow-[0_10px_26px_-22px_rgba(30,27,22,0.45)]"
      aria-hidden="true"
    >
      <span className="text-3xl leading-none">›</span>
    </span>
  );
}

function SetupHealthSenseLogo() {
  return (
    <span className="absolute right-6 top-6 flex h-12 w-12 items-center justify-center" aria-label="HealthSense">
      <img src="/healthsense-mark.svg" alt="" className="h-12 w-12 object-contain" />
    </span>
  );
}

function SetupLineIcon({ iconKey, className = "h-9 w-9" }: { iconKey: string; className?: string }) {
  const key = String(iconKey || "").trim().toLowerCase();
  const commonProps = {
    viewBox: "0 0 24 24",
    className,
    "aria-hidden": true,
    fill: "none",
    stroke: "currentColor",
    strokeWidth: "1.8",
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
  };

  switch (key) {
    case "reflection":
      return (
        <svg {...commonProps}>
          <path d="M4 12s3.1-5.5 8-5.5S20 12 20 12s-3.1 5.5-8 5.5S4 12 4 12Z" />
          <path d="M12 14.5a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5Z" />
        </svg>
      );
    case "purpose":
      return (
        <svg {...commonProps}>
          <path d="M12 21s7-5.3 7-11a7 7 0 0 0-14 0c0 5.7 7 11 7 11Z" />
          <path d="M12 13a3 3 0 1 0 0-6 3 3 0 0 0 0 6Z" />
          <path d="M12 10h2" />
        </svg>
      );
    case "resilience":
      return (
        <svg {...commonProps}>
          <path d="M6 13.5c1.9-2 4.2-2 6 0s4.1 2 6 0" />
          <path d="M6 17c1.9-2 4.2-2 6 0s4.1 2 6 0" />
          <path d="M12 4.5a5 5 0 0 0-5 5c0 1.4.6 2.6 1.5 3.5" />
          <path d="M12 4.5a5 5 0 0 1 5 5c0 1.4-.6 2.6-1.5 3.5" />
        </svg>
      );
    case "recovery":
      return (
        <svg {...commonProps}>
          <path d="M19 15.2A7.2 7.2 0 0 1 8.8 5a7.8 7.8 0 1 0 10.2 10.2Z" />
          <path d="M16.5 4.8h3" />
          <path d="M18 3.3v3" />
          <path d="M7.5 16.5c1.4 1 3.1 1.5 5 1.2" />
        </svg>
      );
    case "nutrition":
      return (
        <svg {...commonProps}>
          <path d="M6 4.5v15" />
          <path d="M9 4.5v5a3 3 0 0 1-3 3" />
          <path d="M15.5 4.5c2.2.7 3.5 2.8 3.5 5.2 0 2.6-1.5 4.8-3.5 5.3v4.5" />
          <path d="M15.5 4.5v10.5" />
        </svg>
      );
    case "training":
      return (
        <svg {...commonProps}>
          <path d="M4 10v4" />
          <path d="M7 8v8" />
          <path d="M17 8v8" />
          <path d="M20 10v4" />
          <path d="M7 12h10" />
        </svg>
      );
    case "checkin":
      return (
        <svg {...commonProps}>
          <path d="M5 5.5h14v13H5z" />
          <path d="M8 9h8" />
          <path d="M8 13h3" />
          <path d="m13.5 14.2 1.5 1.5 3-3.4" />
        </svg>
      );
    case "targets":
      return (
        <svg {...commonProps}>
          <circle cx="12" cy="12" r="7.5" />
          <circle cx="12" cy="12" r="3.5" />
          <path d="M12 12 18.5 5.5" />
          <path d="M17.8 4.2h2v2" />
        </svg>
      );
    case "scoring":
      return (
        <svg {...commonProps}>
          <path d="M4.5 18.5h15" />
          <path d="M7 18.5v-5" />
          <path d="M12 18.5v-9" />
          <path d="M17 18.5v-12" />
          <path d="M6.5 7.5 10 4l3 3 4.5-4.5" />
        </svg>
      );
    case "lessons":
      return (
        <svg {...commonProps}>
          <path d="M5 5.5h10a3 3 0 0 1 3 3v10H8a3 3 0 0 1-3-3v-10Z" />
          <path d="M8.5 9h6" />
          <path d="M8.5 12.5h6" />
          <path d="M8 18.5V7.5" />
        </svg>
      );
  }

  return (
    <svg {...commonProps}>
      <path d="M12 3a7 7 0 0 0-4 12.7c.6.4 1 1 1.2 1.7h5.6c.2-.7.6-1.3 1.2-1.7A7 7 0 0 0 12 3Z" />
      <path d="M9.5 21h5" />
      <path d="M10 18.5h4" />
    </svg>
  );
}

function SetupCardIcon({ iconKey, tone, background }: { iconKey: string; tone: string; background: string }) {
  return (
    <span className="absolute right-5 top-5 flex h-[84px] w-[84px] shrink-0 items-center justify-center" aria-hidden="true">
      <svg width="84" height="84" className="absolute inset-0 rotate-[-90deg]">
        <circle cx="42" cy="42" r="38" stroke="var(--ring-track)" strokeWidth="8" fill="none" />
        <circle cx="42" cy="42" r="38" stroke={tone} strokeWidth="8" fill="none" strokeLinecap="round" />
      </svg>
      <span
        className="relative flex h-[60px] w-[60px] items-center justify-center rounded-full text-[#17120f]"
        style={{ backgroundColor: background }}
      >
        <SetupLineIcon iconKey={iconKey} />
      </span>
    </span>
  );
}

function SetupPillarSelectionCircle({ pillarKey, selected }: { pillarKey: string; selected: boolean }) {
  const palette = getPillarPalette(pillarKey);
  return (
    <span className="absolute right-5 top-5 flex h-[84px] w-[84px] shrink-0 items-center justify-center" aria-hidden="true">
      <svg width="84" height="84" className="absolute inset-0 rotate-[-90deg]">
        <circle cx="42" cy="42" r="38" stroke="var(--ring-track)" strokeWidth="8" fill="none" />
        <circle cx="42" cy="42" r="38" stroke={palette.accent} strokeWidth="8" fill="none" strokeLinecap="round" />
      </svg>
      <span
        className="relative flex h-[60px] w-[60px] items-center justify-center rounded-full text-[#17120f]"
        style={{ backgroundColor: selected ? palette.accent : palette.bg }}
      >
        {selected ? (
          <svg viewBox="0 0 24 24" className="h-9 w-9 text-white" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round">
            <path d="M5 12.5 10 17l9-10" />
          </svg>
        ) : (
          <svg viewBox="0 0 24 24" className="h-9 w-9" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M12 5v14" />
            <path d="M5 12h14" />
          </svg>
        )}
      </span>
    </span>
  );
}

function SetupGuideIcon({ iconKey }: { iconKey: string }) {
  return <SetupCardIcon iconKey={iconKey} tone="var(--accent)" background="var(--accent-soft)" />;
}

function WeeklyObjectiveSectionIcon({ sectionKey }: { sectionKey: string }) {
  const normalizedKey = String(sectionKey || "").trim().toLowerCase();
  const iconSrc = normalizedKey === "wellbeing" ? "/healthsense-mark.svg" : getPillarPalette(normalizedKey).icon;
  if (!iconSrc) return null;
  return (
    <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl border border-[var(--border)] bg-[#fffaf3]">
      <img src={iconSrc} alt="" aria-hidden="true" className="h-6 w-6 object-contain" />
    </span>
  );
}

function formatWeeklyObjectiveSectionLabel(sectionKey: string, label?: string | null): string {
  const normalizedKey = String(sectionKey || "").trim().toLowerCase();
  if (normalizedKey === "wellbeing") return "General";
  return String(label || "").trim() || normalizedKey.replace(/_/g, " ");
}

function getWellbeingObjectivePillarKey(item: WeeklyObjectiveWellbeingItem): ObjectivesSectionKey | null {
  const itemKey = String(item?.key || "").trim().toLowerCase();
  if (["fasting_mode", "alcohol_tracking", "ketogenic_diet", "omega_3", "vitamin_d"].includes(itemKey)) {
    return "nutrition";
  }
  if (itemKey === "creatine") {
    return "training";
  }
  if (["heat_exposure", "cold_exposure", "magnesium"].includes(itemKey)) {
    return "recovery";
  }
  return null;
}

function isWellbeingObjectiveConfigured(
  item: WeeklyObjectiveWellbeingItem,
  draft: Record<string, string>,
): boolean {
  const itemKey = String(item?.key || "").trim();
  const itemValue = String(draft[itemKey] ?? item?.value ?? "off").trim().toLowerCase();
  if (["fasting_mode"].includes(itemKey)) return itemValue !== "off";
  if (["alcohol_tracking", "ketogenic_diet"].includes(itemKey)) return itemValue === "on";
  const fields = Array.isArray(item?.fields) ? item.fields : [];
  if (!fields.length) return itemValue === "on";
  return fields.some((field) => {
    const fieldKey = String(field?.key || "").trim();
    const fieldValue = Number(draft[fieldKey] ?? field?.value ?? 0);
    return Number.isFinite(fieldValue) && fieldValue > 0;
  });
}

export default function LatestAssessmentPanel({
  userId,
  initialSummary,
  initialAssessmentReviewed = false,
  initialInteractionDaysCount = null,
  isAdminUser = false,
}: LatestAssessmentPanelProps) {
  const [summary, setSummary] = useState<PillarTrackerSummaryResponse>(initialSummary);
  const [summaryPanelVisible, setSummaryPanelVisible] = useState(
    () => resolveSummaryPanelVisible(initialSummary, "idle"),
  );
  const [displayTheme, setDisplayTheme] = useState<DisplayTheme>("light");
  const [selectedPillarKey, setSelectedPillarKey] = useState<string | null>(null);
  const [detail, setDetail] = useState<PillarTrackerDetailResponse | null>(null);
  const [draft, setDraft] = useState<Record<string, number>>({});
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [saving, setSaving] = useState(false);
  const [guidedTrackingActive, setGuidedTrackingActive] = useState(false);
  const [trackerReturnSurface, setTrackerReturnSurface] = useState<TrackerReturnSurface | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [assessmentReviewed, setAssessmentReviewed] = useState(initialAssessmentReviewed);
  const [assessmentReviewSyncStarted, setAssessmentReviewSyncStarted] = useState(initialAssessmentReviewed);
  const [objectivesModalOpen, setObjectivesModalOpen] = useState(false);
  const [streakSectionOpen, setStreakSectionOpen] = useState(false);
  const [streakCalendarMonth, setStreakCalendarMonth] = useState(() => {
    const baseDate = parseIsoLocalDay(initialSummary.today) || new Date();
    return monthStart(baseDate);
  });
  const [weeklyObjectives, setWeeklyObjectives] = useState<WeeklyObjectivesResponse | null>(null);
  const [weeklyObjectivesLoading, setWeeklyObjectivesLoading] = useState(false);
  const [weeklyObjectivesError, setWeeklyObjectivesError] = useState<string | null>(null);
  const [weeklyObjectivesSaving, setWeeklyObjectivesSaving] = useState(false);
  const [selectedObjectivesSection, setSelectedObjectivesSection] = useState<ObjectivesSectionKey | null>(null);
  const [pillarObjectiveDrafts, setPillarObjectiveDrafts] = useState<Record<string, Record<string, number | null>>>({});
  const [wellbeingObjectiveDraft, setWellbeingObjectiveDraft] = useState<Record<string, string>>({});
  const [restingHeartRate, setRestingHeartRate] = useState<AppleHealthRestingHeartRateResponse | null>(null);
  const [biometricsModalOpen, setBiometricsModalOpen] = useState(false);
  const [biometricSourceCheckOpen, setBiometricSourceCheckOpen] = useState(false);
  const [urineTestFlowOpen, setUrineTestFlowOpen] = useState(false);
  const [activeBiomarkerExplanation, setActiveBiomarkerExplanation] = useState<BiomarkerExplanationKey | null>(null);
  const [restingHeartRateLoading, setRestingHeartRateLoading] = useState(false);
  const [restingHeartRateEnabling, setRestingHeartRateEnabling] = useState(false);
  const [biometricPreferenceSaving, setBiometricPreferenceSaving] = useState<string | null>(null);
  const [biometricsActionError, setBiometricsActionError] = useState<string | null>(null);
  const [wearableConnectPending, setWearableConnectPending] = useState<string | null>(null);
  const [, setAppleHealthAuthStatus] = useState<AppleHealthAuthorizationState>("unsupported");
  const [urineTest, setUrineTest] = useState<UrineTestResponse | null>(null);
  const [urineTestLoading, setUrineTestLoading] = useState(false);
  const [urineTestSaving, setUrineTestSaving] = useState(false);
  const [urineTestError, setUrineTestError] = useState<string | null>(null);
  const [urineCaptureStartedAt, setUrineCaptureStartedAt] = useState<number | null>(null);
  const [urineTimerSecondsLeft, setUrineTimerSecondsLeft] = useState(0);
  const appleHealthAutoRequestRef = useRef(false);
  const urinePhotoCameraInputRef = useRef<HTMLInputElement | null>(null);
  const urinePhotoLibraryInputRef = useRef<HTMLInputElement | null>(null);
  const summaryPanelRef = useRef<HTMLElement | null>(null);
  const pillarCueCardRefs = useRef<Record<string, HTMLElement | null>>({});
  const [returnToPillarKey, setReturnToPillarKey] = useState<string | null>(null);
  const [urinePhotoName, setUrinePhotoName] = useState<string | null>(null);
  const [urinePhotoCapturedAt, setUrinePhotoCapturedAt] = useState<string | null>(null);
  const [urinePhotoCapturedAtMs, setUrinePhotoCapturedAtMs] = useState<number | null>(null);
  const [urineCaptureNowMs, setUrineCaptureNowMs] = useState(() => Date.now());
  const [activeDockKey, setActiveDockKey] = useState<"checkin" | "learn">("checkin");
  const [setupPillarSelections, setSetupPillarSelections] = useState<Record<string, boolean>>(() =>
    initialSetupPillarSelections(initialSummary, isAdminUser),
  );
  const [setupSaving, setSetupSaving] = useState(false);
  const [setupError, setSetupError] = useState<string | null>(null);
  const appSetupRequired = summary.app_setup_completed !== true;
  const setupSelectablePillarOrder = isAdminUser ? PILLAR_ORDER : SETUP_SELECTABLE_PILLAR_ORDER;
  const modalOverlayOpen = (BIOMETRICS_ENABLED && biometricsModalOpen) || Boolean(selectedPillarKey);
  const homeDockButtonClassName =
    "flex h-[3.75rem] min-w-0 flex-col items-center justify-center gap-0.5 rounded-[22px] border px-1.5 py-1.5 text-center transition focus:outline-none focus-visible:ring-2 focus-visible:ring-black focus-visible:ring-offset-2";
  const homeDockButtonStyleInactive =
    displayTheme === "dark"
      ? {
          backgroundColor: "var(--surface-soft)",
          borderColor: "var(--border)",
          color: "var(--text-primary)",
        }
      : {
          backgroundColor: "#fffdf9",
          borderColor: "#efe7db",
          color: "#000000",
        };
  const homeDockButtonStyleActive =
    displayTheme === "dark"
      ? {
          backgroundColor: "var(--surface-muted)",
          borderColor: "var(--border-strong)",
          color: "var(--text-primary)",
        }
      : {
          backgroundColor: "#ececec",
          borderColor: "#d9d0c3",
          color: "#000000",
        };

  const pillars = sortPillars(Array.isArray(summary.pillars) ? summary.pillars : []);
  const visiblePillars = useMemo(
    () => pillars,
    [pillars],
  );
  const streakTodayIso = String(summary.today || "").trim() || formatIsoLocalDay(new Date());
  const currentStreakDays = Number.isFinite(Number(initialInteractionDaysCount))
    ? Math.max(0, Math.round(Number(initialInteractionDaysCount)))
    : 0;
  const streakCompletedDateSet = useMemo(() => {
    const dates = new Set<string>(collectTrackerCompletionDates(summary));
    const anchor = parseIsoLocalDay(streakTodayIso);
    if (anchor && currentStreakDays > 0) {
      for (let index = 0; index < currentStreakDays; index += 1) {
        dates.add(formatIsoLocalDay(addLocalDays(anchor, -index)));
      }
    }
    return dates;
  }, [currentStreakDays, streakTodayIso, summary]);
  const streakCalendarDays = useMemo(
    () => buildStreakCalendarDays(streakCalendarMonth, streakTodayIso),
    [streakCalendarMonth, streakTodayIso],
  );
  const streakMonthLabel = formatStreakMonthLabel(streakCalendarMonth);
  const pillarCueCardStyle =
    displayTheme === "dark"
      ? {
          backgroundColor: "var(--surface)",
          color: "var(--text-primary)",
        }
      : {
          backgroundColor: "#ffffff",
          color: "#181512",
        };
  const concepts = Array.isArray(detail?.concepts) ? detail?.concepts : [];
  const canSave =
    !saving &&
    concepts.length > 0 &&
    concepts.every((concept) => {
      const conceptKey = String(concept.concept_key || "").trim();
      return conceptKey && Number.isFinite(Number(draft[conceptKey]));
    });
  const activeDate = String(detail?.pillar?.active_date || detail?.pillar?.today || "").trim();
  const activeLabel = String(detail?.pillar?.active_label || "").trim();
  const currentDate = String(detail?.pillar?.current_date || "").trim();
  const savingPastDay = Boolean(activeDate && currentDate && activeDate !== currentDate);
  const viewingCurrentWeek = detail?.pillar?.is_current_week !== false;
  const canEditActiveWeek = detail?.pillar?.is_editable !== false;
  const trackerScoreLabel =
    detail?.pillar?.tracker_score !== null && detail?.pillar?.tracker_score !== undefined
      ? `${detail?.pillar?.tracker_score}/100 ${viewingCurrentWeek ? "this week so far" : "last week"}`
      : viewingCurrentWeek
        ? savingPastDay
          ? `Complete ${activeLabel || "yesterday"} to update this week's score`
          : "Complete today to start this week's score"
        : "No completed tracker days last week";
  const trackerPillarKey = String(detail?.pillar?.pillar_key || selectedPillarKey || "").trim().toLowerCase();
  const wellbeingObjectiveItems = useMemo(
    () => (Array.isArray(weeklyObjectives?.wellbeing?.items) ? weeklyObjectives.wellbeing.items : []),
    [weeklyObjectives],
  );
  const wellbeingObjectiveItemsByPillar = useMemo(() => {
    const grouped: Partial<Record<ObjectivesSectionKey, WeeklyObjectiveWellbeingItem[]>> = {};
    wellbeingObjectiveItems.forEach((item) => {
      const pillarKey = getWellbeingObjectivePillarKey(item);
      if (!pillarKey) return;
      grouped[pillarKey] = [...(grouped[pillarKey] || []), item];
    });
    return grouped;
  }, [wellbeingObjectiveItems]);
  const objectivesSections = useMemo(
    () =>
      (Array.isArray(weeklyObjectives?.sections) ? weeklyObjectives.sections : [])
        .filter((section) => String(section?.key || "").trim().toLowerCase() !== "wellbeing")
        .map((section) => {
          const sectionKey = String(section?.key || "").trim().toLowerCase() as ObjectivesSectionKey;
          const movedItems = wellbeingObjectiveItemsByPillar[sectionKey] || [];
          if (!movedItems.length) return section;
          const configuredCount = Number(section?.configured_count);
          const totalCount = Number(section?.total_count);
          return {
            ...section,
            configured_count:
              (Number.isFinite(configuredCount) ? configuredCount : 0) +
              movedItems.filter((item) => isWellbeingObjectiveConfigured(item, wellbeingObjectiveDraft)).length,
            total_count: (Number.isFinite(totalCount) ? totalCount : 0) + movedItems.length,
          };
        }),
    [weeklyObjectives, wellbeingObjectiveDraft, wellbeingObjectiveItemsByPillar],
  );
  const selectedObjectivesPillar = useMemo(
    () =>
      Array.isArray(weeklyObjectives?.pillars) && selectedObjectivesSection && selectedObjectivesSection !== "wellbeing"
        ? (weeklyObjectives.pillars.find(
            (pillar) => String(pillar.pillar_key || "").trim().toLowerCase() === selectedObjectivesSection,
          ) as WeeklyObjectivePillarConfig | undefined)
        : undefined,
    [selectedObjectivesSection, weeklyObjectives],
  );
  const selectedPillarObjectiveDraft = useMemo(
    () =>
      selectedObjectivesSection && selectedObjectivesSection !== "wellbeing"
        ? pillarObjectiveDrafts[selectedObjectivesSection] || {}
        : {},
    [pillarObjectiveDrafts, selectedObjectivesSection],
  );
  const selectedPillarWellbeingItems = useMemo(
    () => (selectedObjectivesSection ? wellbeingObjectiveItemsByPillar[selectedObjectivesSection] || [] : []),
    [selectedObjectivesSection, wellbeingObjectiveItemsByPillar],
  );
  const ketogenicDietActive = useMemo(
    () =>
      wellbeingObjectiveItems.some(
        (item) =>
          String(item?.key || "").trim().toLowerCase() === "ketogenic_diet" &&
          String(item?.value || "").trim().toLowerCase() === "on",
      ),
    [wellbeingObjectiveItems],
  );
  const appleHealthSupported = BIOMETRICS_ENABLED && canUseAppleHealth();
  const biometricSourceRows = useMemo(
    () => normalizeBiometricSourceRows(restingHeartRate?.biometric_sources),
    [restingHeartRate?.biometric_sources],
  );
  const biometricSourceEnabled = useMemo(
    () =>
      Object.fromEntries(
        biometricSourceRows.map(({ key, source }) => [key, source?.enabled !== false]),
      ) as Record<BiometricMetricKey, boolean>,
    [biometricSourceRows],
  );
  const showRestingHeartRateMetric = biometricSourceEnabled.resting_hr;
  const showHrvMetric = biometricSourceEnabled.hrv;
  const showStepsMetric = biometricSourceEnabled.steps;
  const showActiveMinutesMetric = biometricSourceEnabled.exercise_minutes;
  const showTrainingReadinessCard = showRestingHeartRateMetric || showHrvMetric;
  const showActivityStatusCard = showStepsMetric || showActiveMinutesMetric;
  const restingHeartRateValue = resolveRestingHeartRateValue(restingHeartRate?.resting_hr_bpm);
  const latestHrvMetricDate = String(restingHeartRate?.hrv_metric_date || "").trim();
  const latestActiveMinutesMetricDate = String(restingHeartRate?.active_minutes_metric_date || "").trim();
  const latestStepsMetricDate = String(restingHeartRate?.steps_metric_date || "").trim();
  const latestActivityMetricDate = String(restingHeartRate?.activity_metric_date || "").trim();
  const restingHeartRateHistory = useMemo(
    () =>
      Array.isArray(restingHeartRate?.history)
        ? restingHeartRate.history.filter(
            (item) =>
              Boolean(String(item?.metric_date || "").trim()) &&
              Number.isFinite(Number(item?.resting_hr_bpm)),
          )
        : [],
    [restingHeartRate?.history],
  );
  const heartRateVariabilityHistory = useMemo(
    () =>
      Array.isArray(restingHeartRate?.hrv_history)
        ? restingHeartRate.hrv_history.filter(
            (item) =>
              Boolean(String(item?.metric_date || "").trim()) &&
              Number.isFinite(Number(item?.hrv_ms)),
          )
        : [],
    [restingHeartRate?.hrv_history],
  );
  const stepsHistory = useMemo(
    () =>
      Array.isArray(restingHeartRate?.steps_history)
        ? restingHeartRate.steps_history.filter(
            (item) =>
              Boolean(String(item?.metric_date || "").trim()) &&
              Number.isFinite(Number(item?.steps)) &&
              Number(item?.steps) >= 0,
          )
        : [],
    [restingHeartRate?.steps_history],
  );
  const activeMinutesHistory = useMemo(
    () =>
      Array.isArray(restingHeartRate?.active_minutes_history)
        ? restingHeartRate.active_minutes_history.filter(
            (item) =>
              Boolean(String(item?.metric_date || "").trim()) &&
              Number.isFinite(Number(item?.active_minutes)) &&
              Number(item?.active_minutes) >= 0,
          )
        : [],
    [restingHeartRate?.active_minutes_history],
  );
  const trainingReadinessHistory = useMemo(
    () =>
      Array.isArray(restingHeartRate?.training_readiness_history)
        ? restingHeartRate.training_readiness_history.filter((item) =>
            Boolean(String(item?.metric_date || "").trim()),
          )
        : [],
    [restingHeartRate?.training_readiness_history],
  );
  const activityStatusHistory = useMemo(
    () =>
      Array.isArray(restingHeartRate?.activity_status_history)
        ? restingHeartRate.activity_status_history.filter((item) =>
            Boolean(String(item?.metric_date || "").trim()),
          )
        : [],
    [restingHeartRate?.activity_status_history],
  );
  const readinessActivityHistory = useMemo(
    () =>
      Array.isArray(restingHeartRate?.readiness_activity_history)
        ? restingHeartRate.readiness_activity_history.filter((item) =>
            Boolean(String(item?.metric_date || "").trim()),
          )
        : [],
    [restingHeartRate?.readiness_activity_history],
  );
  const resolvedLatestHrvMetricDate = useMemo(() => {
    if (latestHrvMetricDate) return latestHrvMetricDate;
    const latestHrvEntry = [...heartRateVariabilityHistory]
      .sort((left, right) => String(right?.metric_date || "").localeCompare(String(left?.metric_date || "")))[0];
    return String(latestHrvEntry?.metric_date || "").trim();
  }, [heartRateVariabilityHistory, latestHrvMetricDate]);
  const resolvedLatestStepsMetricDate = useMemo(() => {
    if (latestStepsMetricDate) return latestStepsMetricDate;
    const latestStepEntry = [...stepsHistory]
      .sort((left, right) => String(right?.metric_date || "").localeCompare(String(left?.metric_date || "")))[0];
    return String(latestStepEntry?.metric_date || "").trim();
  }, [latestStepsMetricDate, stepsHistory]);
  const resolvedLatestActiveMinutesMetricDate = useMemo(() => {
    if (latestActiveMinutesMetricDate) return latestActiveMinutesMetricDate;
    const latestActiveMinutesEntry = [...activeMinutesHistory]
      .sort((left, right) => String(right?.metric_date || "").localeCompare(String(left?.metric_date || "")))[0];
    return String(latestActiveMinutesEntry?.metric_date || "").trim();
  }, [activeMinutesHistory, latestActiveMinutesMetricDate]);
  const resolvedStatusWeekEndDate = useMemo(() => {
    const latestTrainingReadinessEntry = [...trainingReadinessHistory]
      .sort((left, right) => String(right?.metric_date || "").localeCompare(String(left?.metric_date || "")))[0];
    const latestActivityEntry = [...activityStatusHistory]
      .sort((left, right) => String(right?.metric_date || "").localeCompare(String(left?.metric_date || "")))[0];
    return resolveBiometricEndDay(
      String(latestTrainingReadinessEntry?.metric_date || "").trim(),
      latestActivityMetricDate,
      String(latestActivityEntry?.metric_date || "").trim(),
      restingHeartRate?.metric_date,
      latestHrvMetricDate,
    );
  }, [
    activityStatusHistory,
    latestActivityMetricDate,
    latestHrvMetricDate,
    restingHeartRate?.metric_date,
    trainingReadinessHistory,
  ]);
  const trainingReadinessWeek = useMemo(
    () => buildBiometricWeek(trainingReadinessHistory, resolvedStatusWeekEndDate),
    [resolvedStatusWeekEndDate, trainingReadinessHistory],
  );
  const activityStatusWeek = useMemo(
    () => buildBiometricWeek(activityStatusHistory, resolvedStatusWeekEndDate),
    [activityStatusHistory, resolvedStatusWeekEndDate],
  );
  const readinessActivityWeek = useMemo(
    () => buildBiometricWeek(readinessActivityHistory, resolvedStatusWeekEndDate),
    [readinessActivityHistory, resolvedStatusWeekEndDate],
  );
  const restingHeartRateWeek = useMemo(
    () => buildBiometricWeek(restingHeartRateHistory, resolvedStatusWeekEndDate),
    [resolvedStatusWeekEndDate, restingHeartRateHistory],
  );
  const heartRateVariabilityWeek = useMemo(
    () => buildBiometricWeek(heartRateVariabilityHistory, resolvedStatusWeekEndDate),
    [heartRateVariabilityHistory, resolvedStatusWeekEndDate],
  );
  const activeMinutesWeek = useMemo(
    () => buildBiometricWeek(activeMinutesHistory, resolvedStatusWeekEndDate),
    [activeMinutesHistory, resolvedStatusWeekEndDate],
  );
  const stepsWeek = useMemo(
    () => buildBiometricWeek(stepsHistory, resolvedStatusWeekEndDate),
    [resolvedStatusWeekEndDate, stepsHistory],
  );
  const latestHrvItem = useMemo(
    () =>
      heartRateVariabilityHistory.find(
        (item) => String(item?.metric_date || "").trim() === resolvedLatestHrvMetricDate,
      ) ||
      [...heartRateVariabilityHistory]
        .sort((left, right) => String(right?.metric_date || "").localeCompare(String(left?.metric_date || "")))[0] ||
      null,
    [heartRateVariabilityHistory, resolvedLatestHrvMetricDate],
  );
  const latestActiveMinutesItem = useMemo(
    () =>
      activeMinutesHistory.find(
        (item) => String(item?.metric_date || "").trim() === resolvedLatestActiveMinutesMetricDate,
      ) ||
      [...activeMinutesHistory]
        .sort((left, right) => String(right?.metric_date || "").localeCompare(String(left?.metric_date || "")))[0] ||
      null,
    [activeMinutesHistory, resolvedLatestActiveMinutesMetricDate],
  );
  const latestStepsItem = useMemo(
    () =>
      stepsHistory.find(
        (item) => String(item?.metric_date || "").trim() === resolvedLatestStepsMetricDate,
      ) ||
      [...stepsHistory]
        .sort((left, right) => String(right?.metric_date || "").localeCompare(String(left?.metric_date || "")))[0] ||
      null,
    [resolvedLatestStepsMetricDate, stepsHistory],
  );
  const latestTrainingReadinessItem = useMemo(
    () =>
      trainingReadinessHistory.find(
        (item) => String(item?.metric_date || "").trim() === resolvedStatusWeekEndDate,
      ) ||
      [...trainingReadinessHistory]
        .sort((left, right) => String(right?.metric_date || "").localeCompare(String(left?.metric_date || "")))[0] ||
      null,
    [resolvedStatusWeekEndDate, trainingReadinessHistory],
  );
  const latestActivityStatusItem = useMemo(
    () =>
      activityStatusHistory.find(
        (item) => String(item?.metric_date || "").trim() === resolvedStatusWeekEndDate,
      ) ||
      [...activityStatusHistory]
        .sort((left, right) => String(right?.metric_date || "").localeCompare(String(left?.metric_date || "")))[0] ||
      null,
    [activityStatusHistory, resolvedStatusWeekEndDate],
  );
  const latestReadinessActivityItem = useMemo(
    () =>
      readinessActivityHistory.find(
        (item) => String(item?.metric_date || "").trim() === resolvedStatusWeekEndDate,
      ) ||
      [...readinessActivityHistory]
        .sort((left, right) => String(right?.metric_date || "").localeCompare(String(left?.metric_date || "")))[0] ||
      null,
    [readinessActivityHistory, resolvedStatusWeekEndDate],
  );
  const restingHeartRateBoxToneClassName = resolveRestingHeartRateBoxTone(displayTheme);
  const normalizedTrainingReadinessStatus = normalizeTrainingReadinessStatus(
    latestTrainingReadinessItem?.status || restingHeartRate?.training_readiness_status,
  );
  const trainingReadinessStatus =
    normalizedTrainingReadinessStatus !== "unknown"
      ? normalizedTrainingReadinessStatus
      : resolveTrainingReadinessStatus(
          latestHrvItem?.trend_status || restingHeartRate?.hrv_trend_status,
          restingHeartRate?.trend_status,
        );
  const normalizedActivityStatus = normalizeActivityStatus(
    latestActivityStatusItem?.status || latestReadinessActivityItem?.activity_status || restingHeartRate?.activity_status,
  );
  const activityStatus =
    normalizedActivityStatus !== "unknown"
      ? normalizedActivityStatus
      : resolveActivityStatus({
          steps: latestStepsItem?.steps ?? restingHeartRate?.steps_today,
          active_minutes: latestActiveMinutesItem?.active_minutes ?? restingHeartRate?.active_minutes_today,
        });
  const normalizedActivityAlignmentStatus = normalizeActivityAlignmentStatus(
    latestReadinessActivityItem?.alignment_status || restingHeartRate?.activity_alignment_status,
  );
  const activityAlignmentStatus =
    normalizedActivityAlignmentStatus !== "unknown"
      ? normalizedActivityAlignmentStatus
      : resolveActivityAlignmentStatusFromLevels(trainingReadinessStatus, activityStatus);
  const urineMarkers = useMemo(
    () => normalizeUrineMarkers(urineTest?.markers),
    [urineTest?.markers],
  );
  const urineGlucoseRaised = useMemo(
    () =>
      urineMarkers.some(
        (marker) =>
          String(marker?.key || "").trim().toLowerCase() === "glucose" &&
          formatUrineStatusLabel(marker) === "raised",
      ),
    [urineMarkers],
  );
  const urineTestDayMonth = useMemo(() => formatUrineTestDayMonth(urineTest), [urineTest]);
  const urineTestHeadingDate = `${urineTestDayMonth.day}${urineTestDayMonth.month ? ` ${urineTestDayMonth.month}` : ""}`;
  const urineResultMessage = useMemo(() => resolveUrineResultMessage(urineTest), [urineTest]);
  const urineTestStatus = String(urineTest?.status || "").trim().toLowerCase();
  const savedUrineCaptureMs = parseTimestampMs(urineTest?.captured_at);
  const latestUrineCaptureMs = Math.max(
    ...[urinePhotoCapturedAtMs, savedUrineCaptureMs].filter(
      (value): value is number => typeof value === "number" && Number.isFinite(value),
    ),
  );
  const hasRecentUrineCapture =
    Number.isFinite(latestUrineCaptureMs) &&
    urineCaptureNowMs - latestUrineCaptureMs >= -60000 &&
    urineCaptureNowMs - latestUrineCaptureMs <= URINE_RECENT_CAPTURE_WINDOW_MS;
  let urineCaptureState: UrineCaptureState = "ready";
  if (urineTestError) {
    urineCaptureState = "error";
  } else if (urineTestSaving) {
    urineCaptureState = "saving";
  } else if (urineTestStatus === "analysed") {
    urineCaptureState = "analysed";
  } else if (urineTestStatus === "needs_review") {
    urineCaptureState = "review";
  } else if (urinePhotoCapturedAt || urineTest?.available) {
    urineCaptureState = "queued";
  } else if (urineCaptureStartedAt) {
    urineCaptureState = "timing";
  }
  const urineCaptureToneClassName = resolveUrineCaptureTone(displayTheme, urineCaptureState);
  const biomarkerExplanationButtonClassName =
    "rounded-full border border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-[10px] font-semibold uppercase tracking-[0.14em] text-[var(--text-secondary)]";
  const biometricSourceCheckButtonClassName =
    "shrink-0 rounded-full border border-[var(--accent)] bg-[var(--accent)] px-3 py-2 text-xs font-semibold uppercase tracking-[0.16em] text-white shadow-[0_10px_24px_-18px_var(--shadow-strong)]";
  const biometricAboutButtonClassName =
    displayTheme === "dark"
      ? "border-[#2f3542] bg-[#1c2230] text-white shadow-[0_10px_24px_-18px_rgba(12,18,28,0.9)]"
      : "border-[var(--border)] bg-[var(--surface)] text-[var(--text-secondary)] shadow-[0_10px_24px_-18px_rgba(93,83,72,0.45)]";
  const biometricAboutPanelClassName =
    displayTheme === "dark"
      ? "border-[var(--border)] bg-[#151a24] text-[var(--text-secondary)]"
      : "border-[var(--border)] bg-[#fffaf3] text-[var(--text-secondary)]";
  const latestHrvValue = resolveHeartRateVariabilityValue(latestHrvItem?.hrv_ms);
  const latestActiveMinutesValue = formatFullActiveMinutes(latestActiveMinutesItem?.active_minutes);
  const latestActiveMinutesStatus = resolveActiveMinutesStatus(latestActiveMinutesItem?.active_minutes);
  const latestStepsValue = formatFullStepCount(latestStepsItem?.steps);
  const latestStepsStatus = resolveStepsStatus(latestStepsItem?.steps);
  const trainingReadinessSignalSummary =
    latestHrvValue && restingHeartRateValue
      ? `This combines HRV ${latestHrvValue} ms and Resting HR ${restingHeartRateValue} bpm against your recent 7-14 day baseline.`
      : restingHeartRateValue
        ? `This is based on Resting HR ${restingHeartRateValue} bpm against your recent 7-14 day baseline.`
        : latestHrvValue
          ? `This is based on HRV ${latestHrvValue} ms against your recent 7-14 day baseline.`
          : "Once HRV or Resting HR syncs, this section compares recovery capacity with activity status.";
  const rhrExplanationResult = restingHeartRateValue
    ? `Latest result: ${restingHeartRateValue} bpm, currently shown as ${resolveRestingHeartRateTrendLabel(restingHeartRate?.trend_label)}. Resting HR is compared with your own 7-14 day baseline; lower than your usual range often suggests better recovery, while elevated can reflect stress, illness, poor sleep, dehydration, alcohol, or training load.`
    : "Latest result: no current Resting HR is available yet. Once Apple Health syncs enough readings, this section will compare it with your recent 7-14 day baseline.";
  const hrvExplanationResult = latestHrvValue
    ? `Latest result: ${latestHrvValue} ms, currently shown as ${resolveRestingHeartRateTrendLabel(latestHrvItem?.trend_label || restingHeartRate?.hrv_trend_label)}. HRV is compared with your own 7-14 day baseline; higher than your recent pattern usually suggests better recovery, while a suppressed reading can reflect stress, illness, poor sleep, alcohol, dehydration, or training load.`
    : "Latest result: no current HRV is available yet. Once Apple Health syncs enough readings, this section will compare HRV with your recent 7-14 day baseline.";
  const activeMinutesExplanationResult = latestActiveMinutesValue
    ? `Latest result: ${latestActiveMinutesValue} minutes, currently shown as ${resolveActiveMinutesStatusDescription(latestActiveMinutesStatus)}. Exercise minutes come from Apple Health Exercise Time.`
    : "Latest result: no recent exercise minutes are available yet. Once Apple Health syncs Exercise Time, this section shows daily training minutes.";
  const stepsExplanationResult = latestStepsValue
    ? `Latest result: ${latestStepsValue} steps, currently shown as ${resolveStepsStatusDescription(latestStepsStatus)}. Steps are a movement-volume marker; they help show whether the day included enough basic activity, independent of formal training.`
    : "Latest result: no recent step count is available yet. Once steps sync, this section shows your daily movement volume.";
  const trainingReadinessExplanationResult =
    trainingReadinessStatus !== "unknown"
      ? `Latest status: ${resolveTrainingReadinessLabel(trainingReadinessStatus)}. ${resolveTrainingReadinessAction(trainingReadinessStatus)}. ${trainingReadinessSignalSummary}`
      : `Latest status: no current training readiness is available yet. ${trainingReadinessSignalSummary}`;
  const activityStatusExplanationResult =
    activityStatus !== "unknown"
      ? `Latest status: ${resolveActivityStatusLabel(activityStatus)}. ${resolveActivityAlignmentLabel(activityAlignmentStatus)}. This combines ${latestStepsValue ? `${latestStepsValue} steps` : "no step count"} and ${latestActiveMinutesValue ? `${latestActiveMinutesValue} exercise minutes` : "no exercise minutes"} so Gia can compare activity load with readiness.`
      : "Latest status: no current activity status is available yet. Once steps or exercise minutes sync, this section compares activity load with training readiness.";
  const urineStatusSummary = urineMarkers
    .map((marker) => `${marker.label}: ${formatUrineExplanationStatusLabel(marker)}`)
    .join("; ");
  const urineExplanationResult = urineTest?.available
    ? `Latest result: ${urineStatusSummary}. Use this as a quick screening and trend check; if a result looks unexpected, retake the strip in good light at the 60-second point.`
    : "Latest result: no urine test has been completed yet. Press Test to take a sample and populate these markers.";
  const trainingReadinessExplanationScaleRows: BiomarkerExplanationScaleRow[] = [
    {
      marker: "Readiness",
      status: "Ready",
      tone: "green",
      meaning: "HRV is above normal and Resting HR is at or below normal. Push intensity if the plan calls for it.",
    },
    {
      marker: "Readiness",
      status: "Moderate",
      tone: "amber",
      meaning: "One recovery signal is slightly off or mixed. Train, but control intensity.",
    },
    {
      marker: "Readiness",
      status: "Low",
      tone: "purple",
      meaning: "HRV is down and Resting HR is elevated. Recover or avoid intensity.",
    },
  ];
  const activityStatusExplanationScaleRows: BiomarkerExplanationScaleRow[] = [
    {
      marker: "Activity",
      status: "High",
      tone: "purple",
      meaning: "30+ exercise minutes or 10,000+ steps. A high activity load for the day.",
    },
    {
      marker: "Activity",
      status: "Moderate",
      tone: "green",
      meaning: "20-29 exercise minutes or 7,500-9,999 steps. A controlled activity load.",
    },
    {
      marker: "Activity",
      status: "Low",
      tone: "amber",
      meaning: `Below moderate activity. Steps are currently ${resolveStepsStatusDescription(latestStepsStatus)} and exercise minutes are ${resolveActiveMinutesStatusDescription(latestActiveMinutesStatus)}.`,
    },
  ];
  const rhrExplanationScaleRows: BiomarkerExplanationScaleRow[] = [
    {
      marker: "Resting HR",
      status: "Optimum",
      tone: "purple",
      meaning: "Lower than your recent 7-14 day pattern, which usually suggests recovery/load is moving in the right direction.",
    },
    {
      marker: "Resting HR",
      status: "Normal",
      tone: "green",
      meaning: "Broadly in your expected recent range.",
    },
    {
      marker: "Resting HR",
      status: "Elevated",
      tone: "amber",
      meaning: "Higher than usual; consider sleep, stress, hydration, illness, alcohol, or training load.",
    },
  ];
  const hrvExplanationScaleRows: BiomarkerExplanationScaleRow[] = [
    {
      marker: "HRV",
      status: "Optimum",
      tone: "purple",
      meaning: "Higher than your recent 7-14 day pattern, which usually suggests recovery is moving in the right direction.",
    },
    {
      marker: "HRV",
      status: "Normal",
      tone: "green",
      meaning: "Broadly in your expected recent range.",
    },
    {
      marker: "HRV",
      status: "Suppressed",
      tone: "amber",
      meaning: "Lower than usual; consider sleep, stress, hydration, illness, alcohol, or training load.",
    },
  ];
  const activeMinutesExplanationScaleRows: BiomarkerExplanationScaleRow[] = [
    {
      marker: "Exercise minutes",
      status: "Optimal",
      tone: "purple",
      meaning: "30+ minutes; strong deliberate training volume for the day.",
    },
    {
      marker: "Exercise minutes",
      status: "Strong",
      tone: "green",
      meaning: "20-29 minutes; a solid training or conditioning day.",
    },
    {
      marker: "Exercise minutes",
      status: "Base",
      tone: "amber",
      meaning: "10-19 minutes; some useful higher-effort movement.",
    },
    {
      marker: "Exercise minutes",
      status: "Below",
      tone: "neutral",
      meaning: "Below 10 minutes; useful context for training consistency rather than a score by itself.",
    },
  ];
  const stepsExplanationScaleRows: BiomarkerExplanationScaleRow[] = [
    {
      marker: "Steps",
      status: "Optimal",
      tone: "purple",
      meaning: "10,000+ steps; strong daily movement volume.",
    },
    {
      marker: "Steps",
      status: "Strong",
      tone: "green",
      meaning: "7,500-9,999 steps; a solid active day.",
    },
    {
      marker: "Steps",
      status: "Base",
      tone: "amber",
      meaning: "5,000-7,499 steps; enough to show movement, but still a lower activity day.",
    },
    {
      marker: "Steps",
      status: "Below",
      tone: "neutral",
      meaning: "Below 5,000 steps; useful context for energy, recovery, and routine rather than a score by itself.",
    },
  ];
  const urineExplanationScaleRows: BiomarkerExplanationScaleRow[] = [
    {
      marker: "Hydration",
      status: "Well",
      tone: "purple",
      dotClassName: urineStatusDot(displayTheme, "concentration", "well"),
      meaning: "Dilute urine, usually consistent with good recent fluid intake.",
    },
    {
      marker: "Hydration",
      status: "OK",
      tone: "green",
      dotClassName: urineStatusDot(displayTheme, "concentration", "ok"),
      meaning: "Typical urine concentration; hydration looks acceptable.",
    },
    {
      marker: "Hydration",
      status: "Low",
      tone: "amber",
      dotClassName: urineStatusDot(displayTheme, "concentration", "low"),
      meaning: "More concentrated urine; often suggests lower fluid intake or higher fluid loss.",
    },
    {
      marker: "UTI Signs",
      status: "Clear",
      tone: "green",
      dotClassName: urineStatusDot(displayTheme, "uti", "clear"),
      meaning: "No leukocyte/nitrite signal detected on the strip.",
    },
    {
      marker: "UTI Signs",
      status: "Watch",
      tone: "amber",
      dotClassName: urineStatusDot(displayTheme, "uti", "watch"),
      meaning: "A small leukocyte-type signal; retest and consider symptoms such as burning, urgency, or frequency.",
    },
    {
      marker: "UTI Signs",
      status: "Flagged",
      tone: "red",
      dotClassName: urineStatusDot(displayTheme, "uti", "flagged"),
      meaning: "Nitrite or stronger leukocyte signal; more relevant if symptoms are present or if repeated.",
    },
    {
      marker: "Protein",
      status: "Clear",
      tone: "green",
      dotClassName: urineStatusDot(displayTheme, "protein", "clear"),
      meaning: "No protein signal detected.",
    },
    {
      marker: "Protein",
      status: "Trace",
      tone: "amber",
      dotClassName: urineStatusDot(displayTheme, "protein", "trace"),
      meaning: "Small protein signal; can be temporary after exercise, dehydration, or illness.",
    },
    {
      marker: "Protein",
      status: "Flagged",
      tone: "red",
      dotClassName: urineStatusDot(displayTheme, "protein", "flagged"),
      meaning: "Protein signal present; more important if it repeats across tests.",
    },
    {
      marker: "Blood",
      status: "Clear",
      tone: "green",
      dotClassName: urineStatusDot(displayTheme, "blood", "clear"),
      meaning: "No blood signal detected.",
    },
    {
      marker: "Blood",
      status: "Trace",
      tone: "amber",
      dotClassName: urineStatusDot(displayTheme, "blood", "trace"),
      meaning: "Small blood signal; can be affected by exercise, contamination, or timing.",
    },
    {
      marker: "Blood",
      status: "Flagged",
      tone: "red",
      dotClassName: urineStatusDot(displayTheme, "blood", "flagged"),
      meaning: "Blood signal present; repeat and consider symptoms or persistence.",
    },
    {
      marker: "Glucose",
      status: "Clear",
      tone: "green",
      dotClassName: urineStatusDot(displayTheme, "glucose", "clear"),
      meaning: "No glucose signal detected.",
    },
    {
      marker: "Glucose",
      status: "Raised",
      tone: "red",
      dotClassName: urineStatusDot(displayTheme, "glucose", "raised"),
      meaning: "Glucose detected in urine; retest and consider recent food, diabetes risk, or symptoms.",
    },
    {
      marker: "Ketones",
      status: "Clear",
      tone: ketogenicDietActive ? "amber" : "green",
      dotClassName: urineStatusDot(displayTheme, "ketones", "clear", { ketogenicDietActive }),
      meaning: ketogenicDietActive
        ? "No ketone signal; less expected if actively following a keto/low-carb objective."
        : "No ketone signal detected.",
    },
    {
      marker: "Ketones",
      status: "Trace",
      tone: ketogenicDietActive ? "green" : "amber",
      dotClassName: urineStatusDot(displayTheme, "ketones", "trace", { ketogenicDietActive }),
      meaning: ketogenicDietActive
        ? "Small ketone signal, consistent with a keto/low-carb objective."
        : "Small ketone signal; can appear with fasting, low intake, heavy exercise, or illness.",
    },
    {
      marker: "Ketones",
      status: "Raised",
      tone: ketogenicDietActive ? "purple" : "red",
      dotClassName: urineStatusDot(displayTheme, "ketones", "raised", { ketogenicDietActive }),
      meaning: ketogenicDietActive
        ? "Higher ketone signal can fit a keto/low-carb objective; if glucose is also raised, HealthSense shows this as red."
        : "Higher ketone signal; more important when unexpected, repeated, or paired with raised glucose.",
    },
    {
      marker: "Ketones + glucose",
      status: "Flagged",
      tone: "red",
      dotClassName: urineStatusDot(displayTheme, "ketones", "raised", {
        glucoseRaised: true,
        ketogenicDietActive,
      }),
      meaning: "Raised glucose with trace or raised ketones is shown as red because the combination needs more attention than ketones alone.",
    },
  ];
  const activeBiomarkerExplanationDetail =
    activeBiomarkerExplanation === "training_readiness"
      ? {
          title: "Training readiness",
          description: "Training readiness combines HRV and Resting HR against your own recent baseline so intensity can match recovery capacity.",
          result: trainingReadinessExplanationResult,
          scaleRows: trainingReadinessExplanationScaleRows,
          showMarkerColumn: false,
        }
      : activeBiomarkerExplanation === "rhr"
        ? {
            title: "Resting HR",
            description: "Resting HR is your heart rate at rest. HealthSense compares it with your own recent 7-14 day baseline rather than using one fixed target.",
            result: rhrExplanationResult,
            scaleRows: rhrExplanationScaleRows,
            showMarkerColumn: false,
          }
      : activeBiomarkerExplanation === "hrv"
        ? {
            title: "HRV",
            description: "HRV is heart rate variability, measured in milliseconds. HealthSense compares it with your own recent 7-14 day baseline rather than using one fixed target.",
            result: hrvExplanationResult,
            scaleRows: hrvExplanationScaleRows,
            showMarkerColumn: false,
          }
      : activeBiomarkerExplanation === "activity_status"
        ? {
            title: "Activity status",
            description: "Activity status combines steps and exercise minutes so daily load can be compared with training readiness.",
            result: activityStatusExplanationResult,
            scaleRows: activityStatusExplanationScaleRows,
            showMarkerColumn: false,
          }
      : activeBiomarkerExplanation === "active_minutes"
        ? {
            title: "Exercise minutes",
            description: "Exercise minutes come from Apple Health Exercise Time. They show higher-effort movement and sit alongside steps as training-volume context.",
            result: activeMinutesExplanationResult,
            scaleRows: activeMinutesExplanationScaleRows,
            showMarkerColumn: false,
          }
      : activeBiomarkerExplanation === "steps"
        ? {
            title: "Steps",
            description: "Steps show daily movement volume. They do not replace training quality, but they are useful context for activity, energy, and routine.",
            result: stepsExplanationResult,
            scaleRows: stepsExplanationScaleRows,
            showMarkerColumn: false,
          }
      : activeBiomarkerExplanation === "urine"
          ? {
              title: "Urine",
              description:
                "Urine uses the strip photo to group six dipstick readings into practical HealthSense markers. Hydration comes from specific gravity; UTI Signs combines leukocytes and nitrite; protein, blood, glucose, and ketones are screening signals that make most sense with context and repeat tests.",
              result: urineExplanationResult,
              scaleRows: urineExplanationScaleRows,
              showMarkerColumn: true,
            }
          : null;

  const refreshSummary = useCallback(async ({
    anchorDate,
    skipQuoteGeneration = false,
  }: { anchorDate?: string | null; skipQuoteGeneration?: boolean } = {}) => {
    const params = new URLSearchParams({ userId });
    const resolvedAnchorDate = String(anchorDate || "").trim();
    if (resolvedAnchorDate) {
      params.set("anchorDate", resolvedAnchorDate);
    }
    params.set("skipQuoteGeneration", skipQuoteGeneration ? "true" : "false");
    const res = await fetch(`/api/pillar-tracker/summary?${params.toString()}`, {
      method: "GET",
      cache: "no-store",
    });
    const text = await res.text().catch(() => "");
    if (!res.ok) {
      throw new Error(normalizeError(text, "Failed to refresh the pillar tracker summary."));
    }
    const payload = (text ? (JSON.parse(text) as PillarTrackerSummaryResponse) : {}) as PillarTrackerSummaryResponse;
    setSummary(payload);
    dispatchPillarTrackerOverallScore(payload);
    return payload;
  }, [userId]);

  const saveAppSetup = useCallback(async () => {
    const selectedKeys = setupSelectablePillarOrder.filter((pillarKey) => setupPillarSelections[pillarKey]);
    if (!selectedKeys.length) {
      setSetupError("Choose at least one pillar to continue.");
      return;
    }
    setSetupSaving(true);
    setSetupError(null);
    try {
      const payload: Record<string, unknown> = {
        userId,
        app_setup_completed: "1",
        preferred_channel: "app",
      };
      PILLAR_ORDER.forEach((pillarKey) => {
        payload[PILLAR_PREF_KEYS[pillarKey]] =
          setupSelectablePillarOrder.includes(pillarKey) && setupPillarSelections[pillarKey] ? "1" : "0";
      });
      const res = await fetch("/api/preferences", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const text = await res.text().catch(() => "");
      if (!res.ok) {
        throw new Error(normalizeError(text, "Failed to save setup."));
      }
      setSummary((current) => ({ ...current, app_setup_completed: true }));
      await refreshSummary({ skipQuoteGeneration: false });
      const objectivesRes = await fetch(`/api/weekly-objectives?userId=${encodeURIComponent(userId)}`, {
        method: "GET",
        cache: "no-store",
      });
      if (objectivesRes.ok) {
        const objectivesText = await objectivesRes.text().catch(() => "");
        const objectivesPayload = (objectivesText ? JSON.parse(objectivesText) : {}) as WeeklyObjectivesResponse;
        const selectedKeySet = new Set(selectedKeys);
        await Promise.all(
          (objectivesPayload.pillars || [])
            .filter((pillar) => selectedKeySet.has(String(pillar?.pillar_key || "").trim().toLowerCase()))
            .map((pillar) => {
              const sectionKey = String(pillar?.pillar_key || "").trim().toLowerCase();
              const conceptTargets = buildDefaultWeeklyObjectiveTargets(pillar);
              const hasTargets = Object.values(conceptTargets).some((value) => Number.isFinite(Number(value)));
              if (!sectionKey || !hasTargets) return Promise.resolve();
              return fetch("/api/weekly-objectives", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                  userId,
                  sectionKey,
                  conceptTargets,
                }),
              }).then(async (targetRes) => {
                if (targetRes.ok) return;
                const targetText = await targetRes.text().catch(() => "");
                throw new Error(normalizeError(targetText, "Failed to save default weekly targets."));
              });
            }),
        );
      }
      setActiveDockKey("checkin");
      setSummaryPanelVisible(true);
      if (typeof window !== "undefined") {
        window.dispatchEvent(
          new CustomEvent("healthsense-home-surface", {
            detail: {
              surface: "blank",
              source: "setup",
            },
          }),
        );
        window.scrollTo({ top: 0, behavior: "smooth" });
      }
    } catch (error) {
      setSetupError(error instanceof Error ? error.message : String(error));
    } finally {
      setSetupSaving(false);
    }
  }, [refreshSummary, setupPillarSelections, setupSelectablePillarOrder, userId]);

  const pillarNeedsGeneratedCue = useCallback((pillar: PillarTrackerPillar | null | undefined) => {
    if (!pillar) return true;
    if (pillar.daily_quote_generated === true) return false;
    if (pillar.daily_quote_pending === true) return true;
    if (pillar.daily_quote_generated === false) return true;
    const quote = String(pillar.daily_quote || "").trim().toLowerCase();
    return !quote || HOME_PILLAR_FALLBACK_QUOTES.has(quote);
  }, []);

  const summaryHasFallbackCueMessages = useCallback((payload: PillarTrackerSummaryResponse | null | undefined) => {
    const pillars = Array.isArray(payload?.pillars) ? payload.pillars : [];
    return pillars.some((pillar) => pillarNeedsGeneratedCue(pillar));
  }, [pillarNeedsGeneratedCue]);

  const scrollToPillarCueCard = useCallback((pillarKey?: string | null, behavior: ScrollBehavior = "smooth") => {
    if (typeof window === "undefined") return;
    const normalizedPillarKey = String(pillarKey || "").trim().toLowerCase();
    if (!normalizedPillarKey) return;
    window.requestAnimationFrame(() => {
      window.requestAnimationFrame(() => {
        const card = pillarCueCardRefs.current[normalizedPillarKey];
        if (!card || typeof card.scrollIntoView !== "function") return;
        card.scrollIntoView({ behavior, block: "nearest", inline: "center" });
      });
    });
  }, []);

  const refreshSummaryFromWorkerCache = useCallback((pillarKey?: string | null, options?: { anchorDate?: string | null; waitForFresh?: boolean }) => {
    if (typeof window === "undefined") return;
    const normalizedPillarKey = String(pillarKey || "").trim().toLowerCase();
    const anchorDate = String(options?.anchorDate || "").trim();
    const waitForFresh = Boolean(options?.waitForFresh && normalizedPillarKey);
    const delays = [1400, 2400, 3600, 5200, 7600, 10400, 14000, 18000];
    let resolved = false;
    delays.forEach((delay) => {
      window.setTimeout(() => {
        if (resolved) return;
        void refreshSummary({ anchorDate, skipQuoteGeneration: true })
          .then((payload) => {
            const pillars = Array.isArray(payload?.pillars) ? payload.pillars : [];
            const targetPillar = normalizedPillarKey
              ? pillars.find((pillar) => String(pillar.pillar_key || "").trim().toLowerCase() === normalizedPillarKey)
              : null;
            if (targetPillar && !pillarNeedsGeneratedCue(targetPillar)) {
              resolved = true;
              return;
            }
            if (waitForFresh) {
              return;
            }
            if (!normalizedPillarKey && !summaryHasFallbackCueMessages(payload)) {
              resolved = true;
            }
          })
          .catch(() => undefined);
      }, delay);
    });
  }, [pillarNeedsGeneratedCue, refreshSummary, summaryHasFallbackCueMessages]);

  useEffect(() => {
    void refreshSummary().catch(() => undefined);
  }, [refreshSummary]);

  const loadRestingHeartRate = useCallback(async () => {
    if (!BIOMETRICS_ENABLED) return null;
    const res = await fetch(`/api/apple-health/resting-heart-rate?userId=${encodeURIComponent(userId)}`, {
      method: "GET",
      cache: "no-store",
    });
    const text = await res.text().catch(() => "");
    if (!res.ok) {
      throw new Error(normalizeError(text, "Failed to load Resting HR."));
    }
    const payload = (text ? (JSON.parse(text) as AppleHealthRestingHeartRateResponse) : {}) as AppleHealthRestingHeartRateResponse;
    setRestingHeartRate(payload);
    return payload;
  }, [userId]);

  const loadLatestUrineTest = useCallback(async () => {
    if (!BIOMETRICS_ENABLED) return null;
    setUrineTestLoading(true);
    setUrineTestError(null);
    try {
      const res = await fetch(`/api/urine-tests?userId=${encodeURIComponent(userId)}`, {
        method: "GET",
        cache: "no-store",
      });
      const text = await res.text().catch(() => "");
      if (!res.ok) {
        throw new Error(normalizeError(text, "Failed to load urine test."));
      }
      const payload = (text ? (JSON.parse(text) as UrineTestResponse) : {}) as UrineTestResponse;
      setUrineTest(payload);
      setUrinePhotoCapturedAtMs(parseTimestampMs(payload?.captured_at));
      return payload;
    } catch (error) {
      setUrineTestError(error instanceof Error ? error.message : String(error));
      return null;
    } finally {
      setUrineTestLoading(false);
    }
  }, [userId]);

  const logUserAppEvent = useCallback(
    (eventType: string, meta?: Record<string, unknown>) => {
      void fetch("/api/engagement", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          userId,
          event_type: eventType,
          surface: "coach_home",
          meta: {
            page: "coach_home",
            ...(meta || {}),
          },
        }),
      }).catch(() => undefined);
    },
    [userId],
  );

  const syncNativeRestingHeartRate = useCallback(
    async (requestAccess = false) => {
      if (!BIOMETRICS_ENABLED || !appleHealthSupported) return null;
      if (requestAccess) {
        setRestingHeartRateEnabling(true);
      } else {
        setRestingHeartRateLoading(true);
      }
      try {
        const auth = requestAccess
          ? await requestAppleHealthAuthorization()
          : await getAppleHealthAuthorizationStatus();
        const status = auth.status || "unsupported";
        setAppleHealthAuthStatus(status);
        if (!auth.available || status !== "authorized") {
          return null;
        }
        const payload = await syncAppleHealthRestingHeartRate(userId, { days: 21 });
        if (payload) {
          setRestingHeartRate(payload);
          return payload;
        }
        return await loadRestingHeartRate().catch(() => null);
      } catch {
        return null;
      } finally {
        setRestingHeartRateLoading(false);
        setRestingHeartRateEnabling(false);
      }
    },
    [appleHealthSupported, loadRestingHeartRate, userId],
  );

  const startUrineCaptureTimer = useCallback(() => {
    if (!BIOMETRICS_ENABLED) return;
    setUrineTestError(null);
    setUrineCaptureStartedAt(Date.now());
    setUrineTimerSecondsLeft(URINE_CAPTURE_TIMER_SECONDS);
  }, []);

  const submitUrinePhotoCapture = useCallback(async ({
    capturedAt,
    fileName,
    imageDataUrl,
    mimeType,
    sizeBytes,
  }: {
    capturedAt: Date;
    fileName: string;
    imageDataUrl: string;
    mimeType: string;
    sizeBytes: number;
  }) => {
    if (!BIOMETRICS_ENABLED) return;
    setUrineTestSaving(true);
    setUrineTestError(null);
    const captureStage = urineCaptureStartedAt ? "timed" : "single";
    try {
      if (sizeBytes > URINE_TEST_MAX_PHOTO_BYTES) {
        throw new Error("Photo is too large. Retake or choose a smaller image.");
      }
      const res = await fetch("/api/urine-tests", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          userId,
          capturedAt: capturedAt.toISOString(),
          captureStage,
          fileName,
          mimeType,
          sizeBytes,
          imageDataUrl,
        }),
      });
      const text = await res.text().catch(() => "");
      if (!res.ok) {
        throw new Error(normalizeError(text, "Failed to save urine test photo."));
      }
      const payload = (text ? (JSON.parse(text) as UrineTestResponse) : {}) as UrineTestResponse;
      setUrineTest(payload);
      setUrinePhotoName(fileName);
      setUrinePhotoCapturedAt(formatCapturedAt(capturedAt));
      setUrinePhotoCapturedAtMs(capturedAt.getTime());
      setUrineCaptureNowMs(Date.now());
      setUrineCaptureStartedAt(null);
      setUrineTimerSecondsLeft(0);
      setActiveBiomarkerExplanation(null);
      setBiometricSourceCheckOpen(false);
      setUrineTestFlowOpen(false);
      setBiometricsModalOpen(true);
      logUserAppEvent("urine_test_capture", {
        captureStage,
        source: "biometrics_modal",
      });
    } catch (error) {
      setUrineTestError(error instanceof Error ? error.message : String(error));
    } finally {
      setUrineTestSaving(false);
    }
  }, [logUserAppEvent, urineCaptureStartedAt, userId]);

  const openUrinePhotoCapture = useCallback(async () => {
    if (!BIOMETRICS_ENABLED) return;
    setUrineTestError(null);
    urinePhotoCameraInputRef.current?.click();
  }, []);

  const openUrinePhotoLibrary = useCallback(async () => {
    if (!BIOMETRICS_ENABLED) return;
    setUrineTestError(null);
    urinePhotoLibraryInputRef.current?.click();
  }, []);

  const handleUrinePhotoSelected = useCallback(async (event: ChangeEvent<HTMLInputElement>) => {
    if (!BIOMETRICS_ENABLED) return;
    const file = event.target.files?.[0];
    if (!file) {
      event.target.value = "";
      return;
    }
    try {
      const capturedAt = new Date();
      const imageDataUrl = await readFileAsDataUrl(file);
      await submitUrinePhotoCapture({
        capturedAt,
        fileName: String(file.name || "urine-sample.jpg").trim() || "urine-sample.jpg",
        imageDataUrl,
        mimeType: String(file.type || "image/jpeg"),
        sizeBytes: file.size,
      });
    } finally {
      event.target.value = "";
    }
  }, [submitUrinePhotoCapture]);

  const applyWeeklyObjectivesPayload = useCallback((payload: WeeklyObjectivesResponse | null) => {
    setWeeklyObjectives(payload);
    const nextPillarDrafts: Record<string, Record<string, number | null>> = {};
    (payload?.pillars || []).forEach((pillar) => {
      const pillarKey = String(pillar?.pillar_key || "").trim().toLowerCase();
      if (!pillarKey) return;
      nextPillarDrafts[pillarKey] = buildDefaultWeeklyObjectiveTargets(pillar);
    });
    setPillarObjectiveDrafts(nextPillarDrafts);
    const nextWellbeingDraft: Record<string, string> = {};
    (payload?.wellbeing?.items || []).forEach((item) => {
      const itemKey = String(item?.key || "").trim();
      if (!itemKey) return;
      nextWellbeingDraft[itemKey] = String(item?.value || "").trim() || "off";
      (item?.fields || []).forEach((field) => {
        const fieldKey = String(field?.key || "").trim();
        if (!fieldKey) return;
        nextWellbeingDraft[fieldKey] = String(field?.value ?? "").trim();
      });
    });
    setWellbeingObjectiveDraft(nextWellbeingDraft);
  }, []);

  const loadWeeklyObjectives = useCallback(async () => {
    setWeeklyObjectivesLoading(true);
    setWeeklyObjectivesError(null);
    try {
      const res = await fetch(`/api/weekly-objectives?userId=${encodeURIComponent(userId)}`, {
        method: "GET",
        cache: "no-store",
      });
      const text = await res.text().catch(() => "");
      if (!res.ok) {
        throw new Error(normalizeError(text, "Failed to load weekly objectives."));
      }
      const payload = (text ? (JSON.parse(text) as WeeklyObjectivesResponse) : {}) as WeeklyObjectivesResponse;
      applyWeeklyObjectivesPayload(payload);
    } catch (error) {
      setWeeklyObjectivesError(error instanceof Error ? error.message : String(error));
    } finally {
      setWeeklyObjectivesLoading(false);
    }
  }, [applyWeeklyObjectivesPayload, userId]);

  const saveBiometricPreference = useCallback(
    async (metricKey: BiometricMetricKey, enabled: boolean) => {
      setBiometricPreferenceSaving(metricKey);
      setBiometricsActionError(null);
      try {
        const res = await fetch("/api/biometrics/preferences", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            userId,
            metrics: {
              [metricKey]: { enabled },
            },
          }),
        });
        const text = await res.text().catch(() => "");
        if (!res.ok) {
          throw new Error(normalizeError(text, "Failed to save biometrics preference."));
        }
        const payload = (text ? (JSON.parse(text) as AppleHealthRestingHeartRateResponse) : {}) as AppleHealthRestingHeartRateResponse;
        setRestingHeartRate(payload);
        logUserAppEvent("biometrics_source_update", { metricKey, enabled });
        await loadWeeklyObjectives().catch(() => undefined);
      } catch (error) {
        setBiometricsActionError(error instanceof Error ? error.message : String(error));
      } finally {
        setBiometricPreferenceSaving(null);
      }
    },
    [loadWeeklyObjectives, logUserAppEvent, userId],
  );

  const startBiometricWearableConnection = useCallback(
    async (provider: string | undefined) => {
      const key = String(provider || "").trim().toLowerCase();
      if (!key) return;
      setWearableConnectPending(key);
      setBiometricsActionError(null);
      try {
        const redirectPath =
          typeof window !== "undefined"
            ? `${window.location.pathname}${window.location.search || ""}`
            : "/";
        const res = await fetch(`/api/wearables/${key}/connect`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            userId,
            redirect_path: redirectPath,
          }),
        });
        const data = (await res.json().catch(() => ({}))) as {
          error?: string;
          message?: string;
          auth_url?: string;
        };
        if (!res.ok) {
          throw new Error(String(data.error || data.message || `Failed to connect ${key}`));
        }
        const authUrl = String(data.auth_url || "").trim();
        if (!authUrl) {
          throw new Error("Connect URL missing from wearable response.");
        }
        window.location.assign(authUrl);
      } catch (error) {
        setBiometricsActionError(error instanceof Error ? error.message : String(error));
      } finally {
        setWearableConnectPending(null);
      }
    },
    [userId],
  );

  const openObjectivesModal = useCallback(async () => {
    setStreakSectionOpen(false);
    setSelectedPillarKey(null);
    setBiometricsModalOpen(false);
    setObjectivesModalOpen(true);
    setSelectedObjectivesSection(null);
    setBiometricsActionError(null);
    logUserAppEvent("weekly_objectives_open", { source: "weekly_targets_card" });
    await loadWeeklyObjectives();
  }, [loadWeeklyObjectives, logUserAppEvent]);

  const closeObjectivesModal = useCallback(() => {
    setObjectivesModalOpen(false);
    setSelectedObjectivesSection(null);
    setWeeklyObjectivesError(null);
    setWeeklyObjectivesSaving(false);
    setBiometricsActionError(null);
  }, []);

  const closeStreakSection = useCallback(() => {
    setStreakSectionOpen(false);
    setActiveDockKey("checkin");
    setSummaryPanelVisible(true);
  }, []);

  const showPreviousStreakMonth = useCallback(() => {
    setStreakCalendarMonth((current) => monthStart(new Date(current.getFullYear(), current.getMonth() - 1, 1, 12, 0, 0, 0)));
  }, []);

  const showNextStreakMonth = useCallback(() => {
    setStreakCalendarMonth((current) => monthStart(new Date(current.getFullYear(), current.getMonth() + 1, 1, 12, 0, 0, 0)));
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const onOpenObjectives = () => {
      void openObjectivesModal();
    };
    window.addEventListener("healthsense-open-objectives", onOpenObjectives);
    return () => window.removeEventListener("healthsense-open-objectives", onOpenObjectives);
  }, [openObjectivesModal]);

  const saveObjectivesSection = useCallback(async () => {
    if (!selectedObjectivesSection) return;
    setWeeklyObjectivesSaving(true);
    setWeeklyObjectivesError(null);
    try {
      const savePayload = async (body: Record<string, unknown>) => {
        const res = await fetch("/api/weekly-objectives", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
        const text = await res.text().catch(() => "");
        if (!res.ok) {
          throw new Error(normalizeError(text, "Failed to save weekly objectives."));
        }
        return (text ? (JSON.parse(text) as WeeklyObjectivesResponse) : {}) as WeeklyObjectivesResponse;
      };
      let payload: WeeklyObjectivesResponse;
      if (selectedObjectivesSection === "wellbeing") {
        payload = await savePayload({
          userId,
          sectionKey: "wellbeing",
          wellbeing: wellbeingObjectiveDraft,
        });
      } else {
        payload = await savePayload({
          userId,
          sectionKey: selectedObjectivesSection,
          conceptTargets: selectedPillarObjectiveDraft,
        });
        if (selectedPillarWellbeingItems.length) {
          payload = await savePayload({
            userId,
            sectionKey: "wellbeing",
            wellbeing: wellbeingObjectiveDraft,
          });
        }
      }
      applyWeeklyObjectivesPayload(payload);
      logUserAppEvent("weekly_objectives_save", { section: selectedObjectivesSection });
      void refreshSummary({ skipQuoteGeneration: false }).catch(() => undefined);
      refreshSummaryFromWorkerCache(selectedObjectivesSection);
      if (typeof window !== "undefined") {
        window.dispatchEvent(
          new CustomEvent("healthsense-tracker-updated", {
            detail: {
              guided: false,
              objectivesUpdated: true,
            },
          }),
        );
      }
      setSelectedObjectivesSection(null);
    } catch (error) {
      setWeeklyObjectivesError(error instanceof Error ? error.message : String(error));
    } finally {
      setWeeklyObjectivesSaving(false);
    }
  }, [
    applyWeeklyObjectivesPayload,
    logUserAppEvent,
    refreshSummary,
    selectedObjectivesSection,
    selectedPillarObjectiveDraft,
    selectedPillarWellbeingItems,
    userId,
    wellbeingObjectiveDraft,
  ]);

  useEffect(() => {
    setSummaryPanelVisible(
      activeDockKey === "checkin" &&
        resolveSummaryPanelVisible(summary, readMorningSequenceState(userId, summary.today)),
    );
  }, [activeDockKey, summary, userId]);

  useEffect(() => {
    setDisplayTheme(resolveCurrentDisplayTheme());
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const syncTheme = () => setDisplayTheme(resolveCurrentDisplayTheme());
    window.addEventListener("healthsense-theme-changed", syncTheme as EventListener);
    window.addEventListener("storage", syncTheme);
    return () => {
      window.removeEventListener("healthsense-theme-changed", syncTheme as EventListener);
      window.removeEventListener("storage", syncTheme);
    };
  }, []);

  useEffect(() => {
    if (!modalOverlayOpen || typeof document === "undefined") return;
    const previousBodyOverflow = document.body.style.overflow;
    const previousDocumentOverflow = document.documentElement.style.overflow;
    document.body.style.overflow = "hidden";
    document.documentElement.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previousBodyOverflow;
      document.documentElement.style.overflow = previousDocumentOverflow;
    };
  }, [modalOverlayOpen]);

  useEffect(() => {
    if (!BIOMETRICS_ENABLED || !biometricsModalOpen) return;
    void loadLatestUrineTest();
    void loadWeeklyObjectives();
  }, [biometricsModalOpen, loadLatestUrineTest, loadWeeklyObjectives]);

  useEffect(() => {
    if (!BIOMETRICS_ENABLED || !biometricsModalOpen || !urineTestFlowOpen) return;
    setUrineCaptureNowMs(Date.now());
    const interval = window.setInterval(() => setUrineCaptureNowMs(Date.now()), 30000);
    return () => {
      window.clearInterval(interval);
    };
  }, [biometricsModalOpen, urineTestFlowOpen]);

  useEffect(() => {
    if (!BIOMETRICS_ENABLED || !biometricsModalOpen || !urineCaptureStartedAt) return;
    const updateTimer = () => {
      const elapsedSeconds = Math.floor((Date.now() - urineCaptureStartedAt) / 1000);
      const nextSecondsLeft = Math.max(0, URINE_CAPTURE_TIMER_SECONDS - elapsedSeconds);
      setUrineTimerSecondsLeft(nextSecondsLeft);
      if (nextSecondsLeft <= 0) {
        setUrineCaptureStartedAt(null);
      }
    };
    updateTimer();
    const interval = window.setInterval(updateTimer, 1000);
    return () => {
      window.clearInterval(interval);
    };
  }, [biometricsModalOpen, urineCaptureStartedAt]);

  useEffect(() => {
    if (!BIOMETRICS_ENABLED || !summaryPanelVisible) return;
    let cancelled = false;
    const hydrateRestingHeartRate = async () => {
      try {
        const summaryPayload = await loadRestingHeartRate();
        if (cancelled) return;
        if (summaryPayload?.available) {
          setRestingHeartRate(summaryPayload);
        }
      } catch {
        // Keep the score screen usable even if Apple Health data is unavailable.
      }
      if (!appleHealthSupported) return;
      try {
        const auth = await getAppleHealthAuthorizationStatus();
        if (cancelled) return;
        const status = auth.status || "unsupported";
        setAppleHealthAuthStatus(status);
        if (auth.available && status === "not_determined" && !appleHealthAutoRequestRef.current) {
          appleHealthAutoRequestRef.current = true;
          await syncNativeRestingHeartRate(true);
          return;
        }
        if (auth.available && status === "authorized") {
          await syncNativeRestingHeartRate(false);
        }
      } catch {
        if (!cancelled) {
          setAppleHealthAuthStatus("unsupported");
        }
      }
    };
    void hydrateRestingHeartRate();
    return () => {
      cancelled = true;
    };
  }, [appleHealthSupported, loadRestingHeartRate, summaryPanelVisible, syncNativeRestingHeartRate]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const onSummaryVisibilityChange = (event: Event) => {
      const detail = (event as CustomEvent<{ visible?: boolean }>).detail;
      setSummaryPanelVisible(Boolean(detail?.visible));
    };
    const onShowSummaryPanel = () => {
      setStreakSectionOpen(false);
      setObjectivesModalOpen(false);
      setSummaryPanelVisible(true);
      setSelectedPillarKey(null);
      setActiveDockKey("checkin");
    };
    window.addEventListener("healthsense-score-panel-visibility", onSummaryVisibilityChange as EventListener);
    window.addEventListener("healthsense-show-score-panel", onShowSummaryPanel);
    return () => {
      window.removeEventListener("healthsense-score-panel-visibility", onSummaryVisibilityChange as EventListener);
      window.removeEventListener("healthsense-show-score-panel", onShowSummaryPanel);
    };
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const onHomeSurfaceChange = (event: Event) => {
      const detail = (event as CustomEvent<{ surface?: string }>).detail;
      const surface = String(detail?.surface || "").trim();
      if (surface === "insight") {
        setStreakSectionOpen(false);
        setObjectivesModalOpen(false);
        setActiveDockKey("learn");
        setSummaryPanelVisible(false);
      } else if (surface === "streak") {
        setStreakSectionOpen(true);
        setObjectivesModalOpen(false);
        setSelectedPillarKey(null);
        setBiometricsModalOpen(false);
        setActiveDockKey("checkin");
        setSummaryPanelVisible(false);
      } else if (surface === "blank" || surface === "tracking") {
        setStreakSectionOpen(false);
        setActiveDockKey("checkin");
      }
    };
    window.addEventListener("healthsense-home-surface", onHomeSurfaceChange as EventListener);
    return () => window.removeEventListener("healthsense-home-surface", onHomeSurfaceChange as EventListener);
  }, []);

  useEffect(() => {
    if (!summaryPanelVisible) return;
    const panel = summaryPanelRef.current;
    if (!panel || typeof panel.scrollIntoView !== "function") return;
    const frame = window.requestAnimationFrame(() => {
      panel.scrollIntoView({ behavior: "smooth", block: "start" });
    });
    return () => {
      window.cancelAnimationFrame(frame);
    };
  }, [summaryPanelVisible]);

  useEffect(() => {
    if (!summaryPanelVisible || selectedPillarKey || !returnToPillarKey) return;
    scrollToPillarCueCard(returnToPillarKey);
    setReturnToPillarKey(null);
  }, [returnToPillarKey, scrollToPillarCueCard, selectedPillarKey, summaryPanelVisible]);

  useEffect(() => {
    if (!summaryPanelVisible || assessmentReviewed || assessmentReviewSyncStarted) return;
    let cancelled = false;
    setAssessmentReviewSyncStarted(true);
    const syncAssessmentReview = async () => {
      try {
        const params = new URLSearchParams({ userId });
        const res = await fetch(`/api/assessment/report?${params.toString()}`, {
          method: "GET",
          cache: "no-store",
        });
        if (res.ok && !cancelled) {
          setAssessmentReviewed(true);
        }
      } catch {
        // Ignore silent review sync failures; the score view still works without this marker.
      }
    };
    void syncAssessmentReview();
    return () => {
      cancelled = true;
    };
  }, [assessmentReviewed, assessmentReviewSyncStarted, summaryPanelVisible, userId]);

  const loadTrackerDetail = useCallback(async (pillarKey: string, anchorDate?: string) => {
    setLoadingDetail(true);
    setDetailError(null);
    setSaveError(null);
    try {
      const params = new URLSearchParams({ userId });
      if (anchorDate) {
        params.set("anchorDate", anchorDate);
      }
      const res = await fetch(`/api/pillar-tracker/${encodeURIComponent(pillarKey)}?${params.toString()}`, {
        method: "GET",
        cache: "no-store",
      });
      const text = await res.text().catch(() => "");
      if (!res.ok) {
        throw new Error(normalizeError(text, "Failed to load the pillar tracker."));
      }
      const payload = (text ? (JSON.parse(text) as PillarTrackerDetailResponse) : {}) as PillarTrackerDetailResponse;
      setDetail(payload);
      const nextDraft: Record<string, number> = {};
      (payload.concepts || []).forEach((concept) => {
        const conceptKey = String(concept.concept_key || "").trim();
        const rawValue = concept.value;
        const hasRecordedValue =
          rawValue !== null &&
          rawValue !== undefined &&
          !(typeof rawValue === "string" && String(rawValue).trim() === "");
        const value = Number(rawValue);
        if (conceptKey && hasRecordedValue && Number.isFinite(value)) {
          nextDraft[conceptKey] = value;
        }
      });
      setDraft(nextDraft);
    } catch (error) {
      setDetailError(error instanceof Error ? error.message : String(error));
    } finally {
      setLoadingDetail(false);
    }
  }, [userId]);

  const openTracker = useCallback(async (
    pillarKey: string,
    anchorDate?: string,
    options?: { guided?: boolean; returnSurface?: TrackerReturnSurface | null },
  ) => {
    const normalizedPillarKey = String(pillarKey || "").trim().toLowerCase();
    if (!normalizedPillarKey) return;
    const guided = Boolean(options?.guided);
    setStreakSectionOpen(false);
    setObjectivesModalOpen(false);
    setBiometricsModalOpen(false);
    setGuidedTrackingActive(guided);
    setTrackerReturnSurface(options?.returnSurface ?? null);
    setSelectedPillarKey(normalizedPillarKey);
    setDetail(null);
    setDraft({});
    setDetailError(null);
    setSaveError(null);
    if (typeof window !== "undefined") {
      window.dispatchEvent(
        new CustomEvent("healthsense-home-surface", {
          detail: {
            surface: "blank",
          },
        }),
      );
    }
    await loadTrackerDetail(normalizedPillarKey, anchorDate);
  }, [loadTrackerDetail]);

  const closeTracker = () => {
    setSelectedPillarKey(null);
    setGuidedTrackingActive(false);
    setTrackerReturnSurface(null);
    setDetail(null);
    setDraft({});
    setDetailError(null);
    setSaveError(null);
    setLoadingDetail(false);
    setSaving(false);
  };

  const handleTrackerBack = () => {
    if (trackerReturnSurface && typeof window !== "undefined") {
      window.dispatchEvent(
        new CustomEvent("healthsense-home-surface", {
          detail: {
            surface: trackerReturnSurface,
          },
        }),
      );
    } else {
      setActiveDockKey("checkin");
      setSummaryPanelVisible(true);
      if (typeof window !== "undefined") {
        window.dispatchEvent(
          new CustomEvent("healthsense-home-surface", {
            detail: {
              surface: "blank",
              source: "summary",
            },
          }),
        );
        window.dispatchEvent(new CustomEvent("healthsense-show-score-panel"));
        window.scrollTo({ top: 0, behavior: "smooth" });
      }
    }
    closeTracker();
  };

  const saveTracker = async () => {
    if (!detail?.pillar?.pillar_key || !canSave) return;
    setSaving(true);
    setSaveError(null);
    try {
      const completedPillarKey = String(detail.pillar.pillar_key || "").trim().toLowerCase();
      const savedScoreDate = activeDate || detail.pillar.today || "";
      const entries = concepts.map((concept) => ({
        concept_key: concept.concept_key,
        value: draft[String(concept.concept_key || "").trim()],
      }));
      const res = await fetch(`/api/pillar-tracker/${encodeURIComponent(String(detail.pillar.pillar_key))}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          userId,
          score_date: savedScoreDate,
          entries,
          skipQuoteGeneration: false,
        }),
      });
      const text = await res.text().catch(() => "");
      if (!res.ok) {
        throw new Error(normalizeError(text, "Failed to save the pillar tracker."));
      }
      if (typeof window !== "undefined") {
        window.dispatchEvent(
          new CustomEvent("healthsense-tracker-updated", {
            detail: {
              pillarKey: completedPillarKey,
              scoreDate: savedScoreDate || null,
              guided: guidedTrackingActive,
            },
          }),
        );
      }
      setActiveDockKey("checkin");
      setSummaryPanelVisible(true);
      if (guidedTrackingActive && typeof window !== "undefined") {
        window.dispatchEvent(
          new CustomEvent("healthsense-home-surface", {
            detail: {
              surface: "blank",
              complete: true,
            },
          }),
        );
        window.dispatchEvent(new CustomEvent("healthsense-show-score-panel"));
      } else if (trackerReturnSurface && typeof window !== "undefined") {
        window.dispatchEvent(
          new CustomEvent("healthsense-home-surface", {
            detail: {
              surface: trackerReturnSurface,
            },
          }),
        );
      } else if (typeof window !== "undefined") {
        window.dispatchEvent(
          new CustomEvent("healthsense-home-surface", {
            detail: {
              surface: "blank",
              source: "summary",
            },
          }),
        );
      }
      setReturnToPillarKey(completedPillarKey || null);
      closeTracker();
      setSaving(false);
      void refreshSummary({ anchorDate: savedScoreDate, skipQuoteGeneration: false })
        .then(() => scrollToPillarCueCard(completedPillarKey))
        .catch(() => undefined);
      refreshSummaryFromWorkerCache(completedPillarKey, { anchorDate: savedScoreDate, waitForFresh: true });
    } catch (error) {
      setSaveError(error instanceof Error ? error.message : String(error));
      setSaving(false);
    }
  };

  const openDailyMenuSurface = (surface: "tracking" | "habits" | "insight" | "ask") => {
    if (typeof window !== "undefined") {
      const bridge = window as Window & {
        healthsenseSetHomeSurface?: (nextSurface: "tracking" | "habits" | "insight" | "ask") => void;
      };
      bridge.healthsenseSetHomeSurface?.(surface);
      window.dispatchEvent(
        new CustomEvent("healthsense-home-surface", {
          detail: {
            surface,
            source: "summary",
          },
        }),
      );
      window.scrollTo({ top: 0, behavior: "smooth" });
    }
  };

  useEffect(() => {
    if (typeof window === "undefined") return;
    const onOpenTracker = (event: Event) => {
      const detail = (event as CustomEvent<{
        pillarKey?: string;
        guided?: boolean;
        returnSurface?: TrackerReturnSurface | null;
      }>).detail;
      const requestedPillarKey = String(detail?.pillarKey || "").trim().toLowerCase();
      if (!requestedPillarKey) {
        setSummaryPanelVisible(true);
        setActiveDockKey("checkin");
        window.scrollTo({ top: 0, behavior: "smooth" });
        return;
      }
      void openTracker(requestedPillarKey, undefined, {
        guided: detail?.guided !== false,
        returnSurface: detail?.returnSurface ?? null,
      });
    };
    window.addEventListener("healthsense-open-tracker", onOpenTracker as EventListener);
    return () => {
      window.removeEventListener("healthsense-open-tracker", onOpenTracker as EventListener);
    };
  }, [openTracker]);

  return (
    <>
      {appSetupRequired && !selectedPillarKey && !objectivesModalOpen && !streakSectionOpen ? (
        <section className="flex h-full min-h-0 items-center pb-8 pt-6 sm:pt-8">
          <div className="coach-scrollbar w-full min-w-0 -translate-y-5 overflow-x-auto snap-x snap-proximity pb-4">
            <div className="flex gap-4 px-4 sm:gap-5 sm:px-5">
              <article className="relative flex min-h-[25.5rem] w-[min(86vw,22rem)] shrink-0 snap-center flex-col rounded-[30px] bg-[var(--surface)] px-6 py-6 text-[var(--text-primary)] shadow-[0_20px_44px_-36px_rgba(30,27,22,0.55)] sm:min-h-[27rem] sm:w-[23rem] sm:px-7 sm:py-7">
                <SetupHealthSenseLogo />
                <SetupSwipeHint />
                <p className="pr-16 text-[2.35rem] font-semibold leading-[0.98] tracking-normal text-[var(--text-primary)] sm:text-[2.7rem]">
                  Set up your CoachSense
                </p>
                <p className="mt-6 pr-4 text-[1.55rem] font-medium leading-[1.18] text-[var(--text-secondary)]">
                  Choose the pillars you want to work with first. They shape your check-in cards, weekly objectives, and learning units, and you can change them later in Preferences.
                </p>
              </article>

              {setupSelectablePillarOrder.map((pillarKey) => {
                const meta = getPillarMeta(pillarKey);
                const selected = Boolean(setupPillarSelections[pillarKey]);
                return (
                  <button
                    key={`setup-${pillarKey}`}
                    type="button"
                    onClick={() =>
                      setSetupPillarSelections((current) => ({
                        ...current,
                        [pillarKey]: !current[pillarKey],
                      }))
                    }
                    aria-pressed={selected}
                    className="relative flex min-h-[25.5rem] w-[min(86vw,22rem)] shrink-0 snap-center flex-col rounded-[30px] border border-[var(--border)] bg-[var(--surface)] px-6 py-6 text-left text-[var(--text-primary)] shadow-[0_20px_44px_-36px_rgba(30,27,22,0.55)] transition active:scale-[0.99] sm:min-h-[27rem] sm:w-[23rem] sm:px-7 sm:py-7"
                  >
                    <SetupPillarSelectionCircle pillarKey={pillarKey} selected={selected} />
                    <span className="flex items-start justify-between gap-4">
                      <span className="pr-24 text-[2.45rem] font-semibold leading-[0.98] tracking-normal sm:text-[2.85rem]">
                        {meta?.label || pillarKey}
                      </span>
                    </span>
                    <span className="mt-[calc(2rem+0.66cm)] block text-[1.55rem] font-medium leading-[1.18] text-[var(--text-secondary)]">
                      {PILLAR_SETUP_COPY[pillarKey] || meta?.note || ""}
                    </span>
                    <span className="mt-auto inline-flex min-h-[2.8rem] items-center justify-center rounded-full border border-[var(--action-primary-border)] bg-[var(--action-primary-bg)] px-5 py-3 text-sm font-semibold text-[var(--action-primary-text)]">
                      {selected ? "Selected" : "Add pillar"}
                    </span>
                  </button>
                );
              })}

              {SETUP_GUIDE_CARDS.map((card, index) => (
                <article
                  key={card.title}
                  className="relative flex min-h-[25.5rem] w-[min(86vw,22rem)] shrink-0 snap-center flex-col rounded-[30px] bg-[var(--surface)] px-6 py-6 text-[var(--text-primary)] shadow-[0_20px_44px_-36px_rgba(30,27,22,0.55)] sm:min-h-[27rem] sm:w-[23rem] sm:px-7 sm:py-7"
                >
                  <SetupGuideIcon iconKey={card.icon} />
                  {index === SETUP_GUIDE_CARDS.length - 1 ? null : <SetupSwipeHint />}
                  <p className="text-xs font-semibold uppercase tracking-[0.18em] text-[var(--text-tertiary)]">
                    {`Step ${index + 1}`}
                  </p>
                  <p className="mt-5 pr-24 text-[2.45rem] font-semibold leading-[0.98] tracking-normal sm:text-[2.85rem]">
                    {card.title}
                  </p>
                  <p className="mt-8 text-[1.55rem] font-medium leading-[1.18] text-[var(--text-secondary)]">
                    {card.body}
                  </p>
                  {index === SETUP_GUIDE_CARDS.length - 1 ? (
                    <div className="mt-auto space-y-3 pt-6">
                      {setupError ? (
                        <p className="rounded-2xl border border-[var(--border)] bg-[var(--surface-muted)] px-4 py-3 text-sm leading-6 text-[var(--text-secondary)]">
                          {setupError}
                        </p>
                      ) : null}
                      <button
                        type="button"
                        onClick={() => void saveAppSetup()}
                        disabled={setupSaving}
                        className="min-h-[3.25rem] w-full rounded-full border border-[var(--action-primary-border)] bg-[var(--action-primary-bg)] px-5 py-3 text-base font-semibold text-[var(--action-primary-text)] transition active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-60"
                      >
                        {setupSaving ? "Saving setup" : "Start"}
                      </button>
                    </div>
                  ) : null}
                </article>
              ))}
            </div>
          </div>
        </section>
      ) : null}

      {summaryPanelVisible && !appSetupRequired && !selectedPillarKey && !objectivesModalOpen && !streakSectionOpen ? (
        <section
          ref={summaryPanelRef}
          className="flex h-full min-h-0 items-center pb-28 pt-6 sm:pb-32 sm:pt-8"
        >
          <div className="relative -translate-y-[0.5cm] overflow-hidden">
            <div className="overflow-x-auto snap-x snap-proximity [-ms-overflow-style:none] [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
              <div className="flex gap-4 sm:gap-5">
                {visiblePillars.map((pillar) => {
                  const pillarKey = String(pillar.pillar_key || "").trim().toLowerCase();
                  const palette = getPillarPalette(pillarKey);
                  const score = resolvePillarDisplayScore(pillar);
                  const journalDate = formatJournalDate(summary.today || summary.week?.anchor_date || "");
                  const checkinOptions = Array.isArray(pillar.checkin_options)
                    ? pillar.checkin_options.filter((option) => String(option?.date || "").trim())
                    : [];
                  const resolvedCheckinOptions = checkinOptions.length
                    ? checkinOptions
                    : [{ date: summary.today || "", label: "Today", complete: pillar.today_complete, is_today: true }];
                  const orderedCheckinOptions = [...resolvedCheckinOptions].sort((a, b) => {
                    const rank = (option: (typeof resolvedCheckinOptions)[number]) => {
                      if (option?.is_last_week) return 0;
                      if (option?.is_yesterday) return 1;
                      if (option?.is_today) return 2;
                      return 3;
                    };
                    return rank(a) - rank(b);
                  });
                  const quote = resolveHomePillarQuote(pillar, pillarKey);
                  const quoteLines = String(quote || "")
                    .split(/\n+/)
                    .map((line) => line.trim())
                    .filter(Boolean);
                  const quoteAuthor = quoteLines.length >= 3 ? quoteLines[quoteLines.length - 1] : "";
                  const quoteBodyLines = quoteAuthor ? quoteLines.slice(0, -1) : quoteLines;
                  return (
                    <article
                      key={pillarKey}
                      ref={(node) => {
                        if (node) {
                          pillarCueCardRefs.current[pillarKey] = node;
                        } else {
                          delete pillarCueCardRefs.current[pillarKey];
                        }
                      }}
                      className="relative flex min-h-[28rem] w-[min(92vw,24rem)] shrink-0 snap-center flex-col overflow-hidden rounded-[34px] px-7 py-7 text-left shadow-[0_20px_44px_-36px_rgba(30,27,22,0.55)] transition active:scale-[0.99] sm:min-h-[30rem] sm:w-[25rem] sm:px-8 sm:py-8"
                      style={pillarCueCardStyle}
                    >
                      <div className="absolute right-5 top-5">
                        <WeeklyScoreRing value={score} tone={palette.accent} />
                      </div>
                      <div className="pr-24">
                        <p className="text-[2.2rem] font-semibold leading-[0.98] tracking-[-0.02em] sm:text-[2.65rem]">
                          {pillar.label}
                        </p>
                        {journalDate ? (
                          <p className="mt-3 text-xs font-semibold uppercase tracking-[0.16em] text-current opacity-50">
                            Journal {journalDate}
                          </p>
                        ) : null}
                      </div>
                      <div className="mt-8 flex min-h-0 flex-1 flex-col sm:mt-9">
                        <div className="max-h-[9.5rem] max-w-[18rem] overflow-y-auto pr-1 [-ms-overflow-style:none] [scrollbar-width:none] [&::-webkit-scrollbar]:hidden sm:max-h-[10.75rem]">
                          <div className="space-y-3 text-[1.18rem] leading-8 text-current opacity-80">
                            {(quoteBodyLines.length ? quoteBodyLines : [quote]).map((line, index) => (
                              <p key={`${pillarKey}-quote-${index}`}>
                                {line}
                              </p>
                            ))}
                            {quoteAuthor ? (
                              <p className="pt-1 text-right text-[0.9rem] font-semibold uppercase tracking-[0.12em] opacity-70">
                                {quoteAuthor}
                              </p>
                            ) : null}
                          </div>
                        </div>
                        <div className="mt-auto grid max-w-[16rem] grid-cols-2 gap-2 pt-5">
                          {orderedCheckinOptions.map((option) => {
                            const optionDate = String(option?.date || "").trim();
                            const optionLabel = String(
                              option?.label || (option?.is_last_week ? "Last week" : option?.is_yesterday ? "Yesterday" : "Today"),
                            ).trim();
                            const complete = option?.complete === true;
                            return (
                              <button
                                key={`${pillarKey}-${optionDate || optionLabel}`}
                                type="button"
                                onClick={() =>
                                  void openTracker(pillarKey, optionDate || undefined, {
                                    guided: false,
                                  })
                                }
                                className={`min-h-[2.7rem] rounded-full border px-3 py-2 text-center text-[0.88rem] font-semibold leading-tight transition active:scale-[0.98] ${
                                  complete
                                    ? "border-[var(--border-strong)] bg-[var(--surface-muted)] text-[var(--text-primary)] shadow-[inset_0_0_0_1px_rgba(30,27,22,0.03)]"
                                    : "border-[var(--action-primary-border)] bg-[var(--action-primary-bg)] text-[var(--action-primary-text)]"
                                }`}
                              >
                                {optionLabel}
                              </button>
                            );
                          })}
                        </div>
                      </div>
                    </article>
                  );
                })}
              </div>
            </div>
          </div>
        </section>
      ) : null}

      {streakSectionOpen && !appSetupRequired ? (
        <section className="flex h-full min-h-0 flex-col pb-28 pt-4 sm:pb-32 sm:pt-6">
          <div className="relative flex min-h-0 w-full flex-1 flex-col overflow-hidden">
            <div className="shrink-0 px-4 pb-3 sm:px-5">
              <button
                type="button"
                onClick={closeStreakSection}
                className="flex h-12 w-12 items-center justify-center rounded-full border border-[var(--border)] bg-[var(--surface)] text-[var(--text-primary)] shadow-[0_10px_26px_-22px_rgba(30,27,22,0.45)]"
                aria-label="Back to check-in"
              >
                <span className="text-3xl leading-none">‹</span>
              </button>
            </div>

            <div className="coach-scrollbar min-h-0 flex-1 overflow-y-auto overscroll-contain px-4 pb-8 sm:px-5">
              <div className="mb-4 flex items-end justify-between gap-4">
                <div className="min-w-0">
                  <h2 className="text-[1.65rem] font-semibold leading-[1.05] tracking-normal text-[var(--text-primary)] sm:text-3xl">
                    Streak
                  </h2>
                  <p className="mt-1 text-base leading-snug text-[var(--text-secondary)]">
                    A record of the days you have checked in or learned.
                  </p>
                </div>
                <div className="shrink-0 rounded-[22px] border border-[var(--border)] bg-[var(--surface)] px-4 py-3 text-center">
                  <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-[var(--text-tertiary)]">
                    Current
                  </p>
                  <p className="mt-1 text-3xl font-semibold leading-none text-[var(--text-primary)]">
                    {currentStreakDays}
                  </p>
                </div>
              </div>

              <div className="rounded-[28px] border border-[var(--border)] bg-[var(--surface)] px-4 py-4 shadow-[0_24px_40px_-36px_rgba(30,27,22,0.4)] sm:px-5">
                <div className="flex items-center justify-between gap-4">
                  <h3 className="text-[1.25rem] font-semibold leading-none text-[var(--text-primary)]">
                    {streakMonthLabel}
                  </h3>
                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      onClick={showPreviousStreakMonth}
                      className="flex h-10 w-10 items-center justify-center rounded-full border border-[var(--border)] bg-[var(--surface)] text-[var(--text-primary)] transition active:scale-[0.98]"
                      aria-label="Previous month"
                    >
                      <span className="text-3xl leading-none">‹</span>
                    </button>
                    <button
                      type="button"
                      onClick={showNextStreakMonth}
                      className="flex h-10 w-10 items-center justify-center rounded-full border border-[var(--border)] bg-[var(--surface)] text-[var(--text-primary)] transition active:scale-[0.98]"
                      aria-label="Next month"
                    >
                      <span className="text-3xl leading-none">›</span>
                    </button>
                  </div>
                </div>

                <div className="mt-5 grid grid-cols-7 gap-1 text-center text-xs font-semibold text-[var(--text-primary)]">
                  {["M", "T", "W", "T", "F", "S", "S"].map((label, index) => (
                    <div key={`${label}-${index}`} className="py-0.5">
                      {label}
                    </div>
                  ))}
                </div>

                <div className="mt-2 grid grid-cols-7 gap-x-1.5 gap-y-1.5">
                  {streakCalendarDays.map((day) => {
                    if (!day.inMonth) {
                      return <div key={day.key} className="h-11" aria-hidden="true" />;
                    }
                    const completed = streakCompletedDateSet.has(day.iso);
                    const dayStyle = completed
                      ? {
                          backgroundColor: "color-mix(in srgb, var(--accent) 16%, var(--surface))",
                          borderColor: "transparent",
                          color: "var(--accent)",
                        }
                      : day.isToday
                        ? {
                            backgroundColor: "var(--surface)",
                            borderColor: "var(--border-strong)",
                            color: "var(--text-primary)",
                          }
                        : {
                            backgroundColor: "transparent",
                            borderColor: "transparent",
                            color: day.isFuture ? "var(--text-tertiary)" : "var(--text-secondary)",
                          };
                    return (
                      <div
                        key={day.key}
                        className="flex h-11 flex-col items-center justify-center rounded-xl border text-center transition"
                        style={dayStyle}
                      >
                        <span className="text-sm font-semibold leading-none">
                          {day.dayNumber}
                        </span>
                        <svg
                          viewBox="0 0 24 24"
                          className={`mt-1 h-3.5 w-3.5 ${completed ? "" : "opacity-55"}`}
                          aria-hidden="true"
                        >
                          <path
                            d="M12 3.2c.38 1.54-.25 2.55-1.05 3.46C9.86 7.69 8.7 9 8.7 10.8c0 1.76 1.06 3.02 2.05 3.73.24-1.12.24-2.17.1-3.04.94.86 2.05 2.22 2.05 4.02A3.98 3.98 0 0 1 9 19.5a4.12 4.12 0 0 1-4.1-4.1c0-1.98.97-3.62 2.4-5.06 1.03-1.05 2.2-2.08 2.94-3.18.42-.62.74-1.3.85-2.28.27.15.58.55.91 1.3Z"
                            fill="none"
                            stroke="currentColor"
                            strokeWidth="1.55"
                            strokeLinejoin="round"
                            strokeLinecap="round"
                          />
                        </svg>
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>
          </div>
        </section>
      ) : null}

      {!(BIOMETRICS_ENABLED && biometricsModalOpen) && !appSetupRequired ? (
        <div className="pointer-events-none fixed inset-x-0 bottom-0 z-[60]">
          <div className="mx-auto w-full max-w-[23rem] px-4 pb-[calc(0.75rem+env(safe-area-inset-bottom))] sm:px-5">
            <div className="pointer-events-auto overflow-hidden rounded-[30px] border border-[var(--chrome-border)] bg-[var(--chrome)] shadow-[0_18px_40px_-30px_rgba(30,27,22,0.35)]">
              <div className="grid grid-cols-2 p-1">
                <button
                  type="button"
                  onClick={() => {
                    if (selectedPillarKey) {
                      closeTracker();
                    }
                    if (objectivesModalOpen) {
                      closeObjectivesModal();
                    }
                    if (streakSectionOpen) {
                      setStreakSectionOpen(false);
                    }
                    setActiveDockKey("checkin");
                    setSummaryPanelVisible(true);
                    if (typeof window !== "undefined") {
                      window.dispatchEvent(
                        new CustomEvent("healthsense-home-surface", {
                          detail: {
                            surface: "blank",
                            source: "summary",
                          },
                        }),
                      );
                      window.dispatchEvent(new CustomEvent("healthsense-show-score-panel"));
                      window.scrollTo({ top: 0, behavior: "smooth" });
                    }
                  }}
                  aria-pressed={activeDockKey === "checkin"}
                  className={homeDockButtonClassName}
                  style={activeDockKey === "checkin" ? homeDockButtonStyleActive : homeDockButtonStyleInactive}
                >
                  <BiometricsIcon className="h-4 w-4 text-[var(--chrome-text)]" />
                  <span className="text-[12.5px] font-semibold leading-none sm:text-[13.75px]">
                    Checkin
                  </span>
                </button>
                <button
                  type="button"
                  onClick={() => {
                    if (selectedPillarKey) {
                      closeTracker();
                    }
                    if (objectivesModalOpen) {
                      closeObjectivesModal();
                    }
                    if (streakSectionOpen) {
                      setStreakSectionOpen(false);
                    }
                    setActiveDockKey("learn");
                    setSummaryPanelVisible(false);
                    openDailyMenuSurface("insight");
                  }}
                  aria-pressed={activeDockKey === "learn"}
                  className={homeDockButtonClassName}
                  style={activeDockKey === "learn" ? homeDockButtonStyleActive : homeDockButtonStyleInactive}
                >
                  <InsightIcon className="h-4 w-4 text-[var(--chrome-text)]" />
                  <span className="text-[12.5px] font-semibold leading-none sm:text-[13.75px]">
                    Learn
                  </span>
                </button>
              </div>
            </div>
          </div>
        </div>
      ) : null}

      {BIOMETRICS_ENABLED && biometricsModalOpen ? (
        <div className="fixed inset-0 z-50 flex items-stretch justify-center overflow-hidden overscroll-none bg-black/40 sm:items-center sm:px-3 sm:py-3">
          <div className="flex h-[100dvh] max-h-[100dvh] min-h-0 w-full max-w-2xl flex-col overflow-hidden bg-[var(--surface)] pt-[env(safe-area-inset-top)] pb-[env(safe-area-inset-bottom)] shadow-[0_30px_80px_-60px_rgba(30,27,22,0.6)] sm:h-auto sm:max-h-[92vh] sm:rounded-[28px] sm:border sm:border-[#e7e1d6] sm:pt-0 sm:pb-0">
            <div className="shrink-0 border-b border-[var(--border)] bg-[var(--surface)] px-4 py-4 sm:px-5">
              <div className="flex items-start justify-between gap-3">
                <div className="space-y-1">
                  <p className="text-xs uppercase tracking-[0.22em] text-[var(--text-secondary)]">
                    {activeBiomarkerExplanationDetail
                      ? activeBiomarkerExplanationDetail.title
                      : urineTestFlowOpen
                        ? "Urine test"
                        : biometricSourceCheckOpen
                          ? "Config"
                        : "Biometrics"}
                  </p>
                  <p className="text-sm text-[var(--text-secondary)]">
                    {activeBiomarkerExplanationDetail
                      ? "Understand what this biomarker means, your latest result, and the scale."
                      : urineTestFlowOpen
                      ? "Follow the 60-second HealthSense capture flow before taking the photo."
                      : biometricSourceCheckOpen
                      ? "Review where each biometric comes from and what Gia can use."
                      : "Review your latest biometric measurements."}
                  </p>
                </div>
                {urineTestFlowOpen || activeBiomarkerExplanationDetail || biometricSourceCheckOpen ? (
                  <button
                    type="button"
                    onClick={() => {
                      if (activeBiomarkerExplanationDetail) {
                        setActiveBiomarkerExplanation(null);
                        return;
                      }
                      if (biometricSourceCheckOpen) {
                        setBiometricSourceCheckOpen(false);
                        return;
                      }
                      setUrineTestFlowOpen(false);
                    }}
                    className="rounded-full border border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-xs font-semibold uppercase tracking-[0.16em] text-[var(--text-secondary)]"
                  >
                    {activeBiomarkerExplanationDetail ? "Close" : "Back"}
                  </button>
                ) : (
                  <button
                    type="button"
                    onClick={() => {
                      setActiveBiomarkerExplanation(null);
                      setUrineTestFlowOpen(false);
                      setBiometricSourceCheckOpen(true);
                    }}
                    className={biometricSourceCheckButtonClassName}
                  >
                    {restingHeartRateLoading || restingHeartRateEnabling ? "Syncing" : "Config"}
                  </button>
                )}
              </div>
            </div>

            <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-4 py-4 sm:px-5">
              <div className="space-y-4">
                <details className="group">
                  <summary className={`inline-flex cursor-pointer list-none items-center justify-between gap-3 rounded-full border px-3 py-2 text-xs font-semibold uppercase tracking-[0.16em] ${biometricAboutButtonClassName}`}>
                    <span>About biometrics</span>
                    <span aria-hidden="true" className="text-sm leading-none transition-transform group-open:rotate-45">
                      +
                    </span>
                  </summary>
                  <p className={`mt-3 rounded-2xl border px-4 py-3 text-sm leading-6 ${biometricAboutPanelClassName}`}>
                    HealthSense biometrics and urine markers are optional wellbeing screening and trend signals. They
                    are not medical diagnosis or treatment advice. If a result is unexpected or you have symptoms,
                    retest where appropriate and speak to a qualified healthcare professional.
                  </p>
                </details>
                {!urineTestFlowOpen && activeBiomarkerExplanationDetail ? (
                  <div className="rounded-[24px] border border-[var(--border)] bg-[var(--surface)] px-4 py-4">
                    <BiomarkerExplanationCard
                      className=""
                      description={activeBiomarkerExplanationDetail.description}
                      title={activeBiomarkerExplanationDetail.title}
                      result={activeBiomarkerExplanationDetail.result}
                      scaleRows={activeBiomarkerExplanationDetail.scaleRows}
                      showMarkerColumn={activeBiomarkerExplanationDetail.showMarkerColumn}
                      theme={displayTheme}
                    />
                  </div>
                ) : urineTestFlowOpen ? (
                  <div className="rounded-[24px] border border-[var(--border)] bg-[var(--surface)] px-4 py-4">
                    <div className="flex items-start justify-between gap-3">
                      <div className="space-y-1">
                        <p className="text-sm font-semibold text-[var(--text-primary)]">Take urine test</p>
                        <p className="text-sm text-[var(--text-secondary)]">
                          Photograph the strip on a plain white background at 60 seconds.
                        </p>
                      </div>
                      <p className={`shrink-0 rounded-full border px-3 py-2 text-[10px] font-semibold uppercase tracking-[0.14em] ${urineCaptureToneClassName}`}>
                        {urineCaptureState}
                      </p>
                    </div>
                    <input
                      ref={urinePhotoCameraInputRef}
                      type="file"
                      accept="image/*"
                      capture="environment"
                      onChange={handleUrinePhotoSelected}
                      className="hidden"
                    />
                    <input
                      ref={urinePhotoLibraryInputRef}
                      type="file"
                      accept="image/*"
                      onChange={handleUrinePhotoSelected}
                      className="hidden"
                    />
                    <div className="mt-4 space-y-3">
                      <div className="rounded-2xl border border-[var(--border)] bg-[#fffaf3] px-4 py-3">
                        <p className="text-xs font-semibold uppercase tracking-[0.16em] text-[var(--text-tertiary)]">Step 1</p>
                        <p className="mt-1 text-sm font-semibold text-[var(--text-primary)]">Prepare the strip</p>
                        <p className="mt-1 text-sm text-[var(--text-secondary)]">
                          Dip the Siemens Multistix strip, remove excess urine, and place it flat on a plain white background in good light.
                        </p>
                      </div>
                      <div className="rounded-2xl border border-[var(--border)] bg-[#fffaf3] px-4 py-3">
                        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                          <div>
                            <p className="text-xs font-semibold uppercase tracking-[0.16em] text-[var(--text-tertiary)]">Step 2</p>
                            <p className="mt-1 text-sm font-semibold text-[var(--text-primary)]">Start the read window</p>
                            <p className="mt-1 text-sm text-[var(--text-secondary)]">
                              {urineCaptureStartedAt
                                ? `${urineTimerSecondsLeft}s remaining. Take the photo when the timer reaches zero.`
                                : "Start after dipping. HealthSense captures at 60 seconds for the selected marker set."}
                            </p>
                          </div>
                          <button
                            type="button"
                            onClick={startUrineCaptureTimer}
                            disabled={urineTestSaving}
                            className="rounded-full border border-[var(--border)] bg-[var(--surface)] px-4 py-2 text-[11px] font-semibold uppercase tracking-[0.16em] text-[var(--text-secondary)] disabled:cursor-not-allowed disabled:opacity-60"
                          >
                            Start timer
                          </button>
                        </div>
                      </div>
                      <div className="rounded-2xl border border-[var(--border)] bg-[#fffaf3] px-4 py-3">
                        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                          <div>
                            <p className="text-xs font-semibold uppercase tracking-[0.16em] text-[var(--text-tertiary)]">Step 3</p>
                            <p className="mt-1 text-sm font-semibold text-[var(--text-primary)]">Take the photo</p>
                            <p className="mt-1 text-sm text-[var(--text-secondary)]">
                              Keep the strip flat in the frame. Retake if the image is blurred, shadowed, or strongly tinted.
                            </p>
                          </div>
                          <div className="flex flex-col gap-2 sm:items-end">
                            <button
                              type="button"
                              onClick={() => void openUrinePhotoCapture()}
                              disabled={urineTestSaving}
                              className="rounded-full border border-[#c54817] bg-[#c54817] px-4 py-2 text-[11px] font-semibold uppercase tracking-[0.16em] text-white disabled:cursor-not-allowed disabled:opacity-60"
                            >
                              {urineTestSaving ? "Saving" : hasRecentUrineCapture ? "Retake photo" : "Take photo"}
                            </button>
                            <button
                              type="button"
                              onClick={() => void openUrinePhotoLibrary()}
                              disabled={urineTestSaving}
                              className="rounded-full border border-[var(--border)] bg-[var(--surface)] px-4 py-2 text-[11px] font-semibold uppercase tracking-[0.16em] text-[var(--text-secondary)] disabled:cursor-not-allowed disabled:opacity-60"
                            >
                              Use existing photo
                            </button>
                          </div>
                        </div>
                      </div>
                    </div>
                    <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-3">
                      {urineMarkers.map((marker) => {
                        const markerToneClassName = resolveUrineMarkerTone(displayTheme, marker, {
                          glucoseRaised: urineGlucoseRaised,
                          ketogenicDietActive,
                        });
                        return (
                          <div
                            key={String(marker.key || marker.label)}
                            className={`rounded-xl border px-3 py-3 text-left text-[11px] ${markerToneClassName}`}
                          >
                            <p className="font-semibold opacity-80">{marker.label}</p>
                            <p className="mt-3 text-sm font-semibold uppercase tracking-[0.12em]">
                              {formatUrineStatusLabel(marker)}
                            </p>
                          </div>
                        );
                      })}
                    </div>
                    <p className="mt-4 text-sm text-[var(--text-secondary)]">
                      {urineTestLoading
                        ? "Loading latest urine test..."
                        : urineTestError
                          ? urineTestError
                          : urinePhotoCapturedAt
                        ? `Latest capture ${urinePhotoCapturedAt}${urinePhotoName ? ` · ${urinePhotoName}` : ""}`
                        : urineTest?.captured_at
                          ? `Latest capture ${formatCapturedAt(new Date(urineTest.captured_at))}`
                          : "No urine photo captured yet."}
                    </p>
                    {urineResultMessage ? (
                      <p className="mt-2 rounded-2xl border border-[#f2dccb] bg-[#fff8ef] px-3 py-2 text-xs text-[#8a5a1a]">
                        {urineResultMessage}
                      </p>
                    ) : null}
                  </div>
                ) : biometricSourceCheckOpen ? (
                  <div className="rounded-[24px] border border-[#e7e1d6] bg-[var(--surface)] px-4 py-4">
                        <div className="flex items-start justify-between gap-3">
                          <div className="space-y-1">
                            <p className="text-sm font-semibold text-[var(--text-primary)]">Biometric sources</p>
                            <p className="text-sm text-[var(--text-secondary)]">
                              Apple Health source data is used where available. Excluded metrics are not used by Gia.
                            </p>
                          </div>
                          <span className="rounded-full border border-[#f0d4ad] bg-[#fff8ef] px-3 py-1 text-[10px] font-semibold uppercase tracking-[0.14em] text-[#9b5b18]">
                            {restingHeartRateLoading || restingHeartRateEnabling ? "Syncing" : "Config"}
                          </span>
                        </div>
                        {biometricsActionError ? (
                          <p className="mt-3 rounded-2xl border border-[#f0d4ad] bg-[#fff8ef] px-3 py-2 text-xs text-[#9b5b18]">
                            {biometricsActionError}
                          </p>
                        ) : null}
                        <div className="mt-4 space-y-3">
                          {biometricSourceRows.map(({ key, label, source }) => {
                            const enabled = source?.enabled !== false;
                            const confidenceLabel = enabled
                              ? String(source?.confidence_label || source?.confidence || "Unknown")
                              : "Excluded";
                            const sourceToneClassName = resolveBiometricSourceTone(displayTheme, source);
                            const showConnections = shouldShowBiometricConnectionOptions(source);
                            const connectionOptions = Array.isArray(source?.connection_options)
                              ? source.connection_options
                              : [];
                            return (
                              <div
                                key={`source-${key}`}
                                className={`rounded-2xl border px-3 py-3 ${sourceToneClassName}`}
                              >
                                <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                                  <div className="min-w-0 space-y-1">
                                    <div className="flex flex-wrap items-center gap-2">
                                      <p className="text-sm font-semibold">{label}</p>
                                      <span className="rounded-full border border-current/20 bg-[var(--surface)] px-2 py-1 text-[10px] font-semibold uppercase tracking-[0.12em]">
                                        {confidenceLabel}
                                      </span>
                                    </div>
                                    <p className="text-xs opacity-80">
                                      Source: {formatBiometricSourceLabel(source)}
                                    </p>
                                    {source?.advice ? (
                                      <p className="text-xs leading-5 opacity-90">{source.advice}</p>
                                    ) : null}
                                  </div>
                                  <button
                                    type="button"
                                    onClick={() => void saveBiometricPreference(key, !enabled)}
                                    disabled={biometricPreferenceSaving === key}
                                    className={`shrink-0 rounded-full border px-3 py-2 text-[10px] font-semibold uppercase tracking-[0.14em] disabled:cursor-not-allowed disabled:opacity-60 ${
                                      enabled
                                        ? "border-[#c54817] bg-[#c54817] text-white"
                                        : "border-[var(--border)] bg-[var(--surface)] text-[var(--text-secondary)]"
                                    }`}
                                  >
                                    {biometricPreferenceSaving === key ? "Saving" : enabled ? "Included" : "Excluded"}
                                  </button>
                                </div>
                                {showConnections && connectionOptions.length ? (
                                  <div className="mt-3 flex flex-wrap gap-2">
                                    {connectionOptions.map((option) => {
                                      const provider = String(option?.provider || "").trim().toLowerCase();
                                      const canConnect = Boolean(option?.connectable);
                                      const pending = wearableConnectPending === provider;
                                      return (
                                        <button
                                          key={`${key}-${provider || option?.label || "provider"}`}
                                          type="button"
                                          onClick={() => void startBiometricWearableConnection(provider)}
                                          disabled={!canConnect || pending || Boolean(wearableConnectPending)}
                                          className={`rounded-full border px-3 py-2 text-[10px] font-semibold uppercase tracking-[0.14em] disabled:cursor-not-allowed disabled:opacity-55 ${
                                            canConnect
                                              ? "border-[#c54817] bg-[#c54817] text-white"
                                              : "border-[var(--border)] bg-[var(--surface)] text-[var(--text-secondary)]"
                                          }`}
                                        >
                                          {pending
                                            ? "Opening"
                                            : canConnect
                                              ? `Connect ${option?.label || provider}`
                                              : `${option?.label || provider} pending`}
                                        </button>
                                      );
                                    })}
                                  </div>
                                ) : null}
                              </div>
                            );
                          })}
                        </div>
                  </div>
                ) : (
                  <>
                    {showTrainingReadinessCard ? (
                      <div className="rounded-[24px] border border-[#e7e1d6] bg-[#fffaf3] px-4 py-4">
                        <div className="flex items-center justify-between gap-3">
                          <p className="text-sm font-semibold text-[var(--text-primary)]">Training readiness</p>
                          <div className="flex items-center gap-2">
                            <button
                              type="button"
                              onClick={() =>
                                setActiveBiomarkerExplanation((current) =>
                                  current === "training_readiness" ? null : "training_readiness",
                                )
                              }
                              className={biomarkerExplanationButtonClassName}
                            >
                              Explain
                            </button>
                            <p className="text-xs uppercase tracking-[0.16em] text-[var(--text-tertiary)]">
                              Last 7 days
                            </p>
                          </div>
                        </div>

                        <div className="mt-4 grid grid-cols-7 gap-1 sm:gap-2">
                          {trainingReadinessWeek.map(({ metric_date: metricDate, item }) => {
                            const alignmentItem = readinessActivityWeek.find(
                              (entry) => entry.metric_date === metricDate,
                            )?.item;
                            const status = normalizeTrainingReadinessStatus(
                              item?.status || alignmentItem?.training_readiness_status,
                            );
                            return (
                              <BiometricStatusCircle
                                key={`training-readiness-${metricDate}`}
                                label={resolveStatusShortLabel(status)}
                                metricDate={metricDate}
                                status={status}
                                toneClassName={resolveTrainingReadinessCircleTone(displayTheme, status)}
                              />
                            );
                          })}
                        </div>

                        {showRestingHeartRateMetric ? (
                          <div className="mt-5 border-t border-[var(--border)] pt-4">
                          <div className="flex items-center justify-between gap-3">
                            <p className="text-sm font-semibold text-[var(--text-primary)]">Resting HR</p>
                            <div className="flex items-center gap-2">
                              <button
                                type="button"
                                onClick={() =>
                                  setActiveBiomarkerExplanation((current) => (current === "rhr" ? null : "rhr"))
                                }
                                className={biomarkerExplanationButtonClassName}
                              >
                                Explain
                              </button>
                              <p className="text-xs uppercase tracking-[0.16em] text-[var(--text-tertiary)]">
                                Last 7 days
                              </p>
                            </div>
                          </div>
                          {restingHeartRateHistory.length ? (
                            <div className="mt-4 grid grid-cols-7 gap-2">
                              {restingHeartRateWeek.map(({ metric_date: metricDate, item }) => {
                                const value = resolveRestingHeartRateValue(item?.resting_hr_bpm);
                                const metricToneClassName = resolveRestingHeartRateMetricTone(
                                  displayTheme,
                                  item?.trend_status,
                                );
                                return (
                                  <div
                                    key={`resting-hr-${metricDate}`}
                                    className={`rounded-xl border px-2 py-2 text-center text-[11px] ${restingHeartRateBoxToneClassName}`}
                                  >
                                    <p className="font-semibold opacity-80">{formatBiometricDayLabel(metricDate)}</p>
                                    <p className="mt-1 opacity-65">{formatBiometricDayNumber(metricDate)}</p>
                                    <p className={`mt-3 text-sm font-semibold leading-none ${metricToneClassName}`}>
                                      {value || "—"}
                                    </p>
                                    <p className={`mt-2 text-[10px] font-semibold uppercase tracking-[0.12em] ${metricToneClassName}`}>
                                      {value ? resolveRestingHeartRateCompactTrendLabel(item?.trend_label) : "—"}
                                    </p>
                                  </div>
                                );
                              })}
                            </div>
                          ) : (
                            <p className="mt-3 text-sm text-[var(--text-secondary)]">
                              Daily history will appear here once recent biometrics have been synced.
                            </p>
                          )}
                          </div>
                        ) : null}

                        {showHrvMetric ? (
                          <div className="mt-5 border-t border-[var(--border)] pt-4">
                          <div className="flex items-center justify-between gap-3">
                            <p className="text-sm font-semibold text-[var(--text-primary)]">HRV</p>
                            <div className="flex items-center gap-2">
                              <button
                                type="button"
                                onClick={() =>
                                  setActiveBiomarkerExplanation((current) => (current === "hrv" ? null : "hrv"))
                                }
                                className={biomarkerExplanationButtonClassName}
                              >
                                Explain
                              </button>
                              <p className="text-xs uppercase tracking-[0.16em] text-[var(--text-tertiary)]">
                                Last 7 days
                              </p>
                            </div>
                          </div>
                          {heartRateVariabilityHistory.length ? (
                            <div className="mt-4 grid grid-cols-7 gap-2">
                              {heartRateVariabilityWeek.map(({ metric_date: metricDate, item }) => {
                                const value = resolveHeartRateVariabilityValue(item?.hrv_ms);
                                const metricToneClassName = resolveRestingHeartRateMetricTone(
                                  displayTheme,
                                  item?.trend_status,
                                );
                                return (
                                  <div
                                    key={`hrv-${metricDate}`}
                                    className={`rounded-xl border px-2 py-2 text-center text-[11px] ${restingHeartRateBoxToneClassName}`}
                                  >
                                    <p className="font-semibold opacity-80">{formatBiometricDayLabel(metricDate)}</p>
                                    <p className="mt-1 opacity-65">{formatBiometricDayNumber(metricDate)}</p>
                                    <p className={`mt-3 text-sm font-semibold leading-none ${metricToneClassName}`}>
                                      {value || "—"}
                                    </p>
                                    <p className={`mt-2 text-[10px] font-semibold uppercase tracking-[0.12em] ${metricToneClassName}`}>
                                      {value ? resolveRestingHeartRateCompactTrendLabel(item?.trend_label) : "—"}
                                    </p>
                                  </div>
                                );
                              })}
                            </div>
                          ) : (
                            <p className="mt-3 text-sm text-[var(--text-secondary)]">
                              Daily HRV history will appear here once recent biometrics have been synced.
                            </p>
                          )}
                          </div>
                        ) : null}
                      </div>
                    ) : null}

                    {showActivityStatusCard ? (
                      <div className="rounded-[24px] border border-[var(--border)] bg-[var(--surface)] px-4 py-4">
                        <div className="flex items-center justify-between gap-3">
                          <p className="text-sm font-semibold text-[var(--text-primary)]">Activity status</p>
                          <div className="flex items-center gap-2">
                            <button
                              type="button"
                              onClick={() =>
                                setActiveBiomarkerExplanation((current) =>
                                  current === "activity_status" ? null : "activity_status",
                                )
                              }
                              className={biomarkerExplanationButtonClassName}
                            >
                              Explain
                            </button>
                            <p className="text-xs uppercase tracking-[0.16em] text-[var(--text-tertiary)]">
                              Last 7 days
                            </p>
                          </div>
                        </div>
                        <div className="mt-4 grid grid-cols-7 gap-1 sm:gap-2">
                          {activityStatusWeek.map(({ metric_date: metricDate, item }) => {
                            const alignmentItem = readinessActivityWeek.find(
                              (entry) => entry.metric_date === metricDate,
                            )?.item;
                            const status = normalizeActivityStatus(item?.status || alignmentItem?.activity_status);
                            return (
                              <BiometricStatusCircle
                                key={`activity-status-${metricDate}`}
                                label={resolveStatusShortLabel(status)}
                                metricDate={metricDate}
                                status={status}
                                toneClassName={resolveActivityCircleTone(displayTheme, status)}
                              />
                            );
                          })}
                        </div>

                        {showActiveMinutesMetric ? (
                          <div className="mt-5 border-t border-[var(--border)] pt-4">
                          <div className="flex items-center justify-between gap-3">
                            <p className="text-sm font-semibold text-[var(--text-primary)]">Exercise minutes</p>
                            <div className="flex items-center gap-2">
                              <button
                                type="button"
                                onClick={() =>
                                  setActiveBiomarkerExplanation((current) =>
                                    current === "active_minutes" ? null : "active_minutes",
                                  )
                                }
                                className={biomarkerExplanationButtonClassName}
                              >
                                Explain
                              </button>
                              <p className="text-xs uppercase tracking-[0.16em] text-[var(--text-tertiary)]">
                                Last 7 days
                              </p>
                            </div>
                          </div>
                          {activeMinutesHistory.length ? (
                            <div className="mt-4 grid grid-cols-7 gap-2">
                              {activeMinutesWeek.map(({ metric_date: metricDate, item }) => {
                                const rawActiveMinutes = Number(item?.active_minutes);
                                const value = formatActiveMinutes(item?.active_minutes);
                                const activeMinutesStatus = resolveActiveMinutesStatus(rawActiveMinutes);
                                const metricToneClassName = resolveStepsMetricTone(displayTheme, activeMinutesStatus);
                                return (
                                  <div
                                    key={`active-minutes-${metricDate}`}
                                    className={`rounded-xl border px-2 py-2 text-center text-[11px] ${restingHeartRateBoxToneClassName}`}
                                  >
                                    <p className="font-semibold opacity-80">{formatBiometricDayLabel(metricDate)}</p>
                                    <p className="mt-1 opacity-65">{formatBiometricDayNumber(metricDate)}</p>
                                    <p className={`mt-3 whitespace-nowrap text-[12px] font-semibold leading-none ${metricToneClassName}`}>
                                      {value}
                                    </p>
                                    <p className={`mt-2 min-h-[0.75rem] text-[10px] font-semibold uppercase tracking-[0.12em] ${metricToneClassName}`}>
                                      {resolveCompactStepsStatusLabel(activeMinutesStatus)}
                                    </p>
                                  </div>
                                );
                              })}
                            </div>
                          ) : (
                            <p className="mt-3 text-sm text-[var(--text-secondary)]">
                              Daily exercise minutes will appear here once recent biometrics have been synced.
                            </p>
                          )}
                          </div>
                        ) : null}

                        {showStepsMetric ? (
                          <div className="mt-5 border-t border-[var(--border)] pt-4">
                          <div className="flex items-center justify-between gap-3">
                            <p className="text-sm font-semibold text-[var(--text-primary)]">Steps (000s)</p>
                            <div className="flex items-center gap-2">
                              <button
                                type="button"
                                onClick={() =>
                                  setActiveBiomarkerExplanation((current) => (current === "steps" ? null : "steps"))
                                }
                                className={biomarkerExplanationButtonClassName}
                              >
                                Explain
                              </button>
                              <p className="text-xs uppercase tracking-[0.16em] text-[var(--text-tertiary)]">
                                Last 7 days
                              </p>
                            </div>
                          </div>
                          {stepsHistory.length ? (
                            <div className="mt-4 grid grid-cols-7 gap-2">
                              {stepsWeek.map(({ metric_date: metricDate, item }) => {
                                const rawSteps = Number(item?.steps);
                                const value = formatCompactStepCount(item?.steps);
                                const stepStatus = resolveStepsStatus(rawSteps);
                                const metricToneClassName = resolveStepsMetricTone(displayTheme, stepStatus);
                                return (
                                  <div
                                    key={`steps-${metricDate}`}
                                    className={`rounded-xl border px-2 py-2 text-center text-[11px] ${restingHeartRateBoxToneClassName}`}
                                  >
                                    <p className="font-semibold opacity-80">{formatBiometricDayLabel(metricDate)}</p>
                                    <p className="mt-1 opacity-65">{formatBiometricDayNumber(metricDate)}</p>
                                    <p className={`mt-3 whitespace-nowrap text-[12px] font-semibold leading-none ${metricToneClassName}`}>
                                      {value}
                                    </p>
                                    <p className={`mt-2 min-h-[0.75rem] text-[10px] font-semibold uppercase tracking-[0.12em] ${metricToneClassName}`}>
                                      {resolveCompactStepsStatusLabel(stepStatus)}
                                    </p>
                                  </div>
                                );
                              })}
                            </div>
                          ) : (
                            <p className="mt-3 text-sm text-[var(--text-secondary)]">
                              Daily step history will appear here once recent biometrics have been synced.
                            </p>
                          )}
                          </div>
                        ) : null}
                      </div>
                    ) : null}

                    <div className="rounded-[24px] border border-[#e7e1d6] bg-[#fffaf3] px-4 py-4">
                      <div className="flex items-center justify-between gap-3">
                        <p className="text-sm font-semibold text-[var(--text-primary)]">
                          Urine{urineTestHeadingDate !== "—" ? ` (${urineTestHeadingDate})` : ""}
                        </p>
                        <div className="ml-auto flex items-center gap-2">
                          <button
                            type="button"
                            onClick={() =>
                              setActiveBiomarkerExplanation((current) => (current === "urine" ? null : "urine"))
                            }
                            className={biomarkerExplanationButtonClassName}
                          >
                            Explain
                          </button>
                          <button
                            type="button"
                            onClick={() => {
                              setActiveBiomarkerExplanation(null);
                              setUrineTestFlowOpen(true);
                              logUserAppEvent("urine_test_open", { source: "biometrics_modal" });
                            }}
                            className="rounded-full border border-[#c54817] bg-[#c54817] px-3 py-2 text-[10px] font-semibold uppercase tracking-[0.14em] text-white"
                          >
                            Test
                          </button>
                        </div>
                      </div>
                      <div className="mt-4 grid grid-cols-6 gap-2">
                        {urineMarkers.map((marker) => {
                          const dotToneClassName = resolveUrineStatusDotTone(displayTheme, marker, {
                            glucoseRaised: urineGlucoseRaised,
                            ketogenicDietActive,
                          });
                          return (
                            <div
                              key={String(marker.key || marker.label)}
                              className={`rounded-xl border px-1.5 py-2 text-center text-[10px] sm:px-2 sm:text-[11px] ${restingHeartRateBoxToneClassName}`}
                            >
                              <p className="truncate text-[9px] font-semibold leading-tight opacity-80 sm:text-[10px]">
                                {formatUrineTileLabel(marker)}
                              </p>
                              <span className={`mx-auto mt-3 block h-6 w-6 rounded-full border-2 sm:h-7 sm:w-7 ${dotToneClassName}`} />
                              <p className="mt-2 min-h-[0.75rem] text-[10px] font-semibold uppercase tracking-[0.12em]">
                                {formatUrineDisplayStatusLabel(marker)}
                              </p>
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  </>
                )}
              </div>
            </div>

            <div className="shrink-0 border-t border-[var(--border)] px-4 py-4 sm:px-5">
              <button
                type="button"
                onClick={() => {
                  if (activeBiomarkerExplanationDetail) {
                    setActiveBiomarkerExplanation(null);
                    return;
                  }
                  setActiveBiomarkerExplanation(null);
                  setBiometricSourceCheckOpen(false);
                  setUrineTestFlowOpen(false);
                  setBiometricsModalOpen(false);
                }}
                className="w-full rounded-full border border-[var(--border)] bg-[var(--surface)] px-4 py-3 text-center text-xs font-semibold uppercase tracking-[0.18em] text-[var(--text-secondary)]"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {objectivesModalOpen ? (
        <section className="flex h-full min-h-0 flex-col pb-28 pt-4 sm:pb-32 sm:pt-6">
          <div className="relative flex min-h-0 w-full flex-1 flex-col overflow-hidden">
            <div className="shrink-0 px-4 pb-3 sm:px-5">
              <button
                type="button"
                onClick={() => {
                  if (selectedObjectivesSection) {
                    setSelectedObjectivesSection(null);
                    setWeeklyObjectivesError(null);
                  } else {
                    closeObjectivesModal();
                  }
                }}
                className="flex h-12 w-12 items-center justify-center rounded-full border border-[var(--border)] bg-[var(--surface)] text-[var(--text-primary)] shadow-[0_10px_26px_-22px_rgba(30,27,22,0.45)]"
                aria-label={selectedObjectivesSection ? "Back to objectives" : "Close objectives"}
              >
                <span className="text-3xl leading-none">‹</span>
              </button>
            </div>

            <div className="coach-scrollbar min-h-0 flex-1 overflow-y-auto overscroll-contain px-4 pb-8 sm:px-5">
              <div className="mb-4 space-y-1.5">
                <h2 className="text-[1.65rem] font-semibold leading-[1.05] tracking-normal text-[var(--text-primary)] sm:text-3xl">
                  {selectedObjectivesSection
                    ? selectedObjectivesSection === "wellbeing"
                      ? "General options"
                      : selectedObjectivesPillar?.label || "Weekly objectives"
                    : "Weekly objectives"}
                </h2>
                <p className="text-base leading-snug text-[var(--text-secondary)]">
                  {selectedObjectivesSection
                    ? selectedObjectivesSection === "wellbeing"
                      ? "Set optional general tracking preferences."
                      : "Choose your target for each concept this week."
                    : "Select a pillar to set or adjust this week's targets."}
                </p>
              </div>

              {weeklyObjectivesLoading ? <p className="text-sm text-[var(--text-secondary)]">Loading weekly objectives…</p> : null}
              {weeklyObjectivesError ? <p className="text-sm text-[#8a3e1a]">{weeklyObjectivesError}</p> : null}

              {!weeklyObjectivesLoading && !selectedObjectivesSection ? (
                <div className="space-y-3">
                  {objectivesSections.map((section) => {
                    const sectionKey = String(section?.key || "").trim().toLowerCase();
                    const configuredCount = Number(section?.configured_count);
                    const totalCount = Number(section?.total_count);
                    const countLabel =
                      Number.isFinite(configuredCount) && Number.isFinite(totalCount) && totalCount > 0
                        ? `${configuredCount}/${totalCount} set`
                        : "";
                    return (
                      <button
                        key={sectionKey}
                        type="button"
                        onClick={() => setSelectedObjectivesSection(sectionKey as ObjectivesSectionKey)}
                        className="flex min-h-[5.75rem] w-full flex-col items-start justify-center rounded-[28px] border border-[var(--border)] bg-[var(--surface)] px-5 py-4 text-left shadow-[0_24px_40px_-36px_rgba(30,27,22,0.4)]"
                      >
                        <span className="flex w-full items-center justify-between gap-3">
                          <span className="flex min-w-0 items-center gap-3">
                            <WeeklyObjectiveSectionIcon sectionKey={sectionKey} />
                            <span className="truncate text-base font-semibold text-[var(--text-primary)]">
                              {formatWeeklyObjectiveSectionLabel(sectionKey, section?.label)}
                            </span>
                          </span>
                          {countLabel ? (
                            <span className="shrink-0 text-xs uppercase tracking-[0.16em] text-[var(--text-tertiary)]">
                              {countLabel}
                            </span>
                          ) : null}
                        </span>
                      </button>
                    );
                  })}
                </div>
              ) : null}

              {!weeklyObjectivesLoading && selectedObjectivesSection && selectedObjectivesSection !== "wellbeing" && selectedObjectivesPillar ? (
                <div className="space-y-3">
                  {(selectedObjectivesPillar.concepts || []).map((concept) => {
                    const conceptKey = String(concept?.concept_key || "").trim();
                    const selectedValue = selectedPillarObjectiveDraft[conceptKey];
                    const unitLabel = String(concept?.unit_label || "").trim();
                    const currentTargetLabel = String(concept?.target_label || "").trim();
                    return (
                      <div key={conceptKey} className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] px-4 py-4">
                        <div className="space-y-1">
                          <p className="text-sm font-semibold text-[var(--text-primary)]">{concept?.label}</p>
                          <p className="text-xs uppercase tracking-[0.18em] text-[var(--text-tertiary)]">
                            {concept?.metric_label || concept?.helper || conceptKey}
                          </p>
                          <p className="text-xs text-[var(--text-secondary)]">
                            {unitLabel ? `Target ${unitLabel}` : String(concept?.helper || "").trim()}
                            {currentTargetLabel ? ` · ${currentTargetLabel}` : ""}
                          </p>
                        </div>
                        <div className="mt-3 flex flex-wrap gap-2">
                          {(concept?.options || []).map((option) => {
                            const optionValue = Number(option?.value);
                            const isActive =
                              Number.isFinite(optionValue) &&
                              Number.isFinite(Number(selectedValue)) &&
                              optionValue === Number(selectedValue);
                            return (
                              <button
                                key={`${conceptKey}-${String(option?.label || option?.value || "")}`}
                                type="button"
                                onClick={() =>
                                  setPillarObjectiveDrafts((current) => ({
                                    ...current,
                                    [selectedObjectivesSection]: {
                                      ...(current[selectedObjectivesSection] || {}),
                                      [conceptKey]: Number.isFinite(optionValue) ? optionValue : null,
                                    },
                                  }))
                                }
                                className={`rounded-full border px-3 py-2 text-xs font-semibold uppercase tracking-[0.16em] ${
                                  isActive
                                    ? "border-[var(--action-primary-border)] bg-[var(--action-primary-bg)] text-[var(--action-primary-text)]"
                                    : "border-[var(--border)] bg-[var(--surface)] text-[var(--text-secondary)]"
                                }`}
                              >
                                {option?.label}
                              </button>
                            );
                          })}
                        </div>
                      </div>
                    );
                  })}
                  {selectedPillarWellbeingItems.map((item) => {
                    const itemKey = String(item?.key || "").trim();
                    const selectedValue = String(wellbeingObjectiveDraft[itemKey] || item?.value || "off").trim() || "off";
                    const itemFields = Array.isArray(item?.fields) ? item.fields : [];
                    return (
                      <div key={`wellbeing-${itemKey}`} className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] px-4 py-4">
                        <div className="space-y-1">
                          <p className="text-sm font-semibold text-[var(--text-primary)]">{item?.label}</p>
                          <p className="text-xs text-[var(--text-secondary)]">{item?.helper}</p>
                        </div>
                        {itemFields.length ? (
                          <div className="mt-4 space-y-4">
                            {itemFields.map((field) => {
                              const fieldKey = String(field?.key || "").trim();
                              if (!fieldKey) return null;
                              const fieldValue = String(
                                wellbeingObjectiveDraft[fieldKey] ?? field?.value ?? "",
                              ).trim();
                              return (
                                <div key={`${itemKey}-${fieldKey}`} className="space-y-2">
                                  <p className="text-xs font-semibold uppercase tracking-[0.16em] text-[var(--text-tertiary)]">
                                    {field?.label}
                                  </p>
                                  <div className="flex flex-wrap gap-2">
                                    {(field?.options || []).map((option) => {
                                      const optionValue = String(option?.value ?? "").trim();
                                      const isActive = optionValue === fieldValue;
                                      return (
                                        <button
                                          key={`${fieldKey}-${optionValue}`}
                                          type="button"
                                          onClick={() =>
                                            setWellbeingObjectiveDraft((current) => ({
                                              ...current,
                                              [fieldKey]: optionValue,
                                            }))
                                          }
                                          className={`rounded-full border px-3 py-2 text-xs font-semibold uppercase tracking-[0.16em] ${
                                            isActive
                                              ? "border-[var(--action-primary-border)] bg-[var(--action-primary-bg)] text-[var(--action-primary-text)]"
                                              : "border-[var(--border)] bg-[var(--surface)] text-[var(--text-secondary)]"
                                          }`}
                                        >
                                          {option?.label}
                                        </button>
                                      );
                                    })}
                                  </div>
                                </div>
                              );
                            })}
                          </div>
                        ) : (
                          <div className="mt-3 flex flex-wrap gap-2">
                            {(item?.options || []).map((option) => {
                              const optionValue = String(option?.value || "").trim();
                              const isActive = optionValue === selectedValue;
                              return (
                                <button
                                  key={`${itemKey}-${optionValue}`}
                                  type="button"
                                  onClick={() =>
                                    setWellbeingObjectiveDraft((current) => ({
                                      ...current,
                                      [itemKey]: optionValue,
                                    }))
                                  }
                                  className={`rounded-full border px-3 py-2 text-xs font-semibold uppercase tracking-[0.16em] ${
                                    isActive
                                      ? "border-[var(--action-primary-border)] bg-[var(--action-primary-bg)] text-[var(--action-primary-text)]"
                                      : "border-[var(--border)] bg-[var(--surface)] text-[var(--text-secondary)]"
                                  }`}
                                >
                                  {option?.label}
                                </button>
                              );
                            })}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              ) : null}

              {!weeklyObjectivesLoading && selectedObjectivesSection === "wellbeing" ? (
                <div className="space-y-3">
                  {wellbeingObjectiveItems.map((item) => {
                    const itemKey = String(item?.key || "").trim();
                    const selectedValue = String(wellbeingObjectiveDraft[itemKey] || item?.value || "off").trim() || "off";
                    const itemFields = Array.isArray(item?.fields) ? item.fields : [];
                    return (
                      <div key={itemKey} className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] px-4 py-4">
                        <div className="space-y-1">
                          <p className="text-sm font-semibold text-[var(--text-primary)]">{item?.label}</p>
                          <p className="text-xs text-[var(--text-secondary)]">{item?.helper}</p>
                        </div>
                        {itemFields.length ? (
                          <div className="mt-4 space-y-4">
                            {itemFields.map((field) => {
                              const fieldKey = String(field?.key || "").trim();
                              if (!fieldKey) return null;
                              const fieldValue = String(
                                wellbeingObjectiveDraft[fieldKey] ?? field?.value ?? "",
                              ).trim();
                              return (
                                <div key={`${itemKey}-${fieldKey}`} className="space-y-2">
                                  <p className="text-xs font-semibold uppercase tracking-[0.16em] text-[var(--text-tertiary)]">
                                    {field?.label}
                                  </p>
                                  <div className="flex flex-wrap gap-2">
                                    {(field?.options || []).map((option) => {
                                      const optionValue = String(option?.value ?? "").trim();
                                      const isActive = optionValue === fieldValue;
                                      return (
                                        <button
                                          key={`${fieldKey}-${optionValue}`}
                                          type="button"
                                          onClick={() =>
                                            setWellbeingObjectiveDraft((current) => ({
                                              ...current,
                                              [fieldKey]: optionValue,
                                            }))
                                          }
                                          className={`rounded-full border px-3 py-2 text-xs font-semibold uppercase tracking-[0.16em] ${
                                            isActive
                                              ? "border-[var(--action-primary-border)] bg-[var(--action-primary-bg)] text-[var(--action-primary-text)]"
                                              : "border-[var(--border)] bg-[var(--surface)] text-[var(--text-secondary)]"
                                          }`}
                                        >
                                          {option?.label}
                                        </button>
                                      );
                                    })}
                                  </div>
                                </div>
                              );
                            })}
                          </div>
                        ) : (
                          <div className="mt-3 flex flex-wrap gap-2">
                            {(item?.options || []).map((option) => {
                              const optionValue = String(option?.value || "").trim();
                              const isActive = optionValue === selectedValue;
                              return (
                                <button
                                  key={`${itemKey}-${optionValue}`}
                                  type="button"
                                  onClick={() =>
                                    setWellbeingObjectiveDraft((current) => ({
                                      ...current,
                                      [itemKey]: optionValue,
                                    }))
                                  }
                                  className={`rounded-full border px-3 py-2 text-xs font-semibold uppercase tracking-[0.16em] ${
                                    isActive
                                      ? "border-[var(--action-primary-border)] bg-[var(--action-primary-bg)] text-[var(--action-primary-text)]"
                                      : "border-[var(--border)] bg-[var(--surface)] text-[var(--text-secondary)]"
                                  }`}
                                >
                                  {option?.label}
                                </button>
                              );
                            })}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              ) : null}
            </div>

            {selectedObjectivesSection ? (
              <div className="shrink-0 border-t border-[var(--border)] px-4 py-4 sm:px-5">
                <button
                  type="button"
                  onClick={() => void saveObjectivesSection()}
                  disabled={weeklyObjectivesSaving}
                  className="w-full rounded-full border border-[var(--action-primary-border)] bg-[var(--action-primary-bg)] px-4 py-3 text-center text-xs font-semibold uppercase tracking-[0.18em] text-[var(--action-primary-text)] disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {weeklyObjectivesSaving ? "Saving…" : "Save objectives"}
                </button>
              </div>
            ) : null}
          </div>
        </section>
      ) : null}

      {selectedPillarKey ? (
        <section className="flex h-full min-h-0 flex-col pb-28 pt-4 sm:pb-32 sm:pt-6">
          <div className="relative flex min-h-0 w-full flex-1 flex-col overflow-hidden">
            <div className="shrink-0 px-4 pb-3 sm:px-5">
              <button
                type="button"
                onClick={handleTrackerBack}
                className="flex h-12 w-12 items-center justify-center rounded-full border border-[var(--border)] bg-[var(--surface)] text-[var(--text-primary)] shadow-[0_10px_26px_-22px_rgba(30,27,22,0.45)]"
                aria-label="Back"
              >
                <span className="text-3xl leading-none">‹</span>
              </button>
            </div>
            <div className="coach-scrollbar min-h-0 flex-1 overflow-y-auto overscroll-contain px-4 pb-8 sm:px-5">
              {loadingDetail ? <p className="text-sm text-[var(--text-secondary)]">Loading tracker...</p> : null}
              {detailError ? <p className="text-sm text-[#8a3e1a]">{detailError}</p> : null}

              {detail && !loadingDetail ? (
                <div className="space-y-4">
                  {(detail.concepts || []).map((concept, conceptIndex) => {
                    const conceptKey = String(concept.concept_key || "").trim();
                    const selectedValue = draft[conceptKey];
                    const targetLabel = String(concept.target_label || "").trim();
                    const okrStatusLabel = String(concept.okr_status_label || "").trim();
                    const okrStatusDetail = String(concept.okr_status_detail || "").trim();
                    const showInlineOkrProgress = Boolean(okrStatusDetail);
                    const okrStatusTone =
                      concept.okr_on_track === true
                        ? "text-[#4e7a1f]"
                        : concept.okr_on_track === false
                          ? "text-[#b55b1d]"
                          : "text-[var(--text-secondary)]";
                    return (
                      <section
                        key={conceptKey}
                        className="flex min-h-[28rem] w-full flex-col overflow-hidden rounded-[34px] bg-[var(--surface-muted)] px-7 py-7 text-left shadow-[0_20px_44px_-38px_rgba(30,27,22,0.4)] sm:min-h-[30rem] sm:px-8 sm:py-8"
                      >
                        <div className="flex items-start justify-between gap-4">
                          <div className="min-w-0">
                            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-[#c54817]">
                              {`${conceptIndex + 1} of ${detail.concepts?.length || 0}`}
                            </p>
                            <h2 className="mt-3 text-[2.25rem] font-semibold leading-[0.98] tracking-normal text-[var(--text-primary)]">
                              {concept.label}
                            </h2>
                          </div>
                        </div>
                        <p className="mt-6 text-[1.45rem] font-medium leading-8 text-[var(--text-primary)]">
                          {concept.helper}
                        </p>
                        {targetLabel || okrStatusLabel ? (
                          <p className="mb-7 mt-4 text-sm leading-6 text-[var(--text-secondary)]">
                            {targetLabel}
                            {targetLabel && showInlineOkrProgress ? " · " : null}
                            {showInlineOkrProgress ? okrStatusDetail : null}
                            {(targetLabel || showInlineOkrProgress) && okrStatusLabel ? " · " : null}
                            {okrStatusLabel ? (
                              <span className={`font-medium ${okrStatusTone}`}>{okrStatusLabel}</span>
                            ) : null}
                          </p>
                        ) : null}
                        <div className="mt-auto space-y-5">
                          <div className="grid grid-cols-7 gap-1.5">
                            {(concept.week || []).map((day) => (
                              <div
                                key={`${conceptKey}-${day.date}`}
                                className={`rounded-xl border px-1.5 py-2 text-center text-[10px] ${circleDayTone(displayTheme, day.daily_status, day.is_active)}`}
                              >
                                <p className="font-semibold">{day.label}</p>
                                <p className="mt-1 truncate">{day.value_label || "-"}</p>
                              </div>
                            ))}
                          </div>
                          {canEditActiveWeek ? (
                            <div className="grid grid-cols-2 gap-2">
                              {(concept.options || []).map((option) => {
                                const value = Number(option.value);
                                const active = Number.isFinite(value) && value === selectedValue;
                                return (
                                  <button
                                    key={`${conceptKey}-${option.label}-${option.value}`}
                                    type="button"
                                    onClick={() =>
                                      setDraft((current) => ({
                                        ...current,
                                        [conceptKey]: value,
                                      }))
                                    }
                                    className={`min-h-[2.75rem] rounded-full px-3 py-2 text-center text-xs font-semibold leading-tight transition ${
                                      active ? "bg-[var(--action-primary-bg)] text-[var(--action-primary-text)]" : "bg-[var(--surface)] text-[var(--text-primary)]"
                                    }`}
                                  >
                                    {option.label}
                                  </button>
                                );
                              })}
                            </div>
                          ) : null}
                        </div>
                      </section>
                    );
                  })}

                  {saveError ? <p className="text-sm font-semibold text-[#8a3e1a]">{saveError}</p> : null}
                  {canEditActiveWeek ? (
                    <button
                      type="button"
                      onClick={() => void saveTracker()}
                      disabled={!canSave}
                      className="w-full rounded-full bg-[var(--action-primary-bg)] px-5 py-4 text-center text-sm font-semibold uppercase tracking-[0.16em] text-[var(--action-primary-text)] transition disabled:cursor-not-allowed disabled:opacity-45"
                    >
                      {saving ? "Saving check-in..." : "Complete check-in"}
                    </button>
                  ) : null}
                </div>
              ) : null}
            </div>

          </div>
        </section>
      ) : null}
    </>
  );
}
