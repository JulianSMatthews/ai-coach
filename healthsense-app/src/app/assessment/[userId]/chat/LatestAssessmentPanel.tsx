"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type ChangeEvent } from "react";
import type {
  AppleHealthRestingHeartRateResponse,
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
type BiomarkerExplanationKey = "rhr" | "steps" | "urine";
type BiomarkerExplanationTone = "purple" | "green" | "amber" | "red" | "neutral";
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
const URINE_TEST_MAX_PHOTO_BYTES = 8 * 1024 * 1024;
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

function resolveRestingHeartRateTrendLabel(label?: string | null): string {
  const resolved = String(label || "").trim();
  if (!resolved) return "normal";
  return resolved.toLowerCase();
}

function resolveRestingHeartRateCompactTrendLabel(label?: string | null): string {
  const resolved = resolveRestingHeartRateTrendLabel(label);
  if (resolved === "optimal") return "opt";
  if (resolved === "elevated") return "elev";
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

function formatUrineStatusAbbreviation(marker: UrineTestMarker): string {
  const label = formatUrineStatusLabel(marker);
  const abbreviations: Record<string, string> = {
    clear: "clr",
    flagged: "flag",
    low: "low",
    ok: "ok",
    queued: "wait",
    raised: "high",
    ready: "—",
    review: "rev",
    trace: "trc",
    watch: "wch",
    well: "well",
  };
  return abbreviations[label] || label.slice(0, 4) || "—";
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
  theme,
  title,
}: {
  className?: string;
  description?: string;
  result: string;
  scaleRows: BiomarkerExplanationScaleRow[];
  theme: DisplayTheme;
  title: string;
}) {
  return (
    <div className={`${className} rounded-2xl border border-[#efe7db] bg-[#fffaf3] px-4 py-3 text-sm text-[#5d5348]`}>
      <p className="font-semibold text-[#1e1b16]">{title}</p>
      {description ? <p className="mt-2">{description}</p> : null}
      <p className="mt-2">{result}</p>
      <div className="mt-4 overflow-x-auto rounded-2xl border border-[#efe7db] bg-white">
        <table className="w-full min-w-[32rem] border-collapse text-left">
          <thead>
            <tr className="border-b border-[#efe7db] bg-[#fff7ec] text-[10px] font-semibold uppercase tracking-[0.16em] text-[#8c7f70]">
              <th className="px-3 py-2 font-semibold">Marker</th>
              <th className="px-3 py-2 font-semibold">Status</th>
              <th className="px-3 py-2 font-semibold">Meaning</th>
            </tr>
          </thead>
          <tbody>
            {scaleRows.map((row, index) => (
              <tr key={`${row.marker}-${row.status}-${index}`} className="border-b border-[#f3eadf] last:border-b-0">
                <td className="px-3 py-2 align-middle text-xs font-semibold text-[#1e1b16]">{row.marker}</td>
                <td className="px-3 py-2 align-middle">
                  <span
                    className={`inline-flex min-h-9 min-w-[4.5rem] items-center justify-center gap-2 rounded-xl border px-2 py-1 text-[10px] font-semibold uppercase tracking-[0.12em] ${resolveBiomarkerExplanationTone(theme, row.tone)}`}
                  >
                    {row.dotClassName ? <span className={`block h-4 w-4 rounded-full border-2 ${row.dotClassName}`} /> : null}
                    {row.status}
                  </span>
                </td>
                <td className="px-3 py-2 align-middle text-xs leading-relaxed text-[#6b6257]">{row.meaning}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
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
  const [urineTestFlowOpen, setUrineTestFlowOpen] = useState(false);
  const [activeBiomarkerExplanation, setActiveBiomarkerExplanation] = useState<BiomarkerExplanationKey | null>(null);
  const [restingHeartRateLoading, setRestingHeartRateLoading] = useState(false);
  const [restingHeartRateEnabling, setRestingHeartRateEnabling] = useState(false);
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
  const restingHeartRateValue = resolveRestingHeartRateValue(restingHeartRate?.resting_hr_bpm);
  const latestStepsMetricDate = String(restingHeartRate?.steps_metric_date || "").trim();
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
  const resolvedLatestStepsMetricDate = useMemo(() => {
    if (latestStepsMetricDate) return latestStepsMetricDate;
    const latestStepEntry = [...stepsHistory]
      .sort((left, right) => String(right?.metric_date || "").localeCompare(String(left?.metric_date || "")))[0];
    return String(latestStepEntry?.metric_date || "").trim();
  }, [latestStepsMetricDate, stepsHistory]);
  const restingHeartRateWeek = useMemo(
    () => buildBiometricWeek(restingHeartRateHistory, restingHeartRate?.metric_date),
    [restingHeartRate?.metric_date, restingHeartRateHistory],
  );
  const stepsWeek = useMemo(
    () => buildBiometricWeek(stepsHistory, resolvedLatestStepsMetricDate),
    [resolvedLatestStepsMetricDate, stepsHistory],
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
  const restingHeartRateBoxToneClassName = resolveRestingHeartRateBoxTone(displayTheme);
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
  const rhrExplanationResult = restingHeartRateValue
    ? `Latest result: ${restingHeartRateValue} bpm, currently shown as ${resolveRestingHeartRateTrendLabel(restingHeartRate?.trend_label)}. Resting HR is a recovery and load signal; lower than your usual range often suggests better recovery, while elevated can reflect stress, illness, poor sleep, dehydration, alcohol, or training load.`
    : "Latest result: no current Resting HR is available yet. Once Apple Health syncs a value, this section will compare it with your recent pattern.";
  const latestStepsValue = formatFullStepCount(latestStepsItem?.steps);
  const latestStepsStatus = resolveStepsStatus(latestStepsItem?.steps);
  const stepsExplanationResult = latestStepsValue
    ? `Latest result: ${latestStepsValue} steps, currently shown as ${resolveStepsStatusDescription(latestStepsStatus)}. Steps are a movement-volume marker; they help show whether the day included enough basic activity, independent of formal training.`
    : "Latest result: no recent step count is available yet. Once steps sync, this section shows your daily movement volume.";
  const urineStatusSummary = urineMarkers
    .map((marker) => `${marker.label}: ${formatUrineExplanationStatusLabel(marker)}`)
    .join("; ");
  const urineExplanationResult = urineTest?.available
    ? `Latest result: ${urineStatusSummary}. Use this as a quick screening and trend check; if a result looks unexpected, retake the strip in good light at the 60-second point.`
    : "Latest result: no urine test has been completed yet. Press Test to take a sample and populate these markers.";
  const rhrExplanationScaleRows: BiomarkerExplanationScaleRow[] = [
    {
      marker: "Resting HR",
      status: "Optimum",
      tone: "purple",
      meaning: "Lower than your recent pattern, which usually suggests recovery/load is moving in the right direction.",
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
    activeBiomarkerExplanation === "rhr"
      ? {
          title: "Resting HR",
          description: "Resting HR is your heart rate at rest. HealthSense compares it with your recent pattern rather than using one fixed target.",
          result: rhrExplanationResult,
          scaleRows: rhrExplanationScaleRows,
        }
      : activeBiomarkerExplanation === "steps"
        ? {
            title: "Steps",
            description: "Steps show daily movement volume. They do not replace training quality, but they are useful context for activity, energy, and routine.",
            result: stepsExplanationResult,
            scaleRows: stepsExplanationScaleRows,
          }
        : activeBiomarkerExplanation === "urine"
          ? {
              title: "Urine",
              description:
                "Urine uses the strip photo to group six dipstick readings into practical HealthSense markers. Hydration comes from specific gravity; UTI Signs combines leukocytes and nitrite; protein, blood, glucose, and ketones are screening signals that make most sense with context and repeat tests.",
              result: urineExplanationResult,
              scaleRows: urineExplanationScaleRows,
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
    setUrineTestFlowOpen(false);
    setBiometricsModalOpen(true);
    if (
      appleHealthSupported &&
      !restingHeartRateValue &&
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
    restingHeartRateValue,
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
      setUrineCaptureStartedAt(null);
      setUrineTimerSecondsLeft(0);
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

  const openObjectivesModal = useCallback(async () => {
    setObjectivesModalOpen(true);
    setSelectedObjectivesSection(null);
    await loadWeeklyObjectives();
  }, [loadWeeklyObjectives]);

  const closeObjectivesModal = useCallback(() => {
    setObjectivesModalOpen(false);
    setSelectedObjectivesSection(null);
    setWeeklyObjectivesError(null);
    setWeeklyObjectivesSaving(false);
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
          <div className="mt-5 space-y-3">
            <button
              type="button"
              onClick={handleReviewBiometricsPress}
              className="flex min-h-[6.25rem] w-full flex-col items-start justify-center rounded-[28px] border border-[#d9cdbb] bg-white px-5 py-4 text-left shadow-[0_24px_40px_-36px_rgba(30,27,22,0.4)]"
            >
              <div className="flex items-center gap-3">
                <BiometricsIcon />
                <span className="text-base font-semibold text-[#1e1b16]">Review biometrics</span>
              </div>
            </button>
            <button
              type="button"
              onClick={() => openDailyMenuSurface("habits")}
              className="flex min-h-[6.25rem] w-full flex-col items-start justify-center rounded-[28px] border border-[#d9cdbb] bg-white px-5 py-4 text-left shadow-[0_24px_40px_-36px_rgba(30,27,22,0.4)]"
            >
              <div className="flex items-center gap-3">
                <HabitStepsIcon />
                <span className="text-base font-semibold text-[#1e1b16]">Plan for the day</span>
              </div>
            </button>
            <button
              type="button"
              onClick={() => openDailyMenuSurface("insight")}
              className="flex min-h-[6.25rem] w-full flex-col items-start justify-center rounded-[28px] border border-[#d9cdbb] bg-white px-5 py-4 text-left shadow-[0_24px_40px_-36px_rgba(30,27,22,0.4)]"
            >
              <div className="flex items-center gap-3">
                <InsightIcon />
                <span className="text-base font-semibold text-[#1e1b16]">Insight of the day</span>
              </div>
            </button>
            <button
              type="button"
              onClick={() => openDailyMenuSurface("ask")}
              className="flex min-h-[6.25rem] w-full flex-col items-start justify-center rounded-[28px] border border-[#d9cdbb] bg-white px-5 py-4 text-left shadow-[0_24px_40px_-36px_rgba(30,27,22,0.4)]"
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
                        : "Biometrics"}
                  </p>
                  <p className="text-sm text-[#6b6257]">
                    {activeBiomarkerExplanationDetail
                      ? "Understand what this biomarker means, your latest result, and the scale."
                      : urineTestFlowOpen
                      ? "Follow the 60-second HealthSense capture flow before taking the photo."
                      : "Review your latest biometric measurements."}
                  </p>
                </div>
                {urineTestFlowOpen || activeBiomarkerExplanationDetail ? (
                  <button
                    type="button"
                    onClick={() => {
                      if (activeBiomarkerExplanationDetail) {
                        setActiveBiomarkerExplanation(null);
                        return;
                      }
                      setUrineTestFlowOpen(false);
                    }}
                    className="rounded-full border border-[#d9cdbb] bg-white px-3 py-2 text-xs font-semibold uppercase tracking-[0.16em] text-[#5d5348]"
                  >
                    {activeBiomarkerExplanationDetail ? "Close" : "Back"}
                  </button>
                ) : null}
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
                              {urineTestSaving ? "Saving" : urinePhotoCapturedAt || urineTest?.available ? "Retake photo" : "Take photo"}
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
                ) : (
                  <>
                    <div className="rounded-[24px] border border-[#efe7db] bg-white px-4 py-4">
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

                <div className="rounded-[24px] border border-[#efe7db] bg-white px-4 py-4">
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
                            <p className={`mt-3 whitespace-nowrap text-[12px] font-semibold leading-none tracking-[-0.02em] ${metricToneClassName}`}>
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
                        ? "Wellbeing objectives"
                        : selectedObjectivesPillar?.label || "Weekly objectives"
                      : "Weekly objectives"}
                  </p>
                  <p className="text-sm text-[#6b6257]">
                    {selectedObjectivesSection
                      ? selectedObjectivesSection === "wellbeing"
                        ? "Set optional wellbeing tracking preferences."
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
                        <span className="text-base font-semibold text-[#1e1b16]">
                          {section?.label || sectionKey.replace(/_/g, " ")}
                        </span>
                        {countLabel ? (
                          <span className="mt-2 text-xs uppercase tracking-[0.16em] text-[#8c7f70]">{countLabel}</span>
                        ) : null}
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
                <p className="text-xs uppercase tracking-[0.22em] text-[#6b6257]">
                  {(detail?.pillar?.label || selectedPillarKey.replace(/_/g, " ")) +
                    (viewingCurrentWeek
                      ? savingPastDay
                        ? ` · Catching up ${activeLabel || "yesterday"}`
                        : " · Tracking today"
                      : " · Last week results")}
                </p>
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
