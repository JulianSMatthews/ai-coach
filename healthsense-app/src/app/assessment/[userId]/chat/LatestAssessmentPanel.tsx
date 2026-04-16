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
  WeeklyObjectivePillarConfig,
  WeeklyObjectivesResponse,
} from "@/lib/api";
import {
  canUseAppleHealth,
  getAppleHealthAuthorizationStatus,
  requestAppleHealthAuthorization,
  syncAppleHealthRestingHeartRate,
  type AppleHealthAuthorizationState,
} from "@/lib/appleHealth";
import { Capacitor } from "@capacitor/core";
import { applyThemePreference, readStoredThemePreference } from "@/lib/theme";
import { getPillarPalette } from "@/lib/pillars";
import { ScoreRing } from "@/components/ui";
import LeadAssessmentBranding from "./LeadAssessmentBranding";

type LatestAssessmentPanelProps = {
  userId: string;
  initialSummary: PillarTrackerSummaryResponse;
  initialAssessmentCombinedScore?: number | null;
  initialAssessmentReviewed?: boolean;
};

type TrackerReturnSurface = "tracking" | "habits" | "insight" | "ask";
type MorningSequenceState = "idle" | "in_progress" | "completed";
type DisplayTheme = "light" | "dark";
type ObjectivesSectionKey = "nutrition" | "training" | "resilience" | "recovery" | "wellbeing";
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

const PILLAR_ORDER = ["nutrition", "training", "resilience", "recovery"];
const HEALTHSENSE_ORANGE = "#c54817";
const MORNING_SEQUENCE_STORAGE_PREFIX = "hs:morning-sequence-complete";
const URINE_CAPTURE_TIMER_SECONDS = 60;
const URINE_RECENT_CAPTURE_WINDOW_MS = 5 * 60 * 1000;
const URINE_TEST_MAX_PHOTO_BYTES = 8 * 1024 * 1024;
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
    : "border-[#e7e1d6] bg-white text-[#5d5348]";
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
  return theme === "dark" ? "text-[var(--text-primary)]" : "text-[#5d5348]";
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
      ? "border-[var(--border)] bg-[var(--surface-muted)] text-[var(--text-muted)]"
      : "border-[#e7e1d6] bg-[#f7f1e8] text-[#6b6257]";
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
    : "border-[#e7e1d6] bg-white text-[#5d5348]";
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
  if (
    !["optimum", "normal", "elevated"].includes(resolvedHrvStatus) ||
    !["optimum", "normal", "elevated"].includes(resolvedRestingHeartRateStatus)
  ) {
    return "unknown";
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

function resolveTrainingReadinessDot(theme: DisplayTheme, status: TrainingReadinessStatus): string {
  if (status === "ready") {
    return theme === "dark" ? "bg-[#d9f0c5]" : "bg-[#69a23a]";
  }
  if (status === "low") {
    return theme === "dark" ? "bg-[#c7b0ff]" : "bg-[#6b4cc2]";
  }
  if (status === "unknown") {
    return theme === "dark" ? "bg-[#8c7f70]" : "bg-[#d8d0c5]";
  }
  return theme === "dark" ? "bg-[#ffd3ad]" : "bg-[#f0b35f]";
}

function resolveActivityDot(theme: DisplayTheme, status: ActivityStatus): string {
  if (status === "high") {
    return theme === "dark" ? "bg-[#c7b0ff]" : "bg-[#6b4cc2]";
  }
  if (status === "moderate") {
    return theme === "dark" ? "bg-[#d9f0c5]" : "bg-[#69a23a]";
  }
  if (status === "low") {
    return theme === "dark" ? "bg-[#ffd3ad]" : "bg-[#f0b35f]";
  }
  return theme === "dark" ? "bg-[#8c7f70]" : "bg-[#d8d0c5]";
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
  return theme === "dark" ? "border-[var(--border)] bg-[var(--surface)] text-[var(--text-secondary)]" : "border-[#ece5d9] bg-white text-[#8c7f70]";
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
  return theme === "dark" ? "border-[var(--border)] bg-[var(--surface)] text-[var(--text-secondary)]" : "border-[#ece5d9] bg-white text-[#8c7f70]";
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
    : "border-[#e7e1d6] bg-white text-[#8c7f70]";
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
    : "border-[#e7e1d6] bg-white text-[#8c7f70]";
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
  return theme === "dark" ? "border-[var(--border)] bg-[#6b6257]" : "border-[#d9cdbb] bg-[#d8d0c5]";
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
    : "border-[#e7e1d6] bg-white text-[#8c7f70]";
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
      : "border-[#efe7db] bg-[#fffaf3] text-[#5d5348]";
  const titleToneClassName = theme === "dark" ? "text-[var(--text-primary)]" : "text-[#1e1b16]";
  const tableToneClassName =
    theme === "dark" ? "border-[var(--border)] bg-[#151a24]" : "border-[#efe7db] bg-white";
  const headerToneClassName =
    theme === "dark"
      ? "border-[var(--border)] bg-[#1c2230] text-[var(--text-secondary)]"
      : "border-[#efe7db] bg-[#fff7ec] text-[#8c7f70]";
  const rowBorderClassName = theme === "dark" ? "border-[var(--border)]" : "border-[#f3eadf]";
  const markerTextClassName = theme === "dark" ? "text-[var(--text-primary)]" : "text-[#1e1b16]";
  const meaningTextClassName = theme === "dark" ? "text-[var(--text-secondary)]" : "text-[#6b6257]";
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
      <p className="text-[10px] font-semibold leading-none text-[#8c7f70]">{formatBiometricDayLabel(metricDate)}</p>
      <p className="mt-1 text-[10px] leading-none text-[#8c7f70]">{formatBiometricDayNumber(metricDate)}</p>
      <div
        className={`mt-2 flex h-10 w-10 items-center justify-center rounded-full border text-[8px] font-semibold uppercase leading-none sm:h-11 sm:w-11 ${toneClassName}`}
      >
        {hasStatus ? resolvedLabel : "—"}
      </div>
      {detail ? <p className="mt-2 min-h-[1.75rem] text-[9px] leading-tight text-[#6b6257]">{detail}</p> : null}
    </div>
  );
}

function formatIsoLocalDay(value: Date): string {
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, "0");
  const day = String(value.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
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
  if (sequenceState === "completed") return true;
  if (sequenceState === "in_progress") return false;
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
  return resolveScore(pillar.score);
}

function resolvePillarSource(pillar: PillarTrackerPillar): "tracker" | "assessment" {
  return resolveScore(pillar.tracker_score) !== null ? "tracker" : "assessment";
}

function circleDayTone(status?: string | null, isActive?: boolean): string {
  const activeRing = isActive ? " ring-1 ring-[#d9cdbb]" : "";
  if (status === "success") return `border-[#d5e8bf] bg-[#f2fae8] text-[#335f16]${activeRing}`;
  if (status === "warning") return `border-[#f2dccb] bg-[#fff4ea] text-[#8a5a1a]${activeRing}`;
  if (status === "danger") return `border-[#efc4b6] bg-[#fff0eb] text-[#9b3218]${activeRing}`;
  return `border-[#ece5d9] bg-white text-[#8c7f70]${activeRing}`;
}

function completeDayTone(complete?: boolean, score?: number | null, isToday?: boolean): string {
  if (complete && Number.isFinite(Number(score))) {
    const resolved = Number(score);
    if (resolved >= 80) return "border-[#d5e8bf] bg-[#f2fae8] text-[#335f16]";
    if (resolved >= 40) return "border-[#f2dccb] bg-[#fff4ea] text-[#8a5a1a]";
    return "border-[#efc4b6] bg-[#fff0eb] text-[#9b3218]";
  }
  if (isToday) return "border-[#f3d8c9] bg-[#fff5ef] text-[#8a3e1a]";
  return "border-[#ece5d9] bg-white text-[#8c7f70]";
}

function CombinedLogoRing({ value }: { value: number }) {
  const pct = Math.max(0, Math.min(1, value / 100));
  const size = 84;
  const stroke = 8;
  const radius = (size - stroke) / 2;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference * (1 - pct);
  return (
    <div className="relative flex h-[84px] w-[84px] items-center justify-center">
      <svg width={size} height={size} className="rotate-[-90deg]">
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          stroke="rgba(197,72,23,0.18)"
          strokeWidth={stroke}
          fill="none"
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          stroke={HEALTHSENSE_ORANGE}
          strokeWidth={stroke}
          fill="none"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          strokeLinecap="round"
        />
      </svg>
      <div className="absolute flex h-[60px] w-[60px] items-center justify-center rounded-full bg-white">
        <LeadAssessmentBranding
          titleLines={[]}
          logoClassName="h-8 w-8"
        />
      </div>
    </div>
  );
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
        <div className="h-[84px] w-[84px] rounded-full border-[8px] border-[#efe7db]" />
        <span className="absolute text-lg font-semibold text-[#8c7f70]">—</span>
      </div>
    </div>
  );
}

function HabitStepsIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      className="h-5 w-5 text-[var(--accent)]"
      aria-hidden="true"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M9 6h10" />
      <path d="M9 12h10" />
      <path d="M9 18h10" />
      <path d="M4 6l1.5 1.5L7.5 5" />
      <path d="M4 12l1.5 1.5L7.5 11" />
      <path d="M4 18l1.5 1.5L7.5 17" />
    </svg>
  );
}

function InsightIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      className="h-5 w-5 text-[var(--accent)]"
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

function GiaMessageIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      className="h-5 w-5 text-[var(--accent)]"
      aria-hidden="true"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M6 18l-3 3V7a3 3 0 0 1 3-3h12a3 3 0 0 1 3 3v8a3 3 0 0 1-3 3H6Z" />
      <path d="M8 9h8" />
      <path d="M8 13h5" />
    </svg>
  );
}

function BiometricsIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      className="h-5 w-5 text-[var(--accent)]"
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

function WeeklyObjectiveSectionIcon({ sectionKey }: { sectionKey: string }) {
  const normalizedKey = String(sectionKey || "").trim().toLowerCase();
  const iconSrc = normalizedKey === "wellbeing" ? "/healthsense-mark.svg" : getPillarPalette(normalizedKey).icon;
  if (!iconSrc) return null;
  return (
    <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl border border-[#efe7db] bg-[#fffaf3]">
      <img src={iconSrc} alt="" aria-hidden="true" className="h-6 w-6 object-contain" />
    </span>
  );
}

function formatWeeklyObjectiveSectionLabel(sectionKey: string, label?: string | null): string {
  const normalizedKey = String(sectionKey || "").trim().toLowerCase();
  if (normalizedKey === "wellbeing") return "General";
  return String(label || "").trim() || normalizedKey.replace(/_/g, " ");
}

export default function LatestAssessmentPanel({
  userId,
  initialSummary,
  initialAssessmentCombinedScore = null,
  initialAssessmentReviewed = false,
}: LatestAssessmentPanelProps) {
  const [summary, setSummary] = useState<PillarTrackerSummaryResponse>(initialSummary);
  const [summaryPanelVisible, setSummaryPanelVisible] = useState(
    () => resolveSummaryPanelVisible(initialSummary, readMorningSequenceState(userId, initialSummary.today)),
  );
  const [displayTheme, setDisplayTheme] = useState<DisplayTheme>("dark");
  const [togglingDisplay, setTogglingDisplay] = useState(false);
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
  const [appleHealthAuthStatus, setAppleHealthAuthStatus] = useState<AppleHealthAuthorizationState>("unsupported");
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
  const [urinePhotoName, setUrinePhotoName] = useState<string | null>(null);
  const [urinePhotoCapturedAt, setUrinePhotoCapturedAt] = useState<string | null>(null);
  const [urinePhotoCapturedAtMs, setUrinePhotoCapturedAtMs] = useState<number | null>(null);
  const [urineCaptureNowMs, setUrineCaptureNowMs] = useState(() => Date.now());

  const pillars = sortPillars(Array.isArray(summary.pillars) ? summary.pillars : []);
  const orderedPillarKeys = pillars
    .map((pillar) => String(pillar.pillar_key || "").trim().toLowerCase())
    .filter((pillarKey) => Boolean(pillarKey));
  const resolveNextPillarKey = useCallback((pillarKey: string): string | null => {
    const normalizedPillarKey = String(pillarKey || "").trim().toLowerCase();
    const currentIndex = orderedPillarKeys.indexOf(normalizedPillarKey);
    if (currentIndex < 0) {
      return orderedPillarKeys[0] || null;
    }
    return orderedPillarKeys[currentIndex + 1] || null;
  }, [orderedPillarKeys]);
  const hasTrackerScores = pillars.some((pillar) => resolvePillarSource(pillar) === "tracker");
  const combinedScore = (() => {
    if (!hasTrackerScores) {
      const assessmentCombined = resolveScore(initialAssessmentCombinedScore);
      if (assessmentCombined !== null) {
        return assessmentCombined;
      }
    }
    const scores = pillars
      .map((pillar) => resolvePillarDisplayScore(pillar))
      .filter((score): score is number => score !== null);
    if (!scores.length) return 0;
    return Math.round(scores.reduce((total, score) => total + score, 0) / scores.length);
  })();
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
  const closeTrackerLabel = guidedTrackingActive
    ? "Skip"
    : trackerReturnSurface === "tracking"
      ? "Cancel"
      : "Close";
  const trackerPillarLabel = detail?.pillar?.label || selectedPillarKey?.replace(/_/g, " ") || "";
  const trackerPillarKey = String(detail?.pillar?.pillar_key || selectedPillarKey || "").trim().toLowerCase();
  const displayLabel = displayTheme === "dark" ? "light" : "dark";
  const displayButtonClassName =
    displayLabel === "dark"
      ? "rounded-full border border-[#2f3542] bg-[#1c2230] px-3 py-1.5 text-[11px] font-semibold text-white shadow-[0_10px_24px_-18px_rgba(12,18,28,0.9)] disabled:cursor-not-allowed disabled:opacity-60"
      : "rounded-full border border-[#d9cdbb] bg-white px-3 py-1.5 text-[11px] font-semibold text-[#5d5348] shadow-[0_10px_24px_-18px_rgba(93,83,72,0.45)] disabled:cursor-not-allowed disabled:opacity-60";
  const objectivesSections = useMemo(
    () => (Array.isArray(weeklyObjectives?.sections) ? weeklyObjectives.sections : []),
    [weeklyObjectives],
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
  const wellbeingObjectiveItems = useMemo(
    () => (Array.isArray(weeklyObjectives?.wellbeing?.items) ? weeklyObjectives.wellbeing.items : []),
    [weeklyObjectives],
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
  const appleHealthSupported = canUseAppleHealth();
  const biometricSourceRows = useMemo(
    () => normalizeBiometricSourceRows(restingHeartRate?.biometric_sources),
    [restingHeartRate?.biometric_sources],
  );
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
  const trainingReadinessDotClassName = resolveTrainingReadinessDot(displayTheme, trainingReadinessStatus);
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
  const activityDotClassName = resolveActivityDot(displayTheme, activityStatus);
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
    "rounded-full border border-[#d9cdbb] bg-white px-3 py-2 text-[10px] font-semibold uppercase tracking-[0.14em] text-[#5d5348]";
  const biometricSourceCheckButtonClassName =
    "shrink-0 rounded-full border border-[var(--accent)] bg-[var(--accent)] px-3 py-2 text-xs font-semibold uppercase tracking-[0.16em] text-white shadow-[0_10px_24px_-18px_var(--shadow-strong)]";
  const latestHrvValue = resolveHeartRateVariabilityValue(latestHrvItem?.hrv_ms);
  const latestActiveMinutesValue = formatFullActiveMinutes(latestActiveMinutesItem?.active_minutes);
  const latestActiveMinutesStatus = resolveActiveMinutesStatus(latestActiveMinutesItem?.active_minutes);
  const latestStepsValue = formatFullStepCount(latestStepsItem?.steps);
  const latestStepsStatus = resolveStepsStatus(latestStepsItem?.steps);
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
      ? `Latest status: ${resolveTrainingReadinessLabel(trainingReadinessStatus)}. ${resolveTrainingReadinessAction(trainingReadinessStatus)}. This combines HRV ${latestHrvValue ? `${latestHrvValue} ms` : "not available"} and Resting HR ${restingHeartRateValue ? `${restingHeartRateValue} bpm` : "not available"} against your recent 7-14 day baseline.`
      : "Latest status: no current training readiness is available yet. Once HRV and Resting HR sync, this section compares recovery capacity with activity status.";
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

  const refreshSummary = useCallback(async () => {
    const res = await fetch(`/api/pillar-tracker/summary?userId=${encodeURIComponent(userId)}`, {
      method: "GET",
      cache: "no-store",
    });
    const text = await res.text().catch(() => "");
    if (!res.ok) {
      throw new Error(normalizeError(text, "Failed to refresh the pillar tracker summary."));
    }
    const payload = (text ? (JSON.parse(text) as PillarTrackerSummaryResponse) : {}) as PillarTrackerSummaryResponse;
    setSummary(payload);
  }, [userId]);

  const loadRestingHeartRate = useCallback(async () => {
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

  const syncNativeRestingHeartRate = useCallback(
    async (requestAccess = false) => {
      if (!appleHealthSupported) return null;
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

  const handleReviewBiometricsPress = useCallback(() => {
    setActiveBiomarkerExplanation(null);
    setBiometricSourceCheckOpen(false);
    setUrineTestFlowOpen(false);
    setBiometricsActionError(null);
    setBiometricsModalOpen(true);
    if (
      appleHealthSupported &&
      !restingHeartRateLoading &&
      !restingHeartRateEnabling &&
      appleHealthAuthStatus !== "denied"
    ) {
      void syncNativeRestingHeartRate(appleHealthAuthStatus !== "authorized");
    }
  }, [
    appleHealthAuthStatus,
    appleHealthSupported,
    restingHeartRateEnabling,
    restingHeartRateLoading,
    syncNativeRestingHeartRate,
  ]);

  const startUrineCaptureTimer = useCallback(() => {
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
    setUrineTestSaving(true);
    setUrineTestError(null);
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
          captureStage: urineCaptureStartedAt ? "timed" : "single",
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
    } catch (error) {
      setUrineTestError(error instanceof Error ? error.message : String(error));
    } finally {
      setUrineTestSaving(false);
    }
  }, [urineCaptureStartedAt, userId]);

  const openUrinePhotoCapture = useCallback(async () => {
    setUrineTestError(null);
    if (Capacitor.isNativePlatform()) {
      try {
        const { Camera, CameraResultType, CameraSource } = await import("@capacitor/camera");
        const photo = await Camera.getPhoto({
          allowEditing: false,
          correctOrientation: true,
          quality: 88,
          resultType: CameraResultType.DataUrl,
          saveToGallery: false,
          source: CameraSource.Camera,
        });
        const imageDataUrl = String(photo.dataUrl || "").trim();
        if (!imageDataUrl) {
          throw new Error("No photo data was returned.");
        }
        await submitUrinePhotoCapture({
          capturedAt: new Date(),
          fileName: "urine-sample.jpg",
          imageDataUrl,
          mimeType: "image/jpeg",
          sizeBytes: Math.round((imageDataUrl.length * 3) / 4),
        });
        return;
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        if (!message.toLowerCase().includes("cancel")) {
          setUrineTestError(message || "Camera capture failed.");
        }
        return;
      }
    }
    urinePhotoCameraInputRef.current?.click();
  }, [submitUrinePhotoCapture]);

  const openUrinePhotoLibrary = useCallback(async () => {
    setUrineTestError(null);
    if (Capacitor.isNativePlatform()) {
      try {
        const { Camera, CameraResultType, CameraSource } = await import("@capacitor/camera");
        const photo = await Camera.getPhoto({
          allowEditing: false,
          correctOrientation: true,
          quality: 88,
          resultType: CameraResultType.DataUrl,
          saveToGallery: false,
          source: CameraSource.Photos,
        });
        const imageDataUrl = String(photo.dataUrl || "").trim();
        if (!imageDataUrl) {
          throw new Error("No photo data was returned.");
        }
        await submitUrinePhotoCapture({
          capturedAt: new Date(),
          fileName: "urine-sample-library.jpg",
          imageDataUrl,
          mimeType: "image/jpeg",
          sizeBytes: Math.round((imageDataUrl.length * 3) / 4),
        });
        return;
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        if (!message.toLowerCase().includes("cancel")) {
          setUrineTestError(message || "Photo library selection failed.");
        }
        return;
      }
    }
    urinePhotoLibraryInputRef.current?.click();
  }, [submitUrinePhotoCapture]);

  const handleUrinePhotoSelected = useCallback(async (event: ChangeEvent<HTMLInputElement>) => {
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

  const toggleDisplayTheme = useCallback(async () => {
    if (togglingDisplay) return;
    const currentTheme = resolveCurrentDisplayTheme();
    const nextTheme: DisplayTheme = currentTheme === "dark" ? "light" : "dark";
    setTogglingDisplay(true);
    setDisplayTheme(nextTheme);
    applyThemePreference(nextTheme, true);
    try {
      const res = await fetch("/api/preferences", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          userId,
          theme: nextTheme,
        }),
      });
      if (!res.ok) {
        throw new Error("Failed to save display preference.");
      }
    } catch {
      setDisplayTheme(currentTheme);
      applyThemePreference(currentTheme, true);
    } finally {
      setTogglingDisplay(false);
    }
  }, [togglingDisplay, userId]);

  const applyWeeklyObjectivesPayload = useCallback((payload: WeeklyObjectivesResponse | null) => {
    setWeeklyObjectives(payload);
    const nextPillarDrafts: Record<string, Record<string, number | null>> = {};
    (payload?.pillars || []).forEach((pillar) => {
      const pillarKey = String(pillar?.pillar_key || "").trim().toLowerCase();
      if (!pillarKey) return;
      const conceptDraft: Record<string, number | null> = {};
      (pillar?.concepts || []).forEach((concept) => {
        const conceptKey = String(concept?.concept_key || "").trim();
        if (!conceptKey) return;
        const selectedValue = Number(concept?.selected_value);
        conceptDraft[conceptKey] = Number.isFinite(selectedValue) ? selectedValue : null;
      });
      nextPillarDrafts[pillarKey] = conceptDraft;
    });
    setPillarObjectiveDrafts(nextPillarDrafts);
    const nextWellbeingDraft: Record<string, string> = {};
    (payload?.wellbeing?.items || []).forEach((item) => {
      const itemKey = String(item?.key || "").trim();
      if (!itemKey) return;
      nextWellbeingDraft[itemKey] = String(item?.value || "").trim() || "off";
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
        await loadWeeklyObjectives().catch(() => undefined);
      } catch (error) {
        setBiometricsActionError(error instanceof Error ? error.message : String(error));
      } finally {
        setBiometricPreferenceSaving(null);
      }
    },
    [loadWeeklyObjectives, userId],
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
            : `/assessment/${userId}/chat`;
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
    setObjectivesModalOpen(true);
    setSelectedObjectivesSection(null);
    setBiometricsActionError(null);
    await loadWeeklyObjectives();
  }, [loadWeeklyObjectives]);

  const closeObjectivesModal = useCallback(() => {
    setObjectivesModalOpen(false);
    setSelectedObjectivesSection(null);
    setWeeklyObjectivesError(null);
    setWeeklyObjectivesSaving(false);
    setBiometricsActionError(null);
  }, []);

  const saveObjectivesSection = useCallback(async () => {
    if (!selectedObjectivesSection) return;
    setWeeklyObjectivesSaving(true);
    setWeeklyObjectivesError(null);
    try {
      const body =
        selectedObjectivesSection === "wellbeing"
          ? {
              userId,
              sectionKey: "wellbeing",
              wellbeing: wellbeingObjectiveDraft,
            }
          : {
              userId,
              sectionKey: selectedObjectivesSection,
              conceptTargets: selectedPillarObjectiveDraft,
            };
      const res = await fetch("/api/weekly-objectives", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const text = await res.text().catch(() => "");
      if (!res.ok) {
        throw new Error(normalizeError(text, "Failed to save weekly objectives."));
      }
      const payload = (text ? (JSON.parse(text) as WeeklyObjectivesResponse) : {}) as WeeklyObjectivesResponse;
      applyWeeklyObjectivesPayload(payload);
      await refreshSummary().catch(() => undefined);
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
    refreshSummary,
    selectedObjectivesSection,
    selectedPillarObjectiveDraft,
    userId,
    wellbeingObjectiveDraft,
  ]);

  useEffect(() => {
    setSummaryPanelVisible(
      resolveSummaryPanelVisible(summary, readMorningSequenceState(userId, summary.today)),
    );
  }, [summary, userId]);

  useEffect(() => {
    setDisplayTheme(resolveCurrentDisplayTheme());
  }, []);

  useEffect(() => {
    if (!biometricsModalOpen) return;
    void loadLatestUrineTest();
    void loadWeeklyObjectives();
  }, [biometricsModalOpen, loadLatestUrineTest, loadWeeklyObjectives]);

  useEffect(() => {
    if (!biometricsModalOpen || !urineTestFlowOpen) return;
    setUrineCaptureNowMs(Date.now());
    const interval = window.setInterval(() => setUrineCaptureNowMs(Date.now()), 30000);
    return () => {
      window.clearInterval(interval);
    };
  }, [biometricsModalOpen, urineTestFlowOpen]);

  useEffect(() => {
    if (!biometricsModalOpen || !urineCaptureStartedAt) return;
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
    if (!summaryPanelVisible) return;
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
    window.addEventListener("healthsense-score-panel-visibility", onSummaryVisibilityChange as EventListener);
    return () => {
      window.removeEventListener("healthsense-score-panel-visibility", onSummaryVisibilityChange as EventListener);
    };
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
    setGuidedTrackingActive(guided);
    setTrackerReturnSurface(options?.returnSurface ?? null);
    setSelectedPillarKey(normalizedPillarKey);
    setDetail(null);
    setDraft({});
    setDetailError(null);
    setSaveError(null);
    const resolvedAnchorDate =
      anchorDate ||
      (!guided ? String(summary?.today || "").trim() || undefined : undefined);
    if (guided && typeof window !== "undefined") {
      window.dispatchEvent(
        new CustomEvent("healthsense-home-surface", {
          detail: {
            surface: "tracking",
          },
        }),
      );
    }
    await loadTrackerDetail(normalizedPillarKey, resolvedAnchorDate);
  }, [loadTrackerDetail, summary?.today]);

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

  const handleTrackerDismiss = useCallback(async () => {
    const currentPillarKey = String(detail?.pillar?.pillar_key || selectedPillarKey || "").trim().toLowerCase();
    if (guidedTrackingActive) {
      const nextPillarKey = currentPillarKey ? resolveNextPillarKey(currentPillarKey) : null;
      if (nextPillarKey) {
        await openTracker(nextPillarKey, undefined, { guided: true });
        return;
      }
      if (typeof window !== "undefined") {
        window.dispatchEvent(
          new CustomEvent("healthsense-home-surface", {
            detail: {
              surface: "habits",
            },
          }),
        );
      }
      closeTracker();
      return;
    }
    if (trackerReturnSurface && typeof window !== "undefined") {
      window.dispatchEvent(
        new CustomEvent("healthsense-home-surface", {
          detail: {
            surface: trackerReturnSurface,
          },
        }),
      );
    }
    closeTracker();
  }, [
    detail?.pillar?.pillar_key,
    guidedTrackingActive,
    openTracker,
    resolveNextPillarKey,
    selectedPillarKey,
    trackerReturnSurface,
  ]);

  const saveTracker = async () => {
    if (!detail?.pillar?.pillar_key || !canSave) return;
    setSaving(true);
    setSaveError(null);
    try {
      const entries = concepts.map((concept) => ({
        concept_key: concept.concept_key,
        value: draft[String(concept.concept_key || "").trim()],
      }));
      const res = await fetch(`/api/pillar-tracker/${encodeURIComponent(String(detail.pillar.pillar_key))}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          userId,
          score_date: activeDate || detail.pillar.today,
          entries,
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
              pillarKey: String(detail.pillar.pillar_key || "").trim().toLowerCase(),
              scoreDate: activeDate || detail.pillar.today || null,
              guided: guidedTrackingActive,
            },
          }),
        );
      }
      await refreshSummary().catch(() => undefined);
      const currentPillarKey = String(detail.pillar.pillar_key || "").trim().toLowerCase();
      const nextPillarKey = guidedTrackingActive ? resolveNextPillarKey(currentPillarKey) : null;
      if (nextPillarKey) {
        await openTracker(nextPillarKey, undefined, { guided: true });
        return;
      }
      if (guidedTrackingActive && typeof window !== "undefined") {
        window.dispatchEvent(
          new CustomEvent("healthsense-home-surface", {
            detail: {
              surface: "habits",
            },
          }),
        );
      } else if (trackerReturnSurface && typeof window !== "undefined") {
        window.dispatchEvent(
          new CustomEvent("healthsense-home-surface", {
            detail: {
              surface: trackerReturnSurface,
            },
          }),
        );
      }
      closeTracker();
    } catch (error) {
      setSaveError(error instanceof Error ? error.message : String(error));
    } finally {
      setSaving(false);
    }
  };

  const openDailyMenuSurface = (surface: "habits" | "insight" | "ask") => {
    if (typeof window !== "undefined") {
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
      const nextPillarKey = requestedPillarKey || orderedPillarKeys[0] || "";
      if (!nextPillarKey) return;
      void openTracker(nextPillarKey, undefined, {
        guided: detail?.guided !== false,
        returnSurface: detail?.returnSurface ?? null,
      });
    };
    window.addEventListener("healthsense-open-tracker", onOpenTracker as EventListener);
    return () => {
      window.removeEventListener("healthsense-open-tracker", onOpenTracker as EventListener);
    };
  }, [orderedPillarKeys, openTracker]);

  return (
    <>
      {summaryPanelVisible ? (
        <section
          ref={summaryPanelRef}
          className="rounded-[28px] border border-[#e7e1d6] bg-[#fffaf3] px-4 py-4 shadow-[0_30px_80px_-60px_rgba(30,27,22,0.45)] sm:px-5 sm:py-5"
        >
          <div className="mb-2 flex justify-end">
            <button
              type="button"
              onClick={() => void toggleDisplayTheme()}
              disabled={togglingDisplay}
              className={displayButtonClassName}
            >
              {displayLabel}
            </button>
          </div>
          <div className="relative">
            <div className="grid grid-cols-2 gap-3">
              {pillars.map((pillar) => {
                const pillarKey = String(pillar.pillar_key || "").trim().toLowerCase();
                const palette = getPillarPalette(pillarKey);
                const score = resolvePillarDisplayScore(pillar);
                return (
                  <button
                    key={pillarKey}
                    type="button"
                    onClick={() =>
                      void openTracker(pillarKey, String(summary?.today || "").trim() || undefined, {
                        guided: false,
                      })
                    }
                    className="rounded-2xl border border-[#efe7db] bg-white px-3 py-4 text-left transition hover:border-[#dccfbe]"
                  >
                    <div className="flex flex-col items-center text-center">
                      <WeeklyScoreRing value={score} tone={palette.accent} />
                      <p className="mt-3 text-sm font-semibold text-[#1e1b16]">{pillar.label}</p>
                    </div>
                  </button>
                );
              })}
            </div>

            <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
              <button
                type="button"
                onClick={() => void openObjectivesModal()}
                className="pointer-events-auto rounded-full transition hover:scale-[1.01] focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)] focus-visible:ring-offset-4"
                aria-label="Open weekly objectives"
              >
                <div className="relative">
                  <CombinedLogoRing value={combinedScore} />
                </div>
              </button>
            </div>
          </div>
          <div className="mt-4 space-y-2.5">
            <button
              type="button"
              onClick={handleReviewBiometricsPress}
              className="flex min-h-[4.75rem] w-full flex-col items-start justify-center rounded-[24px] border border-[#d9cdbb] bg-white px-5 py-3 text-left shadow-[0_18px_34px_-32px_rgba(30,27,22,0.4)]"
            >
              <div className="flex items-center gap-3">
                <BiometricsIcon />
                <span className="text-base font-semibold text-[#1e1b16]">Review biometrics</span>
              </div>
            </button>
            <button
              type="button"
              onClick={() => openDailyMenuSurface("habits")}
              className="flex min-h-[4.75rem] w-full flex-col items-start justify-center rounded-[24px] border border-[#d9cdbb] bg-white px-5 py-3 text-left shadow-[0_18px_34px_-32px_rgba(30,27,22,0.4)]"
            >
              <div className="flex items-center gap-3">
                <HabitStepsIcon />
                <span className="text-base font-semibold text-[#1e1b16]">Plan for the day</span>
              </div>
            </button>
            <button
              type="button"
              onClick={() => openDailyMenuSurface("insight")}
              className="flex min-h-[4.75rem] w-full flex-col items-start justify-center rounded-[24px] border border-[#d9cdbb] bg-white px-5 py-3 text-left shadow-[0_18px_34px_-32px_rgba(30,27,22,0.4)]"
            >
              <div className="flex items-center gap-3">
                <InsightIcon />
                <span className="text-base font-semibold text-[#1e1b16]">Today&apos;s focus</span>
              </div>
            </button>
            <button
              type="button"
              onClick={() => openDailyMenuSurface("ask")}
              className="flex min-h-[4.75rem] w-full flex-col items-start justify-center rounded-[24px] border border-[#d9cdbb] bg-white px-5 py-3 text-left shadow-[0_18px_34px_-32px_rgba(30,27,22,0.4)]"
            >
              <div className="flex items-center gap-3">
                <GiaMessageIcon />
                <span className="text-base font-semibold text-[#1e1b16]">Gia&apos;s message of the day</span>
              </div>
            </button>
          </div>
        </section>
      ) : null}

      {biometricsModalOpen ? (
        <div className="fixed inset-0 z-50 flex items-stretch justify-center bg-black/40 sm:items-center sm:px-3 sm:py-3">
          <div className="flex h-[100dvh] max-h-[100dvh] w-full max-w-2xl flex-col overflow-hidden bg-white pt-[env(safe-area-inset-top)] pb-[env(safe-area-inset-bottom)] shadow-[0_30px_80px_-60px_rgba(30,27,22,0.6)] sm:h-auto sm:max-h-[92vh] sm:rounded-[28px] sm:border sm:border-[#e7e1d6] sm:pt-0 sm:pb-0">
            <div className="shrink-0 border-b border-[#efe7db] bg-white px-4 py-4 sm:px-5">
              <div className="flex items-start justify-between gap-3">
                <div className="space-y-1">
                  <p className="text-xs uppercase tracking-[0.22em] text-[#6b6257]">
                    {activeBiomarkerExplanationDetail
                      ? activeBiomarkerExplanationDetail.title
                      : urineTestFlowOpen
                        ? "Urine test"
                        : biometricSourceCheckOpen
                          ? "Source check"
                        : "Biometrics"}
                  </p>
                  <p className="text-sm text-[#6b6257]">
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
                    className="rounded-full border border-[#d9cdbb] bg-white px-3 py-2 text-xs font-semibold uppercase tracking-[0.16em] text-[#5d5348]"
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
                    {restingHeartRateLoading || restingHeartRateEnabling ? "Syncing" : "Source check"}
                  </button>
                )}
              </div>
            </div>

            <div className="flex-1 overflow-y-auto px-4 py-4 sm:px-5">
              <div className="space-y-4">
                {!urineTestFlowOpen && activeBiomarkerExplanationDetail ? (
                  <div className="rounded-[24px] border border-[#efe7db] bg-white px-4 py-4">
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
                  <div className="rounded-[24px] border border-[#efe7db] bg-white px-4 py-4">
                    <div className="flex items-start justify-between gap-3">
                      <div className="space-y-1">
                        <p className="text-sm font-semibold text-[#1e1b16]">Take urine test</p>
                        <p className="text-sm text-[#6b6257]">
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
                      <div className="rounded-2xl border border-[#efe7db] bg-[#fffaf3] px-4 py-3">
                        <p className="text-xs font-semibold uppercase tracking-[0.16em] text-[#8c7f70]">Step 1</p>
                        <p className="mt-1 text-sm font-semibold text-[#1e1b16]">Prepare the strip</p>
                        <p className="mt-1 text-sm text-[#6b6257]">
                          Dip the Siemens Multistix strip, remove excess urine, and place it flat on a plain white background in good light.
                        </p>
                      </div>
                      <div className="rounded-2xl border border-[#efe7db] bg-[#fffaf3] px-4 py-3">
                        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                          <div>
                            <p className="text-xs font-semibold uppercase tracking-[0.16em] text-[#8c7f70]">Step 2</p>
                            <p className="mt-1 text-sm font-semibold text-[#1e1b16]">Start the read window</p>
                            <p className="mt-1 text-sm text-[#6b6257]">
                              {urineCaptureStartedAt
                                ? `${urineTimerSecondsLeft}s remaining. Take the photo when the timer reaches zero.`
                                : "Start after dipping. HealthSense captures at 60 seconds for the selected marker set."}
                            </p>
                          </div>
                          <button
                            type="button"
                            onClick={startUrineCaptureTimer}
                            disabled={urineTestSaving}
                            className="rounded-full border border-[#d9cdbb] bg-white px-4 py-2 text-[11px] font-semibold uppercase tracking-[0.16em] text-[#5d5348] disabled:cursor-not-allowed disabled:opacity-60"
                          >
                            Start timer
                          </button>
                        </div>
                      </div>
                      <div className="rounded-2xl border border-[#efe7db] bg-[#fffaf3] px-4 py-3">
                        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                          <div>
                            <p className="text-xs font-semibold uppercase tracking-[0.16em] text-[#8c7f70]">Step 3</p>
                            <p className="mt-1 text-sm font-semibold text-[#1e1b16]">Take the photo</p>
                            <p className="mt-1 text-sm text-[#6b6257]">
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
                              className="rounded-full border border-[#d9cdbb] bg-white px-4 py-2 text-[11px] font-semibold uppercase tracking-[0.16em] text-[#5d5348] disabled:cursor-not-allowed disabled:opacity-60"
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
                    <p className="mt-4 text-sm text-[#6b6257]">
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
                  <div className="rounded-[24px] border border-[#e7e1d6] bg-white px-4 py-4">
                        <div className="flex items-start justify-between gap-3">
                          <div className="space-y-1">
                            <p className="text-sm font-semibold text-[#1e1b16]">Biometric sources</p>
                            <p className="text-sm text-[#6b6257]">
                              Apple Health source data is used where available. Excluded metrics are not used by Gia.
                            </p>
                          </div>
                          <span className="rounded-full border border-[#f0d4ad] bg-[#fff8ef] px-3 py-1 text-[10px] font-semibold uppercase tracking-[0.14em] text-[#9b5b18]">
                            {restingHeartRateLoading || restingHeartRateEnabling ? "Syncing" : "Source check"}
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
                                      <span className="rounded-full border border-current/20 bg-white/70 px-2 py-1 text-[10px] font-semibold uppercase tracking-[0.12em]">
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
                                        : "border-[#d9cdbb] bg-white text-[#5d5348]"
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
                                              : "border-[#d9cdbb] bg-white text-[#5d5348]"
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
                    <div className="rounded-[24px] border border-[#e7e1d6] bg-[#fffaf3] px-4 py-4">
                        <div className="flex items-center justify-between gap-3">
                          <div className="flex items-center gap-2">
                            <p className="text-sm font-semibold text-[#1e1b16]">Training readiness</p>
                            <span
                              aria-label={resolveTrainingReadinessLabel(trainingReadinessStatus)}
                              className={`h-3 w-3 rounded-full ${trainingReadinessDotClassName}`}
                              role="img"
                            />
                          </div>
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
                            <p className="text-xs uppercase tracking-[0.16em] text-[#8c7f70]">
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

                        <div className="mt-5 border-t border-[#efe7db] pt-4">
                          <div className="flex items-center justify-between gap-3">
                            <p className="text-sm font-semibold text-[#1e1b16]">Resting HR</p>
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
                              <p className="text-xs uppercase tracking-[0.16em] text-[#8c7f70]">
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
                            <p className="mt-3 text-sm text-[#6b6257]">
                              Daily history will appear here once recent biometrics have been synced.
                            </p>
                          )}
                        </div>

                        <div className="mt-5 border-t border-[#efe7db] pt-4">
                          <div className="flex items-center justify-between gap-3">
                            <p className="text-sm font-semibold text-[#1e1b16]">HRV</p>
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
                              <p className="text-xs uppercase tracking-[0.16em] text-[#8c7f70]">
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
                            <p className="mt-3 text-sm text-[#6b6257]">
                              Daily HRV history will appear here once recent biometrics have been synced.
                            </p>
                          )}
                        </div>
                      </div>

                      <div className="rounded-[24px] border border-[#efe7db] bg-white px-4 py-4">
                        <div className="flex items-center justify-between gap-3">
                          <div className="flex items-center gap-2">
                            <p className="text-sm font-semibold text-[#1e1b16]">Activity status</p>
                            <span
                              aria-label={resolveActivityStatusLabel(activityStatus)}
                              className={`h-3 w-3 rounded-full ${activityDotClassName}`}
                              role="img"
                            />
                          </div>
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
                            <p className="text-xs uppercase tracking-[0.16em] text-[#8c7f70]">
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

                        <div className="mt-5 border-t border-[#efe7db] pt-4">
                          <div className="flex items-center justify-between gap-3">
                            <p className="text-sm font-semibold text-[#1e1b16]">Exercise minutes</p>
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
                              <p className="text-xs uppercase tracking-[0.16em] text-[#8c7f70]">
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
                            <p className="mt-3 text-sm text-[#6b6257]">
                              Daily exercise minutes will appear here once recent biometrics have been synced.
                            </p>
                          )}
                        </div>

                        <div className="mt-5 border-t border-[#efe7db] pt-4">
                          <div className="flex items-center justify-between gap-3">
                            <p className="text-sm font-semibold text-[#1e1b16]">Steps (000s)</p>
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
                              <p className="text-xs uppercase tracking-[0.16em] text-[#8c7f70]">
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
                            <p className="mt-3 text-sm text-[#6b6257]">
                              Daily step history will appear here once recent biometrics have been synced.
                            </p>
                          )}
                        </div>
                      </div>

                    <div className="rounded-[24px] border border-[#e7e1d6] bg-[#fffaf3] px-4 py-4">
                      <div className="flex items-center justify-between gap-3">
                        <p className="text-sm font-semibold text-[#1e1b16]">
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

            <div className="shrink-0 border-t border-[#efe7db] px-4 py-4 sm:px-5">
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
                className="w-full rounded-full border border-[#d9cdbb] bg-white px-4 py-3 text-center text-xs font-semibold uppercase tracking-[0.18em] text-[#5d5348]"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {objectivesModalOpen ? (
        <div className="fixed inset-0 z-50 flex items-stretch justify-center bg-black/40 sm:items-center sm:px-3 sm:py-3">
          <div className="flex h-[100dvh] max-h-[100dvh] w-full max-w-2xl flex-col overflow-hidden bg-white pt-[env(safe-area-inset-top)] pb-[env(safe-area-inset-bottom)] shadow-[0_30px_80px_-60px_rgba(30,27,22,0.6)] sm:h-auto sm:max-h-[92vh] sm:rounded-[28px] sm:border sm:border-[#e7e1d6] sm:pt-0 sm:pb-0">
            <div className="shrink-0 border-b border-[#efe7db] bg-white px-4 py-4 sm:px-5">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0 space-y-1">
                  <p className="text-xs uppercase tracking-[0.22em] text-[#6b6257]">
                    {selectedObjectivesSection
                      ? selectedObjectivesSection === "wellbeing"
                        ? "General objectives"
                        : selectedObjectivesPillar?.label || "Weekly objectives"
                      : "Weekly objectives"}
                  </p>
                  <p className="text-sm text-[#6b6257]">
                    {selectedObjectivesSection
                      ? selectedObjectivesSection === "wellbeing"
                        ? "Set optional general tracking preferences."
                        : "Choose your target for each concept this week."
                      : "Select a pillar to set or adjust this week's targets."}
                  </p>
                </div>
                {selectedObjectivesSection ? (
                  <button
                    type="button"
                    onClick={() => {
                      setSelectedObjectivesSection(null);
                      setWeeklyObjectivesError(null);
                    }}
                    className="rounded-full border border-[#d9cdbb] bg-white px-3 py-2 text-xs font-semibold uppercase tracking-[0.16em] text-[#5d5348]"
                  >
                    Back
                  </button>
                ) : null}
              </div>
            </div>

            <div className="flex-1 overflow-y-auto px-4 py-4 sm:px-5">
              {weeklyObjectivesLoading ? <p className="text-sm text-[#6b6257]">Loading weekly objectives…</p> : null}
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
                        className="flex min-h-[5.75rem] w-full flex-col items-start justify-center rounded-[28px] border border-[#d9cdbb] bg-white px-5 py-4 text-left shadow-[0_24px_40px_-36px_rgba(30,27,22,0.4)]"
                      >
                        <span className="flex w-full items-center justify-between gap-3">
                          <span className="flex min-w-0 items-center gap-3">
                            <WeeklyObjectiveSectionIcon sectionKey={sectionKey} />
                            <span className="truncate text-base font-semibold text-[#1e1b16]">
                              {formatWeeklyObjectiveSectionLabel(sectionKey, section?.label)}
                            </span>
                          </span>
                          {countLabel ? (
                            <span className="shrink-0 text-xs uppercase tracking-[0.16em] text-[#8c7f70]">
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
                      <div key={conceptKey} className="rounded-2xl border border-[#efe7db] bg-white px-4 py-4">
                        <div className="space-y-1">
                          <p className="text-sm font-semibold text-[#1e1b16]">{concept?.label}</p>
                          <p className="text-xs uppercase tracking-[0.18em] text-[#8c7f70]">
                            {concept?.metric_label || concept?.helper || conceptKey}
                          </p>
                          <p className="text-xs text-[#6b6257]">
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
                                    ? "border-[var(--accent)] bg-[var(--accent)] text-white"
                                    : "border-[#d9cdbb] bg-white text-[#5d5348]"
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
              ) : null}

              {!weeklyObjectivesLoading && selectedObjectivesSection === "wellbeing" ? (
                <div className="space-y-3">
                  <div className="rounded-2xl border border-[#efe7db] bg-[#fffaf3] px-4 py-4">
                    <div className="space-y-1">
                      <p className="text-sm font-semibold text-[#1e1b16]">Wearable connection</p>
                      <p className="text-xs text-[#6b6257]">
                        Connect a direct source where Apple Health cannot confirm HRV or exercise minutes reliably.
                      </p>
                    </div>
                    {biometricsActionError ? (
                      <p className="mt-3 rounded-2xl border border-[#f0d4ad] bg-[#fff8ef] px-3 py-2 text-xs text-[#9b5b18]">
                        {biometricsActionError}
                      </p>
                    ) : null}
                    <div className="mt-3 flex flex-wrap gap-2">
                      {BIOMETRIC_CONNECT_OPTIONS.map((option) => {
                        const pending = wearableConnectPending === option.provider;
                        return (
                          <button
                            key={`general-connect-${option.provider}`}
                            type="button"
                            onClick={() => void startBiometricWearableConnection(option.provider)}
                            disabled={!option.connectable || pending || Boolean(wearableConnectPending)}
                            className={`rounded-full border px-3 py-2 text-xs font-semibold uppercase tracking-[0.16em] disabled:cursor-not-allowed disabled:opacity-55 ${
                              option.connectable
                                ? "border-[#c54817] bg-[#c54817] text-white"
                                : "border-[#d9cdbb] bg-white text-[#5d5348]"
                            }`}
                          >
                            {pending
                              ? "Opening"
                              : option.connectable
                                ? `Connect ${option.label}`
                                : `${option.label} pending`}
                          </button>
                        );
                      })}
                    </div>
                  </div>
                  {wellbeingObjectiveItems.map((item) => {
                    const itemKey = String(item?.key || "").trim();
                    const selectedValue = String(wellbeingObjectiveDraft[itemKey] || item?.value || "off").trim() || "off";
                    return (
                      <div key={itemKey} className="rounded-2xl border border-[#efe7db] bg-white px-4 py-4">
                        <div className="space-y-1">
                          <p className="text-sm font-semibold text-[#1e1b16]">{item?.label}</p>
                          <p className="text-xs text-[#6b6257]">{item?.helper}</p>
                        </div>
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
                                    ? "border-[var(--accent)] bg-[var(--accent)] text-white"
                                    : "border-[#d9cdbb] bg-white text-[#5d5348]"
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
              ) : null}
            </div>

            <div className="shrink-0 border-t border-[#efe7db] px-4 py-4 sm:px-5">
              {selectedObjectivesSection ? (
                <div className="grid grid-cols-2 gap-2">
                  <button
                    type="button"
                    onClick={() => {
                      setSelectedObjectivesSection(null);
                      setWeeklyObjectivesError(null);
                    }}
                    className="rounded-full border border-[#d9cdbb] bg-white px-4 py-3 text-center text-xs font-semibold uppercase tracking-[0.18em] text-[#5d5348]"
                  >
                    Back
                  </button>
                  <button
                    type="button"
                    onClick={() => void saveObjectivesSection()}
                    disabled={weeklyObjectivesSaving}
                    className="rounded-full border border-[var(--accent)] bg-[var(--accent)] px-4 py-3 text-center text-xs font-semibold uppercase tracking-[0.18em] text-white disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    {weeklyObjectivesSaving ? "Saving…" : "Save objectives"}
                  </button>
                </div>
              ) : (
                <button
                  type="button"
                  onClick={closeObjectivesModal}
                  className="w-full rounded-full border border-[#d9cdbb] bg-white px-4 py-3 text-center text-xs font-semibold uppercase tracking-[0.18em] text-[#5d5348]"
                >
                  Close
                </button>
              )}
            </div>
          </div>
        </div>
      ) : null}

      {selectedPillarKey ? (
        <div className="fixed inset-0 z-50 flex items-stretch justify-center bg-black/40 sm:items-center sm:px-3 sm:py-3">
          <div className="flex h-[100dvh] max-h-[100dvh] w-full max-w-2xl flex-col overflow-hidden bg-white pt-[env(safe-area-inset-top)] pb-[env(safe-area-inset-bottom)] shadow-[0_30px_80px_-60px_rgba(30,27,22,0.6)] sm:h-auto sm:max-h-[92vh] sm:rounded-[28px] sm:border sm:border-[#e7e1d6] sm:pt-0 sm:pb-0">
            <div className="shrink-0 border-b border-[#efe7db] bg-white px-4 py-4 sm:px-5">
              <div className="min-w-0 space-y-1">
                <div className="flex min-w-0 items-center gap-3">
                  <WeeklyObjectiveSectionIcon sectionKey={trackerPillarKey} />
                  <p className="min-w-0 text-xs uppercase tracking-[0.22em] text-[#6b6257]">
                    {trackerPillarLabel}
                    {viewingCurrentWeek
                      ? savingPastDay
                        ? ` · Catching up ${activeLabel || "yesterday"}`
                        : " · Tracking today"
                      : " · Last week results"}
                  </p>
                </div>
                <p className="text-sm text-[#6b6257]">{trackerScoreLabel}</p>
                {detail?.pillar?.completed_days_count !== undefined || detail?.pillar?.streak_days !== undefined ? (
                  <p className="text-xs text-[#8c7f70]">
                    {`${detail?.pillar?.completed_days_count || 0}/7 days complete · ${detail?.pillar?.streak_days || 0} day check-in streak`}
                  </p>
                ) : null}
              </div>
            </div>

            <div className="flex-1 overflow-y-auto px-4 py-4 sm:px-5">
              {loadingDetail ? <p className="text-sm text-[#6b6257]">Loading tracker…</p> : null}
              {detailError ? <p className="text-sm text-[#8a3e1a]">{detailError}</p> : null}

              {detail && !loadingDetail ? (
                <div className="space-y-5">
                  {(detail.editable_dates || []).length > 1 ? (
                    <div className="flex flex-wrap gap-2">
                      {(detail.editable_dates || []).map((item) => {
                        const itemDate = String(item.date || "").trim();
                        const active = Boolean(item.is_active);
                        return (
                          <button
                            key={itemDate}
                            type="button"
                            disabled={!itemDate || active || saving}
                            onClick={() =>
                              void openTracker(
                                String(detail.pillar?.pillar_key || selectedPillarKey || ""),
                                itemDate,
                                {
                                  guided: guidedTrackingActive,
                                  returnSurface: trackerReturnSurface,
                                },
                              )
                            }
                            className={`rounded-full border px-3 py-2 text-xs font-semibold uppercase tracking-[0.16em] ${
                              active
                                ? "border-[#d6c3ab] bg-[#f6ede3] text-[#5d472d]"
                                : "border-[#d9cdbb] bg-white text-[#5d5348]"
                            } disabled:cursor-default disabled:opacity-100`}
                          >
                            {item.label}
                          </button>
                        );
                      })}
                    </div>
                  ) : null}

                  <div className="rounded-2xl border border-[#efe7db] bg-[#fffaf3] px-4 py-4">
                    <p className="text-xs uppercase tracking-[0.22em] text-[#6b6257]">
                      {viewingCurrentWeek ? "This week" : "Last week"}
                    </p>
                    <div className="mt-3 grid grid-cols-7 gap-2">
                      {(detail.days || []).map((day) => (
                        <div
                          key={day.date}
                          className={`rounded-xl border px-2 py-2 text-center text-[11px] ${completeDayTone(day.complete, day.score, day.is_today)}`}
                        >
                          <p className="font-semibold">{day.label}</p>
                          <p className="mt-1">{day.complete ? day.score ?? "Done" : day.is_today ? "Today" : "—"}</p>
                        </div>
                      ))}
                    </div>
                  </div>

                  {(detail.concepts || []).map((concept) => {
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
                          : "text-[#6b6257]";
                    return (
                      <div key={conceptKey} className="rounded-2xl border border-[#efe7db] bg-white px-4 py-4">
                        <div className="flex items-start justify-between gap-3">
                          <div>
                            <p className="text-sm font-semibold text-[#1e1b16]">{concept.label}</p>
                            <p className="mt-1 text-xs uppercase tracking-[0.18em] text-[#8c7f70]">{concept.helper}</p>
                            {targetLabel || okrStatusLabel ? (
                              <p className="mt-2 text-xs text-[#6b6257]">
                                {targetLabel}
                                {targetLabel && showInlineOkrProgress ? " · " : null}
                                {showInlineOkrProgress ? okrStatusDetail : null}
                                {(targetLabel || showInlineOkrProgress) && okrStatusLabel ? " · " : null}
                                {okrStatusLabel ? (
                                  <span className={`font-medium ${okrStatusTone}`}>{okrStatusLabel}</span>
                                ) : null}
                              </p>
                            ) : null}
                          </div>
                          <p className="text-xs text-[#8c7f70]">{`${concept.streak_days || 0} day streak`}</p>
                        </div>

                        <div className="mt-3 grid grid-cols-7 gap-2">
                          {(concept.week || []).map((day) => (
                            <div
                              key={`${conceptKey}-${day.date}`}
                              className={`rounded-xl border px-2 py-2 text-center text-[11px] ${circleDayTone(day.daily_status, day.is_active)}`}
                            >
                              <p className="font-semibold">{day.label}</p>
                              <p className="mt-1 truncate">{day.value_label || "—"}</p>
                            </div>
                          ))}
                        </div>

                        <div className="mt-3 flex flex-wrap gap-2">
                          {canEditActiveWeek
                            ? (concept.options || []).map((option) => {
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
                                    className={`rounded-full border px-3 py-2 text-xs font-semibold uppercase tracking-[0.16em] ${
                                      active
                                        ? "border-[var(--accent)] bg-[var(--accent)] text-white"
                                        : "border-[#d9cdbb] bg-white text-[#5d5348]"
                                    }`}
                                  >
                                    {option.label}
                                  </button>
                                );
                              })
                            : null}
                        </div>
                      </div>
                    );
                  })}

                  {saveError ? <p className="text-sm text-[#8a3e1a]">{saveError}</p> : null}
                </div>
                ) : null}
              </div>

            <div className="shrink-0 border-t border-[#efe7db] px-4 py-4 sm:px-5">
              {canEditActiveWeek ? (
                <div className="grid grid-cols-2 gap-2">
                  <button
                    type="button"
                    onClick={() => void handleTrackerDismiss()}
                    className="rounded-full border border-[#d9cdbb] bg-white px-4 py-3 text-center text-xs font-semibold uppercase tracking-[0.18em] text-[#5d5348]"
                  >
                    {closeTrackerLabel}
                  </button>
                  <button
                    type="button"
                    onClick={() => void saveTracker()}
                    disabled={!canSave}
                    className="rounded-full border border-[var(--accent)] bg-[var(--accent)] px-4 py-3 text-center text-xs font-semibold uppercase tracking-[0.18em] text-white disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    {saving
                      ? "Saving tracker…"
                      : "Save"}
                  </button>
                </div>
              ) : (
                <button
                  type="button"
                  onClick={() => void handleTrackerDismiss()}
                  className="w-full rounded-full border border-[#d9cdbb] bg-white px-4 py-3 text-center text-xs font-semibold uppercase tracking-[0.18em] text-[#5d5348]"
                >
                  {closeTrackerLabel}
                </button>
              )}
            </div>
          </div>
        </div>
      ) : null}
    </>
  );
}
