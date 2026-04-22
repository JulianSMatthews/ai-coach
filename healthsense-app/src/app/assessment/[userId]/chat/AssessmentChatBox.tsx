"use client";

import Image from "next/image";
import { useSearchParams } from "next/navigation";
import { FormEvent, KeyboardEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import type {
  DailyHabitPlanItem,
  DailyHabitPlanResponse,
  EducationPlanTodayResponse,
  PillarTrackerSummaryResponse,
} from "@/lib/api";
import { getPillarPalette } from "@/lib/pillars";
import { ProgressBar, ScoreRing } from "@/components/ui";
import AssessmentPromptCard, {
  type AssessmentCurrentPrompt,
  type AssessmentIntroAvatar,
  type AssessmentPromptOption,
  type AssessmentPromptSection,
} from "./AssessmentPromptCard";
import LeadAssessmentBranding from "./LeadAssessmentBranding";
import RealtimeSummaryAvatar from "./RealtimeSummaryAvatar";

type ChatMessage = {
  id?: number;
  direction?: string;
  channel?: string;
  text?: string;
  quick_replies?: string[];
  selected_quick_reply?: string | null;
  selected_quick_reply_label?: string | null;
  media_url?: string | null;
  created_at?: string | null;
};

type ChatResponse = {
  ok?: boolean;
  handled?: boolean;
  needs_start?: boolean;
  has_active_session?: boolean;
  identity_required?: boolean;
  current_prompt?: unknown;
  result_summary?: unknown;
  messages?: ChatMessage[];
  outbox?: ChatMessage[];
  user_id?: number | string;
  next_path?: string;
  error?: string;
};

type AssessmentResultPillar = {
  pillar_key: string;
  label: string;
  score: number;
};

type AssessmentResultSummary = {
  run_id?: number;
  finished_at?: string | null;
  combined: number;
  pillars: AssessmentResultPillar[];
  readiness?: {
    title?: string | null;
    score?: number | null;
    level?: string | null;
    note?: string | null;
  } | null;
  reflection?: {
    selected_pillar?: string | null;
    selected_label?: string | null;
    selected_score?: number | null;
    top_pillar?: string | null;
    top_label?: string | null;
    top_score?: number | null;
    matches_top?: boolean | null;
  } | null;
};

type AssessmentChatBoxProps = {
  userId: string;
  assessmentCompleted?: boolean;
  isLeadGuest?: boolean;
  leadToken?: string;
  showLeadBranding?: boolean;
  introAvatar?: AssessmentIntroAvatar | null;
  coachProductAvatar?: AssessmentIntroAvatar | null;
  introAvatarEnabledOverride?: boolean | null;
  initialTrackerSummary?: PillarTrackerSummaryResponse | null;
};

type AssessmentCompletionSummaryMedia = {
  text: string | null;
  audioUrl: string | null;
  avatarUrl: string | null;
  avatarStatus: string | null;
  avatarError: string | null;
  avatarMode: string | null;
  realtimeEnabled: boolean;
  realtimeMaxSessionSeconds: number | null;
  realtimeMaxReplays: number | null;
};

type HomeSurface = "tracking" | "habits" | "insight" | "ask";
type HomeSurfaceEntryMode = "guided" | "summary";
type EducationQuizAnswerValue = string | number | boolean | string[] | null;
type EducationQuizQuestion = NonNullable<NonNullable<EducationPlanTodayResponse["quiz"]>["questions"]>[number];
type GiaMessageRealtimeSessionResponse = {
  session_id?: string;
  speech_token?: string;
  speech_region?: string;
  ssml?: string;
  summary_text?: string;
  error?: string;
};

const HOME_SURFACE_SEQUENCE: HomeSurface[] = ["tracking", "habits", "insight", "ask"];
const TRACKING_STEP_PILLARS = ["Nutrition", "Training", "Resilience", "Recovery"];
const MORNING_SEQUENCE_STORAGE_PREFIX = "hs:morning-sequence-complete";
type MorningSequenceState = "idle" | "in_progress" | "completed";
const DAY_PLAN_MOMENT_ORDER = ["morning", "midday", "afternoon", "evening"] as const;

const HOME_SURFACE_COPY: Record<
  HomeSurface,
  {
    eyebrow: string;
    title: string;
    description: string;
    nextLabel: string | null;
  }
> = {
  tracking: {
    eyebrow: "Step 1 of 4",
    title: "Track progress",
    description: "Start by completing today's tracking. We will take you through each pillar one at a time.",
    nextLabel: null,
  },
  habits: {
    eyebrow: "Step 2 of 4",
    title: "Today's plan",
    description: "Review the key moments for today, then continue to today's lesson.",
    nextLabel: "Start lesson",
  },
  insight: {
    eyebrow: "Step 3 of 4",
    title: "Today's focus",
    description: "Watch today's short lesson, complete the quick check, then Gia will bring it together with your plan and tracker results.",
    nextLabel: "Continue to Gia's message",
  },
  ask: {
    eyebrow: "Step 4 of 4",
    title: "Gia's message",
    description: "",
    nextLabel: null,
  },
};

function parseApiError(text: string, fallback: string) {
  if (!text) return fallback;
  try {
    const parsed = JSON.parse(text) as { error?: string; detail?: string };
    const message = parsed.error || parsed.detail || text;
    const normalized = String(message || "").trim().toLowerCase();
    if (!normalized || normalized === "internal server error") {
      return fallback;
    }
    if (normalized.includes("email already in use")) {
      return "That email address is already linked to another account.";
    }
    if (normalized.includes("phone already in use")) {
      return "That mobile number is already linked to another account.";
    }
    if (normalized.includes("mobile number required for whatsapp")) {
      return "Add a mobile number if you want it saved on your account.";
    }
    if (normalized.includes("mobile number required")) {
      return "Enter your mobile number, ideally with country code.";
    }
    if (normalized.includes("phone required")) {
      return "Enter your mobile number, ideally with country code.";
    }
    if (normalized.includes("phone must be a valid international number")) {
      return "Enter a valid mobile number, ideally with country code.";
    }
    if (normalized.includes("password is required")) {
      return "Create a password to finish setting up your app login.";
    }
    return message;
  } catch {
    const normalized = String(text || "").trim().toLowerCase();
    if (!normalized || normalized === "internal server error") {
      return fallback;
    }
    if (normalized.includes("email already in use")) {
      return "That email address is already linked to another account.";
    }
    if (normalized.includes("phone already in use")) {
      return "That mobile number is already linked to another account.";
    }
    if (normalized.includes("mobile number required for whatsapp")) {
      return "Add a mobile number if you want it saved on your account.";
    }
    if (normalized.includes("mobile number required")) {
      return "Enter your mobile number, ideally with country code.";
    }
    if (normalized.includes("phone required")) {
      return "Enter your mobile number, ideally with country code.";
    }
    if (normalized.includes("phone must be a valid international number")) {
      return "Enter a valid mobile number, ideally with country code.";
    }
    return text;
  }
}

function normalizeDayPlanMomentKey(value: string | null | undefined): string {
  const token = String(value || "")
    .trim()
    .toLowerCase()
    .replaceAll("-", "_")
    .replaceAll(" ", "_");
  if (token === "pre_training" || token === "pretraining" || token === "training") {
    return "afternoon";
  }
  return token;
}

function mergeDailyPlanItems(
  primaryItems: DailyHabitPlanItem[],
  fallbackItems: DailyHabitPlanItem[],
): DailyHabitPlanItem[] {
  const keepFilled = (items: DailyHabitPlanItem[]) =>
    items.filter((item) => {
      const title = String(item?.title || "").trim();
      const detail = String(item?.detail || "").trim();
      return Boolean(title || detail);
    });

  const primary = keepFilled(primaryItems);
  const fallback = keepFilled(fallbackItems);

  const primaryByMoment = new Map<string, DailyHabitPlanItem>();
  const fallbackByMoment = new Map<string, DailyHabitPlanItem>();

  for (const item of primary) {
    const key = normalizeDayPlanMomentKey(item?.moment_key || item?.moment_label);
    if (key && !primaryByMoment.has(key)) primaryByMoment.set(key, item);
  }
  for (const item of fallback) {
    const key = normalizeDayPlanMomentKey(item?.moment_key || item?.moment_label);
    if (key && !fallbackByMoment.has(key)) fallbackByMoment.set(key, item);
  }

  const merged: DailyHabitPlanItem[] = [];
  const seenIds = new Set<string>();
  const seenMoments = new Set<string>();
  const seenTextKeys = new Set<string>();

  const pushItem = (item: DailyHabitPlanItem | undefined) => {
    if (!item) return;
    const momentKey = normalizeDayPlanMomentKey(item?.moment_key || item?.moment_label);
    const itemId = String(item.id || "").trim();
    const textKey = `${String(item.title || "").trim().toLowerCase()}::${String(item.detail || "").trim().toLowerCase()}`;
    if (itemId && seenIds.has(itemId)) return;
    if (momentKey && seenMoments.has(momentKey)) return;
    if (!itemId && textKey !== "::" && seenTextKeys.has(textKey)) return;
    if (itemId) seenIds.add(itemId);
    if (momentKey) seenMoments.add(momentKey);
    if (textKey !== "::") seenTextKeys.add(textKey);
    merged.push(item);
  };

  for (const momentKey of DAY_PLAN_MOMENT_ORDER) {
    pushItem(primaryByMoment.get(momentKey) || fallbackByMoment.get(momentKey));
  }

  for (const item of [...primary, ...fallback]) {
    const momentKey = normalizeDayPlanMomentKey(item?.moment_key || item?.moment_label);
    if (momentKey && DAY_PLAN_MOMENT_ORDER.includes(momentKey as (typeof DAY_PLAN_MOMENT_ORDER)[number])) {
      continue;
    }
    pushItem(item);
  }

  return merged.slice(0, DAY_PLAN_MOMENT_ORDER.length);
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

function normalizeMessages(raw: unknown): ChatMessage[] {
  if (!Array.isArray(raw)) return [];
  const normalized: ChatMessage[] = [];
  raw.forEach((msg) => {
    if (!msg || typeof msg !== "object") return;
    const row = msg as Record<string, unknown>;
    const text = typeof row.text === "string" ? row.text : "";
    if (!text) return;
    const quickReplies = Array.isArray(row.quick_replies)
      ? row.quick_replies
          .map((item) => (typeof item === "string" ? item.trim() : ""))
          .filter((item) => Boolean(item))
          .slice(0, 6)
      : [];
    normalized.push({
      id: typeof row.id === "number" ? row.id : undefined,
      direction: typeof row.direction === "string" ? row.direction : "",
      channel: typeof row.channel === "string" ? row.channel : "app",
      text,
      quick_replies: quickReplies,
      selected_quick_reply:
        typeof row.selected_quick_reply === "string" ? row.selected_quick_reply : null,
      selected_quick_reply_label:
        typeof row.selected_quick_reply_label === "string" ? row.selected_quick_reply_label : null,
      media_url: typeof row.media_url === "string" ? row.media_url : null,
      created_at: typeof row.created_at === "string" ? row.created_at : null,
    });
  });
  return normalized;
}

function normalizePromptOption(raw: unknown): AssessmentPromptOption | null {
  if (!raw || typeof raw !== "object") return null;
  const row = raw as Record<string, unknown>;
  const value = typeof row.value === "string" ? row.value.trim() : "";
  const label = typeof row.label === "string" ? row.label.trim() : "";
  if (!value || !label) return null;
  return {
    value,
    label,
    detail: typeof row.detail === "string" ? row.detail : null,
  };
}

function normalizePromptSection(raw: unknown): AssessmentPromptSection | null {
  if (!raw || typeof raw !== "object") return null;
  const row = raw as Record<string, unknown>;
  const key = typeof row.key === "string" ? row.key.trim() : "";
  const label = typeof row.label === "string" ? row.label.trim() : "";
  const index = Number.parseInt(String(row.index ?? ""), 10);
  const value = Number.parseInt(String(row.value ?? ""), 10);
  const answered = Number.parseInt(String(row.answered ?? ""), 10);
  const total = Number.parseInt(String(row.total ?? ""), 10);
  const status = typeof row.status === "string" ? row.status.trim() : "";
  if (!key || !label || !Number.isFinite(index) || !Number.isFinite(value) || !Number.isFinite(answered) || !Number.isFinite(total)) {
    return null;
  }
  if (status !== "complete" && status !== "active" && status !== "upcoming") {
    return null;
  }
  return {
    key,
    label,
    index,
    value,
    answered,
    total,
    status,
  };
}

function normalizePromptResultPreview(
  raw: unknown,
): AssessmentCurrentPrompt["result_preview"] {
  if (!raw || typeof raw !== "object") return null;
  const row = raw as Record<string, unknown>;
  const pillars = Array.isArray(row.pillars)
    ? row.pillars.flatMap((entry) => {
        if (!entry || typeof entry !== "object") return [];
        const pillarRow = entry as Record<string, unknown>;
        const pillarKey = typeof pillarRow.pillar_key === "string" ? pillarRow.pillar_key.trim() : "";
        const label = typeof pillarRow.label === "string" ? pillarRow.label.trim() : "";
        if (!pillarKey || !label) return [];
        return [
          {
            pillar_key: pillarKey,
            label,
            score: Number.isFinite(Number(pillarRow.score)) ? Number(pillarRow.score) : null,
            complete: typeof pillarRow.complete === "boolean" ? pillarRow.complete : null,
          },
        ];
      })
    : [];

  return {
    combined: Number.isFinite(Number(row.combined)) ? Number(row.combined) : null,
    pillars,
    readiness:
      row.readiness && typeof row.readiness === "object"
        ? {
            label:
              typeof (row.readiness as Record<string, unknown>).label === "string"
                ? String((row.readiness as Record<string, unknown>).label)
                : "Habit Readiness",
            score: Number.isFinite(Number((row.readiness as Record<string, unknown>).score))
              ? Number((row.readiness as Record<string, unknown>).score)
              : null,
            complete:
              typeof (row.readiness as Record<string, unknown>).complete === "boolean"
                ? Boolean((row.readiness as Record<string, unknown>).complete)
                : null,
          }
        : null,
    latest_pillar_key:
      typeof row.latest_pillar_key === "string" ? String(row.latest_pillar_key) : null,
    latest_pillar_label:
      typeof row.latest_pillar_label === "string" ? String(row.latest_pillar_label) : null,
    latest_pillar_score:
      Number.isFinite(Number(row.latest_pillar_score)) ? Number(row.latest_pillar_score) : null,
  };
}

function normalizeCurrentPrompt(raw: unknown): AssessmentCurrentPrompt | null {
  if (!raw || typeof raw !== "object") return null;
  const row = raw as Record<string, unknown>;
  const kind = typeof row.kind === "string" ? row.kind.trim() : "";
  if (kind !== "concept_scale" && kind !== "readiness_scale" && kind !== "pillar_reflection" && kind !== "pillar_result") return null;
  const question = typeof row.question === "string" ? row.question.trim() : "";
  if (!question) return null;
  const options = Array.isArray(row.options)
    ? row.options.map(normalizePromptOption).filter((item): item is AssessmentPromptOption => Boolean(item))
    : [];
  if (!options.length) return null;
  const sections = Array.isArray(row.sections)
    ? row.sections.map(normalizePromptSection).filter((item): item is AssessmentPromptSection => Boolean(item))
    : [];
  return {
    kind,
    section_key: typeof row.section_key === "string" ? row.section_key : "",
    section_label: typeof row.section_label === "string" ? row.section_label : "Assessment",
    section_index: Number.parseInt(String(row.section_index ?? ""), 10) || 1,
    section_total: Number.parseInt(String(row.section_total ?? ""), 10) || Math.max(sections.length, 1),
    section_question_index: Number.parseInt(String(row.section_question_index ?? ""), 10) || 1,
    section_question_total: Number.parseInt(String(row.section_question_total ?? ""), 10) || options.length,
    question_position: Number.parseInt(String(row.question_position ?? ""), 10) || 1,
    question_total: Number.parseInt(String(row.question_total ?? ""), 10) || 1,
    concept_code: typeof row.concept_code === "string" ? row.concept_code : undefined,
    concept_label: typeof row.concept_label === "string" ? row.concept_label : undefined,
    question,
    measure_label: typeof row.measure_label === "string" ? row.measure_label : null,
    hint: typeof row.hint === "string" ? row.hint : null,
    result_preview: normalizePromptResultPreview(row.result_preview),
    options,
    sections,
  };
}

function normalizeResultPillar(raw: unknown): AssessmentResultPillar | null {
  if (!raw || typeof raw !== "object") return null;
  const row = raw as Record<string, unknown>;
  const pillarKey = typeof row.pillar_key === "string" ? row.pillar_key.trim() : "";
  const label = typeof row.label === "string" ? row.label.trim() : "";
  const score = Number.parseInt(String(row.score ?? ""), 10);
  if (!pillarKey || !label || !Number.isFinite(score)) return null;
  return {
    pillar_key: pillarKey,
    label,
    score,
  };
}

function normalizeResultSummary(raw: unknown): AssessmentResultSummary | null {
  if (!raw || typeof raw !== "object") return null;
  const row = raw as Record<string, unknown>;
  const combined = Number.parseInt(String(row.combined ?? ""), 10);
  if (!Number.isFinite(combined)) return null;
  const pillars = Array.isArray(row.pillars)
    ? row.pillars.map(normalizeResultPillar).filter((item): item is AssessmentResultPillar => Boolean(item))
    : [];
  return {
    run_id: Number.parseInt(String(row.run_id ?? ""), 10) || undefined,
    finished_at: typeof row.finished_at === "string" ? row.finished_at : null,
    combined,
    pillars,
    readiness:
      row.readiness && typeof row.readiness === "object"
        ? {
            title:
              typeof (row.readiness as Record<string, unknown>).title === "string"
                ? String((row.readiness as Record<string, unknown>).title)
                : null,
            score:
              row.readiness && Number.isFinite(Number((row.readiness as Record<string, unknown>).score))
                ? Number((row.readiness as Record<string, unknown>).score)
                : null,
            level:
              typeof (row.readiness as Record<string, unknown>).level === "string"
                ? String((row.readiness as Record<string, unknown>).level)
                : typeof (row.readiness as Record<string, unknown>).label === "string"
                  ? String((row.readiness as Record<string, unknown>).label)
                : null,
            note:
              typeof (row.readiness as Record<string, unknown>).note === "string"
                ? String((row.readiness as Record<string, unknown>).note)
                : null,
          }
        : null,
    reflection:
      row.reflection && typeof row.reflection === "object"
        ? {
            selected_pillar:
              typeof (row.reflection as Record<string, unknown>).selected_pillar === "string"
                ? String((row.reflection as Record<string, unknown>).selected_pillar)
                : null,
            selected_label:
              typeof (row.reflection as Record<string, unknown>).selected_label === "string"
                ? String((row.reflection as Record<string, unknown>).selected_label)
                : null,
            selected_score:
              Number.isFinite(Number((row.reflection as Record<string, unknown>).selected_score))
                ? Number((row.reflection as Record<string, unknown>).selected_score)
                : null,
            top_pillar:
              typeof (row.reflection as Record<string, unknown>).top_pillar === "string"
                ? String((row.reflection as Record<string, unknown>).top_pillar)
                : null,
            top_label:
              typeof (row.reflection as Record<string, unknown>).top_label === "string"
                ? String((row.reflection as Record<string, unknown>).top_label)
                : null,
            top_score:
              Number.isFinite(Number((row.reflection as Record<string, unknown>).top_score))
                ? Number((row.reflection as Record<string, unknown>).top_score)
                : null,
            matches_top:
              typeof (row.reflection as Record<string, unknown>).matches_top === "boolean"
                ? Boolean((row.reflection as Record<string, unknown>).matches_top)
                : null,
          }
        : null,
  };
}

function resultPillarExtremes(pillars: AssessmentResultPillar[]): {
  strongest: AssessmentResultPillar | null;
  weakest: AssessmentResultPillar | null;
} {
  if (!pillars.length) {
    return { strongest: null, weakest: null };
  }
  const sorted = [...pillars].sort((a, b) => a.score - b.score);
  return {
    weakest: sorted[0] || null,
    strongest: sorted[sorted.length - 1] || null,
  };
}

function sortResultPillars(pillars: AssessmentResultPillar[]): AssessmentResultPillar[] {
  return [...pillars].sort((a, b) => b.score - a.score);
}

function normalizeCompletionSummaryMedia(raw: unknown): AssessmentCompletionSummaryMedia {
  if (!raw || typeof raw !== "object") {
    return {
      text: null,
      audioUrl: null,
      avatarUrl: null,
      avatarStatus: null,
      avatarError: null,
      avatarMode: null,
      realtimeEnabled: false,
      realtimeMaxSessionSeconds: null,
      realtimeMaxReplays: null,
    };
  }
  const payload = raw as Record<string, unknown>;
  const row =
    payload.narratives && typeof payload.narratives === "object"
      ? (payload.narratives as Record<string, unknown>)
      : payload;
  const rawMaxSessionSeconds = Number(row.completion_summary_realtime_max_session_seconds);
  const rawMaxReplays = Number(row.completion_summary_realtime_max_replays);
  return {
    text: typeof row.completion_summary_text === "string" ? row.completion_summary_text : null,
    audioUrl:
      typeof row.completion_summary_audio_url === "string" ? row.completion_summary_audio_url : null,
    avatarUrl:
      typeof row.completion_summary_avatar_url === "string" ? row.completion_summary_avatar_url : null,
    avatarStatus:
      typeof row.completion_summary_avatar_status === "string"
        ? row.completion_summary_avatar_status
        : null,
    avatarError:
      typeof row.completion_summary_avatar_error === "string"
        ? row.completion_summary_avatar_error
        : null,
    avatarMode:
      typeof row.completion_summary_avatar_mode === "string" ? row.completion_summary_avatar_mode : null,
    realtimeEnabled: Boolean(row.completion_summary_realtime_enabled),
    realtimeMaxSessionSeconds: Number.isFinite(rawMaxSessionSeconds) ? rawMaxSessionSeconds : null,
    realtimeMaxReplays: Number.isFinite(rawMaxReplays) ? rawMaxReplays : null,
  };
}


function isTruthyToken(value: string | null | undefined): boolean {
  const token = String(value || "").trim().toLowerCase();
  return token === "1" || token === "true" || token === "yes" || token === "on";
}

function parsePositiveUserId(value: unknown): number | null {
  const token = Number.parseInt(String(value ?? "").trim(), 10);
  if (!Number.isFinite(token) || token <= 0) return null;
  return token;
}

function looksLikePhone(value: string): boolean {
  const token = String(value || "").trim();
  if (!token) return false;
  const digits = token.replace(/\D/g, "");
  return digits.length >= 8;
}

function isLikelyVideoUrl(value: string): boolean {
  const token = String(value || "").trim().toLowerCase();
  if (!token) return false;
  return /\.(mp4|m4v|mov|webm)(?:$|[?#])/i.test(token);
}

function firstNonEmptyString(...values: unknown[]): string {
  for (const value of values) {
    const token = String(value || "").trim();
    if (token) return token;
  }
  return "";
}

function educationQuizOptionLabel(option: unknown): string {
  if (typeof option === "string" || typeof option === "number" || typeof option === "boolean") {
    return String(option).trim();
  }
  if (option && typeof option === "object") {
    const row = option as Record<string, unknown>;
    return String(row.label || row.text || row.value || "").trim();
  }
  return "";
}

function educationQuizOptions(question: EducationQuizQuestion | null | undefined): string[] {
  const options = Array.isArray(question?.options) ? question.options : [];
  return options.map(educationQuizOptionLabel).filter((option) => Boolean(option));
}

function educationQuizAnswerLabel(answer: unknown): string {
  if (Array.isArray(answer)) {
    return answer.map(educationQuizOptionLabel).filter(Boolean).join(", ");
  }
  return educationQuizOptionLabel(answer);
}

function fallbackLocalIsoDate(): string {
  const now = new Date();
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function resolveMorningSequenceDay(summary?: PillarTrackerSummaryResponse | null): string {
  const token = String(summary?.today || "").trim();
  return token || fallbackLocalIsoDate();
}

function morningSequenceStorageKey(userId: string, dayToken: string): string | null {
  const normalizedUserId = String(userId || "").trim();
  const normalizedDayToken = String(dayToken || "").trim();
  if (!normalizedUserId || !normalizedDayToken) return null;
  return `${MORNING_SEQUENCE_STORAGE_PREFIX}:${normalizedUserId}:${normalizedDayToken}`;
}

function readMorningSequenceState(userId: string, dayToken: string): MorningSequenceState {
  if (typeof window === "undefined") return "idle";
  const key = morningSequenceStorageKey(userId, dayToken);
  if (!key) return "idle";
  try {
    const raw = String(window.localStorage.getItem(key) || "").trim().toLowerCase();
    if (raw === "completed" || raw === "1") return "completed";
    if (raw === "in_progress") return "in_progress";
    return "idle";
  } catch {
    return "idle";
  }
}

function writeMorningSequenceState(userId: string, dayToken: string, state: MorningSequenceState): void {
  if (typeof window === "undefined") return;
  const key = morningSequenceStorageKey(userId, dayToken);
  if (!key) return;
  try {
    if (state !== "idle") {
      window.localStorage.setItem(key, state);
      return;
    }
    window.localStorage.removeItem(key);
  } catch {
    // Ignore storage failures and fall back to the in-memory state.
  }
}

function resolveJourneyCompleted(options: {
  assessmentCompleted: boolean;
  summary: PillarTrackerSummaryResponse | null | undefined;
  sequenceState: MorningSequenceState;
}): boolean {
  const { assessmentCompleted, summary, sequenceState } = options;
  if (!assessmentCompleted) return false;
  if (sequenceState === "completed") return true;
  if (sequenceState === "in_progress") return false;
  return isDailyCheckInComplete(summary);
}

export default function AssessmentChatBox({
  userId,
  assessmentCompleted = false,
  isLeadGuest = false,
  leadToken,
  showLeadBranding = false,
  introAvatar = null,
  coachProductAvatar = null,
  introAvatarEnabledOverride = null,
  initialTrackerSummary = null,
}: AssessmentChatBoxProps) {
  const searchParams = useSearchParams();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [status, setStatus] = useState<string | null>(null);
  const [hasActiveSession, setHasActiveSession] = useState(false);
  const [identityRequired, setIdentityRequired] = useState(false);
  const [currentPrompt, setCurrentPrompt] = useState<AssessmentCurrentPrompt | null>(null);
  const [resultSummary, setResultSummary] = useState<AssessmentResultSummary | null>(null);
  const [selectedPromptValue, setSelectedPromptValue] = useState<string | null>(null);
  const [claimFirstName, setClaimFirstName] = useState("");
  const [claimSurname, setClaimSurname] = useState("");
  const [claimPhone, setClaimPhone] = useState("");
  const [claimPassword, setClaimPassword] = useState("");
  const [claimConfirmPassword, setClaimConfirmPassword] = useState("");
  const [claiming, setClaiming] = useState(false);
  const [claimError, setClaimError] = useState<string | null>(null);
  const [claimSuccess, setClaimSuccess] = useState(false);
  const [claimNextPath, setClaimNextPath] = useState("");
  const [showCoachingPlan, setShowCoachingPlan] = useState(false);
  const [completionSummaryMedia, setCompletionSummaryMedia] =
    useState<AssessmentCompletionSummaryMedia | null>(null);
  const [completionSummaryLoading, setCompletionSummaryLoading] = useState(false);
  const [completionSummaryError, setCompletionSummaryError] = useState<string | null>(null);
  const [loadedCompletionSummaryRunId, setLoadedCompletionSummaryRunId] = useState<number | null>(null);
  const [completionSummaryVideoSeen, setCompletionSummaryVideoSeen] = useState(false);
  const [summaryGenerationStep, setSummaryGenerationStep] = useState(0);
  const [summaryDetailMode, setSummaryDetailMode] = useState<"read" | "listen" | null>(null);
  const [realtimeSummaryPhase, setRealtimeSummaryPhase] = useState<
    "idle" | "preparing" | "playing" | "completed" | "failed" | "stopped" | "timeout"
  >("idle");
  const [loading, setLoading] = useState(true);
  const [starting, setStarting] = useState(false);
  const [sending, setSending] = useState(false);
  const [homeSurface, setHomeSurface] = useState<HomeSurface>("tracking");
  const [homeSurfaceEntryMode, setHomeSurfaceEntryMode] = useState<HomeSurfaceEntryMode>("guided");
  const [morningSequenceDay, setMorningSequenceDay] = useState(() =>
    resolveMorningSequenceDay(initialTrackerSummary),
  );
  const [journeyCompleted, setJourneyCompleted] = useState(
    () => {
      const initialState = readMorningSequenceState(userId, resolveMorningSequenceDay(initialTrackerSummary));
      return resolveJourneyCompleted({
        assessmentCompleted,
        summary: initialTrackerSummary,
        sequenceState: initialState,
      });
    },
  );
  const [finalGiaMessage, setFinalGiaMessage] = useState<string | null>(null);
  const [finalGiaMessageLoading, setFinalGiaMessageLoading] = useState(false);
  const [finalGiaMessageError, setFinalGiaMessageError] = useState<string | null>(null);
  const [finalGiaListening, setFinalGiaListening] = useState(false);
  const [finalGiaListenError, setFinalGiaListenError] = useState<string | null>(null);
  const [dailyHabitPlan, setDailyHabitPlan] = useState<DailyHabitPlanResponse | null>(null);
  const [dailyHabitPlanLoading, setDailyHabitPlanLoading] = useState(false);
  const [dailyHabitPlanError, setDailyHabitPlanError] = useState<string | null>(null);
  const [educationPlan, setEducationPlan] = useState<EducationPlanTodayResponse | null>(null);
  const [educationPlanLoading, setEducationPlanLoading] = useState(false);
  const [educationPlanError, setEducationPlanError] = useState<string | null>(null);
  const [educationQuizAnswers, setEducationQuizAnswers] = useState<Record<string, EducationQuizAnswerValue>>({});
  const [educationQuizSubmitting, setEducationQuizSubmitting] = useState(false);
  const [educationQuizMessage, setEducationQuizMessage] = useState<string | null>(null);
  const educationPlanRequestIdRef = useRef(0);
  const educationVideoProgressRef = useRef<{ key: string; sent80: boolean; sent100: boolean }>({
    key: "",
    sent80: false,
    sent100: false,
  });
  const finalGiaRequestIdRef = useRef(0);
  const finalGiaListenRequestIdRef = useRef(0);
  const finalGiaSpeechRef = useRef<{ close?: () => void } | null>(null);
  const finalGiaListenSessionIdRef = useRef<string | null>(null);
  const finalGiaListenStartedAtRef = useRef<number | null>(null);

  const autoStart = useMemo(() => isTruthyToken(searchParams?.get("autostart")), [searchParams]);
  const leadFlow = useMemo(() => isTruthyToken(searchParams?.get("lead")), [searchParams]);
  const leadTokenQuery = useMemo(() => {
    const token = String(leadToken || "").trim();
    return token ? `&lt=${encodeURIComponent(token)}` : "";
  }, [leadToken]);
  const initialMorningSequenceDay = resolveMorningSequenceDay(initialTrackerSummary);
  const allowResultSummaryInChat = leadFlow || isLeadGuest;
  const busy = loading || starting || sending || claiming;
  const chatReady = hasActiveSession || assessmentCompleted || messages.length > 0;
  const promptActive = Boolean(currentPrompt);
  const showResultCard = allowResultSummaryInChat && Boolean(resultSummary) && !promptActive;
  const showInlineCoachingPlan = showResultCard && showCoachingPlan;
  const showAssessmentControls = !assessmentCompleted && !isLeadGuest && !promptActive && (!leadFlow || !chatReady);
  const showHomeChatPanel = assessmentCompleted && !leadFlow && !isLeadGuest && !showResultCard && !promptActive;
  const showGuidedHomeChatPanel = showHomeChatPanel && !journeyCompleted;
  const completionSummaryRunId = parsePositiveUserId(resultSummary?.run_id);
  const completionSummaryVideoStorageKey = useMemo(
    () => (completionSummaryRunId ? `hs:assessment-summary-video:${userId}:${completionSummaryRunId}` : null),
    [completionSummaryRunId, userId],
  );
  const completionSummaryStatus = String(completionSummaryMedia?.avatarStatus || "").trim().toLowerCase();
  const completionSummaryUsesRealtime =
    String(completionSummaryMedia?.avatarMode || "").trim().toLowerCase() === "realtime" ||
    Boolean(completionSummaryMedia?.realtimeEnabled);
  const completionSummaryBootstrapPending =
    Boolean(showResultCard && completionSummaryRunId) &&
    !completionSummaryError &&
    (completionSummaryLoading || loadedCompletionSummaryRunId !== completionSummaryRunId);
  const completionSummaryPending =
    !completionSummaryUsesRealtime &&
    loadedCompletionSummaryRunId === completionSummaryRunId &&
    Boolean(completionSummaryStatus) &&
    completionSummaryStatus !== "succeeded" &&
    completionSummaryStatus !== "failed";
  const completionSummaryFailed = completionSummaryStatus === "failed";
  const summaryIntroMessage =
    "Gia is preparing your personalised results video. This can take a moment. Your full results will appear here once it is ready.";
  const showStoredSummaryVideo =
    !completionSummaryUsesRealtime &&
    Boolean(completionSummaryMedia?.avatarUrl) &&
    (allowResultSummaryInChat || !completionSummaryVideoSeen);
  const showCompletionSummaryPanel =
    (completionSummaryUsesRealtime && Boolean(completionSummaryRunId)) ||
    Boolean(
      showStoredSummaryVideo ||
      completionSummaryMedia?.text ||
        completionSummaryMedia?.audioUrl ||
        completionSummaryPending ||
        completionSummaryFailed ||
        completionSummaryLoading ||
        completionSummaryError,
    );
  const summaryExperienceBlocked =
    Boolean(showResultCard && completionSummaryRunId) &&
    !completionSummaryError &&
    (completionSummaryBootstrapPending ||
      completionSummaryPending ||
      (completionSummaryUsesRealtime &&
        (realtimeSummaryPhase === "idle" || realtimeSummaryPhase === "preparing")));
  const summaryResultsUnlocked =
    !summaryExperienceBlocked &&
    (!completionSummaryUsesRealtime ||
      ["playing", "completed", "failed", "stopped", "timeout"].includes(realtimeSummaryPhase));
  const educationLesson = educationPlan?.lesson || null;
  const educationContent = educationLesson?.content || null;
  const educationAvatar = educationContent?.avatar || null;
  const educationAvatarRecord = educationAvatar && typeof educationAvatar === "object"
    ? educationAvatar as Record<string, unknown>
    : null;
  const explicitEducationVideoUrl = firstNonEmptyString(
    educationAvatarRecord?.url,
    educationAvatarRecord?.video_url,
    educationAvatarRecord?.videoUrl,
    educationContent?.video_url,
  );
  const fallbackEducationMediaUrl = String(educationContent?.podcast_url || "").trim();
  const educationVideoUrl = explicitEducationVideoUrl || (
    isLikelyVideoUrl(fallbackEducationMediaUrl) ? fallbackEducationMediaUrl : ""
  );
  const educationVideoPosterUrl = firstNonEmptyString(
    educationAvatarRecord?.poster_url,
    educationAvatarRecord?.posterUrl,
    educationContent?.poster_url,
  );
  const educationHasVideo = Boolean(educationVideoUrl);
  const educationAvatarStatus = String(educationAvatarRecord?.status || "").trim().toLowerCase();
  const educationAvatarPending = Boolean(
    !educationHasVideo &&
      educationAvatarRecord?.job_id &&
      !["failed", "cancelled", "canceled"].includes(educationAvatarStatus),
  );
  const educationMediaKey = `${String(educationPlan?.plan_id || "education")}:${String(
    educationLesson?.lesson_variant_id || "",
  )}:${educationVideoUrl}`;
  const educationProgrammeName = String(educationPlan?.programme?.name || "").trim();
  const educationPillarPalette = getPillarPalette(educationPlan?.pillar_key);
  const educationPillarIconSrc = educationPillarPalette.icon;
  const educationPillarLabel = String(
    educationPlan?.pillar_label || educationPillarPalette.label || "",
  ).trim();
  const educationConceptTitle = String(
    educationPlan?.concept_label || educationLesson?.title || educationPlan?.pillar_label || "",
  ).trim();
  const educationDayIndex = Number(educationPlan?.day_index || 0);
  const educationDurationDays = Number(educationPlan?.programme?.duration_days || 0);
  const educationPreviousLesson = educationPlan?.previous_lesson || null;
  const educationPreviousLearningTitle = String(educationPreviousLesson?.title || "").trim();
  const educationPreviousLearningText = String(educationPreviousLesson?.takeaway || "").trim();
  const educationQuizQuestions = useMemo(
    () => (Array.isArray(educationPlan?.quiz?.questions) ? educationPlan.quiz.questions : []),
    [educationPlan?.quiz?.questions],
  );
  const educationCompletionStatus = String(educationPlan?.progress?.completion_status || "").trim().toLowerCase();
  const educationQuizCompleted = Boolean(
    educationPlan?.progress?.quiz_completed_at ||
      educationCompletionStatus.includes("quiz") ||
      educationCompletionStatus === "completed",
  );
  const educationFocusCompleted = Boolean(
    educationPlan?.progress?.completed_at || educationCompletionStatus === "completed",
  );
  const educationStreakDays = Math.max(0, Math.floor(Number(educationPlan?.streak_days || 0) || 0));
  const educationBestStreakDays = Math.max(0, Math.floor(Number(educationPlan?.best_streak_days || 0) || 0));
  const educationStreakLabel = `${educationStreakDays} day${educationStreakDays === 1 ? "" : "s"}`;
  const educationBestStreakLabel = `${educationBestStreakDays} day${educationBestStreakDays === 1 ? "" : "s"}`;
  const educationCompletedDays = educationDurationDays > 0 && educationDayIndex > 0
    ? Math.min(
        educationDurationDays,
        Math.max(0, educationDayIndex - (educationFocusCompleted ? 0 : 1)),
      )
    : null;
  const educationCompletedDaysLabel =
    educationCompletedDays !== null && educationDurationDays > 0
      ? `${educationCompletedDays}/${educationDurationDays} days complete`
      : educationDayIndex > 0
        ? `Day ${educationDayIndex}`
        : "";
  const educationFocusStreakSummary = [
    educationCompletedDaysLabel,
    `${educationStreakLabel} focus streak`,
    educationBestStreakDays > educationStreakDays ? `Best ${educationBestStreakLabel}` : "",
  ].filter(Boolean).join(" · ");
  const dailyHabits = useMemo(() => {
    const selected = Array.isArray(dailyHabitPlan?.habits) ? dailyHabitPlan.habits : [];
    const fallback = Array.isArray(dailyHabitPlan?.options) ? dailyHabitPlan.options : [];
    return mergeDailyPlanItems(selected, fallback);
  }, [dailyHabitPlan?.habits, dailyHabitPlan?.options]);
  const currentHomeSurfaceIndex = HOME_SURFACE_SEQUENCE.indexOf(homeSurface);
  const homeSurfaceMeta = HOME_SURFACE_COPY[homeSurface];
  const viewingHomeSurfaceFromSummary = homeSurfaceEntryMode === "summary";
  const homeSurfaceEyebrow = viewingHomeSurfaceFromSummary ? "Daily view" : homeSurfaceMeta.eyebrow;
  const homeSurfaceDescription = viewingHomeSurfaceFromSummary
    ? "Review this and close when you are ready."
    : homeSurfaceMeta.description;
  const previousHomeSurface =
    currentHomeSurfaceIndex > 0 ? HOME_SURFACE_SEQUENCE[currentHomeSurfaceIndex - 1] : null;
  const nextHomeSurface =
    currentHomeSurfaceIndex >= 0 && currentHomeSurfaceIndex < HOME_SURFACE_SEQUENCE.length - 1
      ? HOME_SURFACE_SEQUENCE[currentHomeSurfaceIndex + 1]
      : null;
  const homePanelHeightClass =
    homeSurface === "tracking"
      ? "min-h-[calc(100dvh-8.5rem)] sm:h-[44vh] sm:min-h-[20rem] sm:max-h-[28rem]"
      : homeSurface === "ask"
        ? "min-h-[calc(100dvh-8.5rem)] sm:h-[58vh] sm:min-h-[22rem] sm:max-h-[38rem]"
        : "min-h-[calc(100dvh-8.5rem)] sm:h-[78vh] sm:min-h-[32rem] sm:max-h-[56rem]";

  const markCompletionSummaryVideoSeen = useCallback(() => {
    if (!completionSummaryVideoStorageKey || typeof window === "undefined") {
      return;
    }
    try {
      window.localStorage.setItem(completionSummaryVideoStorageKey, "1");
    } catch {
      // Ignore storage failures and keep the current render path active.
    }
  }, [completionSummaryVideoStorageKey]);

  const completeMorningSequence = useCallback(() => {
    writeMorningSequenceState(userId, morningSequenceDay, "completed");
    setJourneyCompleted(true);
  }, [morningSequenceDay, userId]);

  const applyChatPayload = useCallback((data: ChatResponse) => {
    const nextPrompt = normalizeCurrentPrompt(data.current_prompt);
    const persistedMessages = normalizeMessages(data.messages);
    const fallbackOutboxMessages = normalizeMessages(data.outbox);
    setMessages(persistedMessages.length > 0 ? persistedMessages : fallbackOutboxMessages);
    setHasActiveSession(Boolean(data.has_active_session));
    setCurrentPrompt(nextPrompt);
    setResultSummary(allowResultSummaryInChat ? normalizeResultSummary(data.result_summary) : null);
    setSelectedPromptValue(null);
    setIdentityRequired(Boolean(data.identity_required));
  }, [allowResultSummaryInChat]);

  const startAssessment = useCallback(async (forceIntro = false) => {
    setStarting(true);
    setStatus(null);
    try {
      const res = await fetch("/api/assessment/chat/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ userId, force_intro: forceIntro, lead_token: leadToken || undefined }),
      });
      const text = await res.text().catch(() => "");
      if (!res.ok) {
        throw new Error(parseApiError(text, "Failed to start My Coach Gia."));
      }
      const data = (text ? (JSON.parse(text) as ChatResponse) : {}) as ChatResponse;
      applyChatPayload(data);
      if (!data.handled && !data.has_active_session && !assessmentCompleted) {
        setStatus("Chat is not active yet. Provide requested details, then start chat again.");
      }
    } catch (error) {
      setStatus(error instanceof Error ? error.message : String(error));
    } finally {
      setStarting(false);
    }
  }, [userId, assessmentCompleted, applyChatPayload, leadToken]);

  const loadDailyHabitPlan = useCallback(async (options?: { force?: boolean }) => {
    setDailyHabitPlanLoading(true);
    setDailyHabitPlanError(null);
    try {
      const params = new URLSearchParams({ userId });
      if (options?.force) {
        params.set("force", "1");
      }
      const res = await fetch(`/api/daily-habits?${params.toString()}`, {
        method: "GET",
        cache: "no-store",
      });
      const text = await res.text().catch(() => "");
      if (!res.ok) {
        throw new Error(parseApiError(text, "Failed to load today's plan."));
      }
      const data = (text ? (JSON.parse(text) as DailyHabitPlanResponse) : {}) as DailyHabitPlanResponse;
      setDailyHabitPlan(data);
    } catch (error) {
      setDailyHabitPlanError(error instanceof Error ? error.message : String(error));
    } finally {
      setDailyHabitPlanLoading(false);
    }
  }, [userId]);
  const loadEducationPlan = useCallback(async () => {
    const requestId = educationPlanRequestIdRef.current + 1;
    educationPlanRequestIdRef.current = requestId;
    setEducationPlanLoading(true);
    setEducationPlanError(null);
    setEducationQuizMessage(null);
    try {
      const params = new URLSearchParams({ userId });
      const res = await fetch(`/api/education-plan/today?${params.toString()}`, {
        method: "GET",
        cache: "no-store",
      });
      const text = await res.text().catch(() => "");
      if (!res.ok) {
        throw new Error(parseApiError(text, "Failed to load today's lesson."));
      }
      const data = (text ? (JSON.parse(text) as EducationPlanTodayResponse) : {}) as EducationPlanTodayResponse;
      if (requestId !== educationPlanRequestIdRef.current) {
        return;
      }
      setEducationPlan(data);
    } catch (error) {
      if (requestId !== educationPlanRequestIdRef.current) {
        return;
      }
      setEducationPlanError(error instanceof Error ? error.message : String(error));
    } finally {
      if (requestId === educationPlanRequestIdRef.current) {
        setEducationPlanLoading(false);
      }
    }
  }, [userId]);

  const recordEducationVideoProgress = useCallback(async (watchPct: number, watchedSeconds?: number) => {
    try {
      const res = await fetch("/api/education-plan/video-progress", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          userId,
          watch_pct: Math.max(0, Math.min(100, Math.round(watchPct))),
          watched_seconds: Number.isFinite(Number(watchedSeconds)) ? Math.max(0, Math.round(Number(watchedSeconds))) : undefined,
        }),
      });
      const text = await res.text().catch(() => "");
      if (!res.ok) {
        throw new Error(parseApiError(text, "Failed to save lesson progress."));
      }
      const data = (text ? (JSON.parse(text) as EducationPlanTodayResponse) : {}) as EducationPlanTodayResponse;
      setEducationPlan(data);
      setEducationPlanError(null);
    } catch {
      setEducationPlanError(null);
    }
  }, [userId]);

  const selectEducationQuizAnswer = useCallback((questionId: number | undefined, answer: EducationQuizAnswerValue) => {
    if (!questionId) return;
    setEducationQuizAnswers((current) => ({
      ...current,
      [String(questionId)]: answer,
    }));
    setEducationQuizMessage(null);
  }, []);

  const submitEducationQuiz = useCallback(async () => {
    const answers = educationQuizQuestions
      .map((question) => {
        const questionId = Number(question?.id || 0);
        if (!questionId) return null;
        const answer = educationQuizAnswers[String(questionId)];
        return {
          question_id: questionId,
          answer,
        };
      })
      .filter((item): item is { question_id: number; answer: EducationQuizAnswerValue } => Boolean(item));
    const missingAnswer = answers.some((item) => item.answer === undefined || item.answer === null || item.answer === "");
    if (!answers.length || missingAnswer || answers.length < educationQuizQuestions.length) {
      setEducationQuizMessage("Complete the quick check before submitting.");
      return;
    }
    setEducationQuizSubmitting(true);
    setEducationQuizMessage(null);
    try {
      const res = await fetch("/api/education-plan/quiz-submit", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          userId,
          answers,
        }),
      });
      const text = await res.text().catch(() => "");
      if (!res.ok) {
        throw new Error(parseApiError(text, "Failed to submit the quick check."));
      }
      const data = (text ? (JSON.parse(text) as EducationPlanTodayResponse) : {}) as EducationPlanTodayResponse;
      setEducationPlan(data);
      setEducationQuizMessage("Quick check saved.");
    } catch (error) {
      setEducationQuizMessage(error instanceof Error ? error.message : String(error));
    } finally {
      setEducationQuizSubmitting(false);
    }
  }, [educationQuizAnswers, educationQuizQuestions, userId]);

  const refreshChatState = useCallback(
    async (options?: { showLoading?: boolean; clearStatus?: boolean }) => {
      const showLoading = Boolean(options?.showLoading);
      const clearStatus = Boolean(options?.clearStatus);
      if (showLoading) {
        setLoading(true);
      }
      if (clearStatus) {
        setStatus(null);
      }
      const res = await fetch(`/api/assessment/chat/state?userId=${encodeURIComponent(userId)}${leadTokenQuery}`, {
        method: "GET",
        cache: "no-store",
      });
      const text = await res.text().catch(() => "");
      if (!res.ok) {
        throw new Error(parseApiError(text, "Failed to load My Coach Gia."));
      }
      let data: ChatResponse = {};
      if (text) {
        try {
          data = JSON.parse(text) as ChatResponse;
        } catch {
          throw new Error("My Coach Gia returned invalid JSON.");
        }
      }
      applyChatPayload(data);
      return data;
    },
    [userId, leadTokenQuery, applyChatPayload],
  );

  const requestFinalGiaMessage = useCallback(async () => {
    const requestId = finalGiaRequestIdRef.current + 1;
    finalGiaRequestIdRef.current = requestId;
    setFinalGiaMessageLoading(true);
    setFinalGiaMessageError(null);
    setFinalGiaListenError(null);
    setStatus(null);
    try {
      const res = await fetch("/api/assessment/chat/tracker-summary", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          userId,
          lead_token: leadToken || undefined,
        }),
      });
      const text = await res.text().catch(() => "");
      if (!res.ok) {
        throw new Error(parseApiError(text, "Failed to load Gia's message."));
      }
      const data = (text ? (JSON.parse(text) as { text?: string; error?: string }) : {}) as {
        text?: string;
        error?: string;
      };
      if (requestId !== finalGiaRequestIdRef.current) return;
      const nextText = String(data.text || "").trim();
      if (!nextText) {
        throw new Error("Gia's message is not available right now.");
      }
      setFinalGiaMessage(nextText);
    } catch (error) {
      if (requestId !== finalGiaRequestIdRef.current) return;
      setFinalGiaMessageError(error instanceof Error ? error.message : String(error));
    } finally {
      if (requestId === finalGiaRequestIdRef.current) {
        setFinalGiaMessageLoading(false);
      }
    }
  }, [userId, leadToken]);

  const completeFinalGiaListenSession = useCallback(
    (statusValue: "completed" | "failed" | "stopped", error?: string | null) => {
      const sessionId = finalGiaListenSessionIdRef.current;
      const startedAt = finalGiaListenStartedAtRef.current;
      finalGiaListenSessionIdRef.current = null;
      finalGiaListenStartedAtRef.current = null;
      if (!sessionId) return;
      const durationMs = startedAt ? Math.max(0, Date.now() - startedAt) : 0;
      void fetch("/api/assessment/gia-message-avatar/realtime-complete", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          userId,
          session_id: sessionId,
          duration_ms: durationMs,
          status: statusValue,
          error: error || undefined,
        }),
      }).catch(() => undefined);
    },
    [userId],
  );

  const stopFinalGiaListening = useCallback(() => {
    finalGiaListenRequestIdRef.current += 1;
    try {
      finalGiaSpeechRef.current?.close?.();
    } catch {
      // Ignore speech cleanup failures.
    }
    finalGiaSpeechRef.current = null;
    setFinalGiaListening(false);
    completeFinalGiaListenSession("stopped");
  }, [completeFinalGiaListenSession]);

  const startFinalGiaListening = useCallback(async () => {
    const message = String(finalGiaMessage || "").trim();
    if (!message) return;
    if (typeof window === "undefined") {
      setFinalGiaListenError("Listening is not available in this browser.");
      return;
    }

    const requestId = finalGiaListenRequestIdRef.current + 1;
    finalGiaListenRequestIdRef.current = requestId;
    try {
      finalGiaSpeechRef.current?.close?.();
    } catch {
      // Ignore speech cleanup failures.
    }
    finalGiaSpeechRef.current = null;
    finalGiaListenSessionIdRef.current = null;
    finalGiaListenStartedAtRef.current = null;
    setFinalGiaListenError(null);
    setFinalGiaListening(true);

    try {
      const res = await fetch("/api/assessment/gia-message-avatar/realtime-session", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          userId,
          text: message,
        }),
      });
      const rawText = await res.text().catch(() => "");
      if (!res.ok) {
        throw new Error(parseApiError(rawText, "Gia's audio could not be started right now."));
      }
      const payload = (rawText ? JSON.parse(rawText) : {}) as GiaMessageRealtimeSessionResponse;
      if (requestId !== finalGiaListenRequestIdRef.current) return;
      const speechToken = String(payload.speech_token || "").trim();
      const speechRegion = String(payload.speech_region || "").trim();
      const ssml = String(payload.ssml || "").trim();
      const sessionId = String(payload.session_id || "").trim();
      if (!speechToken || !speechRegion || !ssml) {
        throw new Error("Gia's configured voice is not available right now.");
      }

      const SpeechSDK = await import("microsoft-cognitiveservices-speech-sdk");
      if (requestId !== finalGiaListenRequestIdRef.current) return;
      const speechConfig = SpeechSDK.SpeechConfig.fromAuthorizationToken(speechToken, speechRegion);
      const audioConfig = SpeechSDK.AudioConfig.fromDefaultSpeakerOutput();
      const synthesizer = new SpeechSDK.SpeechSynthesizer(speechConfig, audioConfig);
      finalGiaSpeechRef.current = synthesizer;
      finalGiaListenSessionIdRef.current = sessionId || null;
      finalGiaListenStartedAtRef.current = Date.now();

      const result = await new Promise<unknown>((resolve, reject) => {
        synthesizer.speakSsmlAsync(
          ssml,
          (speakResult) => resolve(speakResult),
          (error) => reject(error),
        );
      });
      if (requestId !== finalGiaListenRequestIdRef.current) return;
      const speakResult = result as { reason?: unknown; errorDetails?: string };
      if (speakResult.reason !== SpeechSDK.ResultReason.SynthesizingAudioCompleted) {
        throw new Error(speakResult.errorDetails || "Gia's audio did not complete.");
      }
      finalGiaSpeechRef.current = null;
      try {
        synthesizer.close();
      } catch {
        // Ignore speech cleanup failures.
      }
      setFinalGiaListening(false);
      completeFinalGiaListenSession("completed");
    } catch (error) {
      if (requestId !== finalGiaListenRequestIdRef.current) return;
      try {
        finalGiaSpeechRef.current?.close?.();
      } catch {
        // Ignore speech cleanup failures.
      }
      finalGiaSpeechRef.current = null;
      setFinalGiaListening(false);
      const messageText = error instanceof Error ? error.message : String(error);
      setFinalGiaListenError(messageText || "Gia's audio could not be played right now.");
      completeFinalGiaListenSession("failed", messageText);
    }
  }, [completeFinalGiaListenSession, finalGiaMessage, userId]);

  const toggleFinalGiaListening = useCallback(() => {
    if (finalGiaListening) {
      stopFinalGiaListening();
      return;
    }
    void startFinalGiaListening();
  }, [finalGiaListening, startFinalGiaListening, stopFinalGiaListening]);

  const refreshDailyCheckInStatus = useCallback(async () => {
    if (!assessmentCompleted || leadFlow || isLeadGuest) {
      return null;
    }
    const res = await fetch(`/api/pillar-tracker/summary?userId=${encodeURIComponent(userId)}`, {
      method: "GET",
      cache: "no-store",
    });
    const text = await res.text().catch(() => "");
    if (!res.ok) {
      throw new Error(parseApiError(text, "Failed to load today's tracking status."));
    }
    const data = (text ? (JSON.parse(text) as PillarTrackerSummaryResponse) : {}) as PillarTrackerSummaryResponse;
    return data;
  }, [assessmentCompleted, isLeadGuest, leadFlow, userId]);

  useEffect(() => {
    if (!showGuidedHomeChatPanel) {
      stopFinalGiaListening();
      setHomeSurface("tracking");
      setHomeSurfaceEntryMode("guided");
    }
  }, [showGuidedHomeChatPanel, stopFinalGiaListening, userId]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    window.dispatchEvent(
      new CustomEvent("healthsense-score-panel-visibility", {
        detail: {
          visible: journeyCompleted,
        },
      }),
    );
  }, [journeyCompleted]);

  useEffect(() => {
    const storedSequenceState =
      assessmentCompleted ? readMorningSequenceState(userId, initialMorningSequenceDay) : "idle";
    setMorningSequenceDay(initialMorningSequenceDay);
    setJourneyCompleted(
      resolveJourneyCompleted({
        assessmentCompleted,
        summary: initialTrackerSummary,
        sequenceState: storedSequenceState,
      }),
    );
    setFinalGiaMessage(null);
    setFinalGiaMessageError(null);
    setFinalGiaMessageLoading(false);
    setFinalGiaListenError(null);
    stopFinalGiaListening();
    setDailyHabitPlan(null);
    setDailyHabitPlanError(null);
    setDailyHabitPlanLoading(false);
    setEducationPlan(null);
    setEducationPlanError(null);
    setEducationPlanLoading(false);
    setEducationQuizAnswers({});
    setEducationQuizMessage(null);
  }, [assessmentCompleted, initialMorningSequenceDay, initialTrackerSummary, stopFinalGiaListening, userId]);

  useEffect(() => {
    if (typeof window === "undefined" || !assessmentCompleted || leadFlow || isLeadGuest) {
      return;
    }
    let cancelled = false;
    const syncDailyCheckInStatus = async () => {
      try {
        const nextSummary = await refreshDailyCheckInStatus();
        if (!nextSummary) return;
        const nextDay = resolveMorningSequenceDay(nextSummary);
        const storedSequenceState = readMorningSequenceState(userId, nextDay);
        if (!cancelled) {
          setMorningSequenceDay(nextDay);
          setJourneyCompleted(
            resolveJourneyCompleted({
              assessmentCompleted,
              summary: nextSummary,
              sequenceState: storedSequenceState,
            }),
          );
        }
      } catch {
        // Keep the current local state if the refresh fails.
      }
    };
    if (!initialTrackerSummary) {
      void syncDailyCheckInStatus();
    }
    const onVisibilityChange = () => {
      if (document.visibilityState !== "visible") return;
      void syncDailyCheckInStatus();
    };
    document.addEventListener("visibilitychange", onVisibilityChange);
    return () => {
      cancelled = true;
      document.removeEventListener("visibilitychange", onVisibilityChange);
    };
  }, [
    assessmentCompleted,
    initialTrackerSummary,
    isLeadGuest,
    leadFlow,
    refreshDailyCheckInStatus,
    userId,
  ]);

  useEffect(() => {
    if (homeSurface !== "ask") {
      stopFinalGiaListening();
    }
  }, [homeSurface, stopFinalGiaListening]);

  useEffect(() => () => stopFinalGiaListening(), [stopFinalGiaListening]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const onSurfaceChange = (event: Event) => {
      const detail = (event as CustomEvent<{ surface?: string; source?: string }>).detail;
      const surface = String(detail?.surface || "").trim().toLowerCase();
      const source = String(detail?.source || "").trim().toLowerCase();
      const entryMode: HomeSurfaceEntryMode = source === "summary" ? "summary" : "guided";
      if (entryMode === "guided") {
        writeMorningSequenceState(userId, morningSequenceDay, "in_progress");
      }
      setJourneyCompleted(false);
      if (surface === "tracking") {
        setHomeSurfaceEntryMode(entryMode);
        setHomeSurface("tracking");
        return;
      }
      if (surface === "insight") {
        setHomeSurfaceEntryMode(entryMode);
        setHomeSurface("insight");
        return;
      }
      if (surface === "habits") {
        setHomeSurfaceEntryMode(entryMode);
        setHomeSurface("habits");
        return;
      }
      if (surface === "ask") {
        setHomeSurfaceEntryMode(entryMode);
        setHomeSurface("ask");
      }
    };
    window.addEventListener("healthsense-home-surface", onSurfaceChange as EventListener);
    return () => {
      window.removeEventListener("healthsense-home-surface", onSurfaceChange as EventListener);
    };
  }, [morningSequenceDay, userId]);

  useEffect(() => {
    if (!showGuidedHomeChatPanel || homeSurface !== "habits") return;
    void loadDailyHabitPlan();
  }, [showGuidedHomeChatPanel, homeSurface, loadDailyHabitPlan]);

  useEffect(() => {
    if (!showGuidedHomeChatPanel || homeSurface !== "ask") return;
    if (journeyCompleted || finalGiaMessage || finalGiaMessageLoading || finalGiaMessageError) return;
    void requestFinalGiaMessage();
  }, [
    showGuidedHomeChatPanel,
    homeSurface,
    journeyCompleted,
    finalGiaMessage,
    finalGiaMessageLoading,
    finalGiaMessageError,
    requestFinalGiaMessage,
  ]);

  useEffect(() => {
    if (!showGuidedHomeChatPanel || homeSurface !== "insight") return;
    if (educationPlan) return;
    void loadEducationPlan();
  }, [showGuidedHomeChatPanel, homeSurface, loadEducationPlan, educationPlan]);

  useEffect(() => {
    if (!showGuidedHomeChatPanel || homeSurface !== "insight" || !educationAvatarPending) return;
    const timeout = window.setTimeout(() => {
      void loadEducationPlan();
    }, 12000);
    return () => window.clearTimeout(timeout);
  }, [showGuidedHomeChatPanel, homeSurface, educationAvatarPending, loadEducationPlan]);

  useEffect(() => {
    if (educationVideoProgressRef.current.key === educationMediaKey) return;
    educationVideoProgressRef.current = {
      key: educationMediaKey,
      sent80: false,
      sent100: false,
    };
  }, [educationMediaKey]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const onTrackerUpdated = (event: Event) => {
      const detail = (event as CustomEvent<{ guided?: boolean }>).detail;
      setDailyHabitPlan(null);
      setDailyHabitPlanError(null);
      setEducationPlan(null);
      setEducationPlanError(null);
      setEducationQuizAnswers({});
      setEducationQuizMessage(null);
      setFinalGiaMessage(null);
      setFinalGiaMessageError(null);
      setFinalGiaMessageLoading(false);
      setFinalGiaListenError(null);
      stopFinalGiaListening();
      if (detail?.guided !== true) {
        return;
      }
      writeMorningSequenceState(userId, morningSequenceDay, "in_progress");
      setJourneyCompleted(false);
      if (showGuidedHomeChatPanel) {
        void loadDailyHabitPlan();
        void refreshChatState().catch(() => undefined);
      }
    };
    window.addEventListener("healthsense-tracker-updated", onTrackerUpdated as EventListener);
    return () => {
      window.removeEventListener("healthsense-tracker-updated", onTrackerUpdated as EventListener);
    };
  }, [morningSequenceDay, refreshChatState, showGuidedHomeChatPanel, loadDailyHabitPlan, stopFinalGiaListening, userId]);

  useEffect(() => {
    let cancelled = false;
    const run = async () => {
      try {
        const data = await refreshChatState({ showLoading: true, clearStatus: true });
        if (cancelled) return;
        const shouldAutoStart =
          !isLeadGuest &&
          !Boolean(data.has_active_session) &&
          !assessmentCompleted &&
          (autoStart || leadFlow);
        if (shouldAutoStart) {
          void startAssessment(false);
        }
      } catch (error) {
        if (cancelled) return;
        setStatus(error instanceof Error ? error.message : String(error));
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    };
    void run();
    return () => {
      cancelled = true;
    };
  }, [userId, autoStart, leadFlow, assessmentCompleted, startAssessment, refreshChatState, isLeadGuest]);

  useEffect(() => {
    let cancelled = false;
    const poll = async () => {
      try {
        const data = await refreshChatState();
        if (cancelled) return;
        if (!data) return;
      } catch {
        // Silent polling failures; next cycle retries.
      }
    };

    const interval = window.setInterval(() => {
      if (document.visibilityState && document.visibilityState !== "visible") return;
      void poll();
    }, 8000);

    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, [refreshChatState]);

  useEffect(() => {
    setShowCoachingPlan(false);
    setClaimError(null);
    setClaimSuccess(false);
    setCompletionSummaryMedia(null);
    setCompletionSummaryError(null);
    setCompletionSummaryLoading(false);
    setLoadedCompletionSummaryRunId(null);
    setRealtimeSummaryPhase("idle");
    setSummaryGenerationStep(0);
    setSummaryDetailMode(null);
  }, [resultSummary?.run_id]);

  useEffect(() => {
    if (!completionSummaryVideoStorageKey || typeof window === "undefined") {
      setCompletionSummaryVideoSeen(false);
      return;
    }
    try {
      setCompletionSummaryVideoSeen(window.localStorage.getItem(completionSummaryVideoStorageKey) === "1");
    } catch {
      setCompletionSummaryVideoSeen(false);
    }
  }, [completionSummaryVideoStorageKey]);

  const fetchAssessmentReportPayload = useCallback(
    async (runId: number | null, fallbackMessage: string) => {
      const params = new URLSearchParams({ userId });
      if (runId) {
        params.set("runId", String(runId));
      }
      const res = await fetch(`/api/assessment/report?${params.toString()}`, {
        method: "GET",
        cache: "no-store",
      });
      const text = await res.text().catch(() => "");
      if (!res.ok) {
        throw new Error(parseApiError(text, fallbackMessage));
      }
      return text ? (JSON.parse(text) as Record<string, unknown>) : {};
    },
    [userId],
  );

  const loadCompletionSummary = useCallback(
    async (runId: number, silent = false) => {
      if (!silent) {
        setCompletionSummaryLoading(true);
      }
      try {
        const payload = await fetchAssessmentReportPayload(runId, "Failed to load your assessment summary.");
        const narratives = normalizeCompletionSummaryMedia(payload);
        setCompletionSummaryMedia(narratives);
        setCompletionSummaryError(null);
        setLoadedCompletionSummaryRunId(runId);
      } catch (error) {
        if (!silent) {
          setCompletionSummaryError(
            error instanceof Error ? error.message : String(error),
          );
        }
      } finally {
        if (!silent) {
          setCompletionSummaryLoading(false);
        }
      }
    },
    [fetchAssessmentReportPayload],
  );

  useEffect(() => {
    if (!showResultCard || !completionSummaryRunId) return;
    if (
      loadedCompletionSummaryRunId === completionSummaryRunId &&
      completionSummaryMedia
    ) {
      return;
    }
    void loadCompletionSummary(completionSummaryRunId);
  }, [
    showResultCard,
    completionSummaryRunId,
    loadedCompletionSummaryRunId,
    completionSummaryMedia,
    loadCompletionSummary,
  ]);

  useEffect(() => {
    if (!showResultCard || !completionSummaryRunId || !completionSummaryPending) return;
    const interval = window.setInterval(() => {
      if (document.visibilityState && document.visibilityState !== "visible") return;
      void loadCompletionSummary(completionSummaryRunId, true);
    }, 8000);
    return () => {
      window.clearInterval(interval);
    };
  }, [showResultCard, completionSummaryRunId, completionSummaryPending, loadCompletionSummary]);

  useEffect(() => {
    if (!showResultCard || !summaryExperienceBlocked) {
      setSummaryGenerationStep(0);
      return;
    }
    setSummaryGenerationStep(0);
    const interval = window.setInterval(() => {
      setSummaryGenerationStep((current) => Math.min(current + 1, 3));
    }, 2400);
    return () => {
      window.clearInterval(interval);
    };
  }, [showResultCard, summaryExperienceBlocked, resultSummary?.run_id]);

  async function sendMessage(
    textValue: string,
    options?: {
      restoreDraftOnError?: boolean;
      quickReply?: {
        used: boolean;
        hideInChat: boolean;
        label?: string;
      };
    },
  ) {
    const outbound = String(textValue || "").trim();
    if (!outbound || sending) return;
    setSending(true);
    setStatus(null);
    try {
      const res = await fetch("/api/assessment/chat/send", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          userId,
          text: outbound,
          chat_mode: showGuidedHomeChatPanel && homeSurface === "ask" ? "general_support" : undefined,
          lead_token: leadToken || undefined,
          quick_reply: options?.quickReply
            ? {
                used: Boolean(options.quickReply.used),
                hide_in_chat: Boolean(options.quickReply.hideInChat),
                label: options.quickReply.label || undefined,
              }
            : undefined,
        }),
      });
      const text = await res.text().catch(() => "");
      if (!res.ok) {
        throw new Error(parseApiError(text, "Failed to send message."));
      }
      const data = (text ? (JSON.parse(text) as ChatResponse) : {}) as ChatResponse;
      applyChatPayload(data);
      if (isLeadGuest) {
        const resolvedUserId = parsePositiveUserId(data.user_id);
        if (resolvedUserId) {
          const nextPathRaw = String(data.next_path || "").trim();
          const nextPath =
            nextPathRaw.startsWith("/") && !nextPathRaw.startsWith("//")
              ? nextPathRaw
              : `/assessment/${encodeURIComponent(String(resolvedUserId))}/chat?lead=1`;
          if (typeof window !== "undefined") {
            window.location.href = nextPath;
            return;
          }
        }
      }
      if (data.needs_start && !assessmentCompleted) {
        setStatus("No active chat session. Use Start assessment to begin.");
      }
    } catch (error) {
      setStatus(error instanceof Error ? error.message : String(error));
      setSelectedPromptValue(null);
      if (options?.restoreDraftOnError) {
        setDraft(outbound);
      }
    } finally {
      setSending(false);
    }
  }

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const textValue = draft.trim();
    if (!textValue || sending) return;
    setDraft("");
    await sendMessage(textValue, { restoreDraftOnError: true });
  }

  function onPromptOptionClick(option: AssessmentPromptOption) {
    const textValue = String(option.value || "").trim();
    if (!textValue || busy) return;
    setSelectedPromptValue(textValue);
    void sendMessage(textValue, {
      quickReply: {
        used: true,
        hideInChat: true,
        label: option.label,
      },
    });
  }

  function onPromptRedo() {
    if (busy) return;
    void sendMessage("redo");
  }

  function onPromptRestart() {
    if (busy) return;
    void sendMessage("restart");
  }

  function onDraftKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key !== "Enter" || event.shiftKey) return;
    if (event.nativeEvent.isComposing) return;
    if (busy || !draft.trim()) return;
    event.preventDefault();
    event.currentTarget.form?.requestSubmit();
  }

  async function onClaimIdentity(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const firstName = claimFirstName.trim();
    const surname = claimSurname.trim();
    const phone = claimPhone.trim();
    const password = claimPassword;
    const confirmPassword = claimConfirmPassword;
    if (claiming || claimSuccess) {
      return;
    }
    if (!firstName || !surname) {
      setClaimError("First name and surname are required.");
      return;
    }
    if (!phone) {
      setClaimError("Enter your mobile number, ideally with country code.");
      return;
    }
    if (!looksLikePhone(phone)) {
      setClaimError("Enter a valid mobile number, ideally with country code.");
      return;
    }
    if (!password || password.length < 8) {
      setClaimError("Password must be at least 8 characters.");
      return;
    }
    if (password !== confirmPassword) {
      setClaimError("Passwords do not match.");
      return;
    }

    setClaiming(true);
    setClaimError(null);
    setStatus(null);
    try {
      const res = await fetch("/api/assessment/chat/claim-identity", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          userId,
          first_name: firstName,
          surname,
          phone,
          password,
          create_app_session: true,
          lead_token: leadToken || undefined,
        }),
      });
      const text = await res.text().catch(() => "");
      if (!res.ok) {
        throw new Error(parseApiError(text, "Failed to save your details."));
      }
      const payload = text ? (JSON.parse(text) as {
        user?: { id?: number | string };
        next_path?: string | null;
      }) : {};
      const resolvedUserId = String(payload.user?.id || "").trim();
      const nextPath =
        String(payload.next_path || "").trim() ||
        (resolvedUserId ? `/assessment/${resolvedUserId}/chat` : "");
      setIdentityRequired(false);
      setClaimSuccess(true);
      setClaimNextPath(nextPath);
      void fetch("/api/engagement", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          userId,
          event_type: "coaching_interest",
          surface: "assessment_results",
          meta: {
            surface: "assessment_results",
            source: "personal_coaching_plan",
            component: "secure_your_place",
          },
        }),
      }).catch(() => undefined);
    } catch (error) {
      setClaimError(error instanceof Error ? error.message : String(error));
    } finally {
      setClaiming(false);
    }
  }

  async function onCoachingPlanClick() {
    if (showCoachingPlan) {
      return;
    }
    setClaimError(null);
    setShowCoachingPlan(true);
  }

  const resultExtremes = resultSummary ? resultPillarExtremes(resultSummary.pillars) : { strongest: null, weakest: null };
  const sortedResultPillars = resultSummary ? sortResultPillars(resultSummary.pillars) : [];
  const summaryGenerationMessages = [
    "Generating your personalised results video now.",
    resultExtremes.strongest
      ? `Your strongest pillar is ${resultExtremes.strongest.label} at ${resultExtremes.strongest.score}/100.`
      : null,
    resultExtremes.weakest
      ? `The pillar holding you back most right now is ${resultExtremes.weakest.label} at ${resultExtremes.weakest.score}/100.`
      : null,
    "Pulling everything together into your personalised video and report.",
  ].filter((message): message is string => Boolean(message));
  const visibleSummaryGenerationMessages = summaryGenerationMessages.slice(
    0,
    Math.min(summaryGenerationStep + 1, summaryGenerationMessages.length),
  );
  const resultCard = resultSummary ? (
    <section className="rounded-[28px] border border-[#e7e1d6] bg-[#fffaf3] px-4 py-6 shadow-[0_30px_80px_-60px_rgba(30,27,22,0.45)] sm:px-6 sm:py-8">
      <div className="space-y-6">
        {showCompletionSummaryPanel ? (
          <div className="rounded-2xl border border-[#efe7db] bg-white px-4 py-4">
            <div className="space-y-4">
              <div>
                <p className="text-xs uppercase tracking-[0.22em] text-[#6b6257]">Your personal summary</p>
              </div>

              {completionSummaryUsesRealtime && completionSummaryRunId && completionSummaryMedia?.text ? (
                <RealtimeSummaryAvatar
                  userId={userId}
                  runId={completionSummaryRunId}
                  text={completionSummaryMedia?.text || null}
                  audioUrl={completionSummaryMedia?.audioUrl || null}
                  maxSessionSeconds={completionSummaryMedia?.realtimeMaxSessionSeconds ?? null}
                  maxReplays={completionSummaryMedia?.realtimeMaxReplays ?? null}
                  autoStart
                  introMessage={null}
                  onPhaseChange={setRealtimeSummaryPhase}
                />
              ) : showStoredSummaryVideo ? (
                <video
                  className="w-full rounded-2xl border border-[#efe7db] bg-[#f6efe5]"
                  autoPlay
                  playsInline
                  preload="metadata"
                  onPlay={markCompletionSummaryVideoSeen}
                  onLoadedMetadata={(event) => {
                    void event.currentTarget.play().catch(() => undefined);
                  }}
                >
                  <source src={String(completionSummaryMedia?.avatarUrl || "")} type="video/mp4" />
                </video>
              ) : null}

              {!completionSummaryUsesRealtime &&
              !completionSummaryMedia?.avatarUrl &&
              completionSummaryMedia?.audioUrl ? (
                <div>
                  <p className="text-xs uppercase tracking-[0.18em] text-[#6b6257]">Listen</p>
                  <audio className="mt-2 w-full" controls preload="metadata">
                    <source src={completionSummaryMedia.audioUrl} type="audio/mpeg" />
                  </audio>
                </div>
              ) : null}

              {summaryExperienceBlocked ? (
                <div className="space-y-2">
                  {visibleSummaryGenerationMessages.map((message, index) => (
                    <p
                      key={`${index}-${message}`}
                      className="rounded-2xl border border-[#efe7db] bg-[#fffaf3] px-4 py-3 text-sm text-[#6b6257]"
                    >
                      {message}
                    </p>
                  ))}
                  {completionSummaryBootstrapPending || completionSummaryPending || completionSummaryLoading ? (
                    <p className="text-sm text-[#8c7f70]">{summaryIntroMessage}</p>
                  ) : null}
                </div>
              ) : null}

              {completionSummaryFailed && !completionSummaryMedia?.avatarUrl ? (
                <div className="space-y-1">
                  <p className="text-sm text-[#6b6257]">
                    {completionSummaryMedia?.audioUrl
                      ? "We couldn’t generate the video right now, but your audio summary is ready."
                      : "We couldn’t generate the video right now."}
                  </p>
                  {completionSummaryMedia?.avatarError ? (
                    <p className="text-sm text-[#8a3e1a]">{completionSummaryMedia.avatarError}</p>
                  ) : null}
                </div>
              ) : null}

              {completionSummaryError ? (
                <p className="text-sm text-[#6b6257]">{completionSummaryError}</p>
              ) : null}

              {!completionSummaryUsesRealtime &&
              !completionSummaryPending &&
              !completionSummaryLoading &&
              (completionSummaryMedia?.text || completionSummaryMedia?.audioUrl) ? (
                <div className="space-y-3">
                  <div className="flex flex-wrap gap-2">
                    {completionSummaryMedia?.text ? (
                      <button
                        type="button"
                        onClick={() => setSummaryDetailMode((current) => (current === "read" ? null : "read"))}
                        className="rounded-full border border-[#d9cdbb] bg-white px-4 py-2 text-xs font-semibold uppercase tracking-[0.18em] text-[#5d5348]"
                      >
                        {summaryDetailMode === "read" ? "Hide read" : "Read"}
                      </button>
                    ) : null}
                    {completionSummaryMedia?.audioUrl ? (
                      <button
                        type="button"
                        onClick={() => setSummaryDetailMode((current) => (current === "listen" ? null : "listen"))}
                        className="rounded-full border border-[#d9cdbb] bg-white px-4 py-2 text-xs font-semibold uppercase tracking-[0.18em] text-[#5d5348]"
                      >
                        {summaryDetailMode === "listen" ? "Hide listen" : "Listen"}
                      </button>
                    ) : null}
                  </div>

                  {summaryDetailMode === "listen" && completionSummaryMedia?.audioUrl ? (
                    <audio className="w-full" controls preload="metadata">
                      <source src={completionSummaryMedia.audioUrl} type="audio/mpeg" />
                    </audio>
                  ) : null}

                  {summaryDetailMode === "read" && completionSummaryMedia?.text ? (
                    <div className="rounded-2xl border border-[#efe7db] bg-[#fffaf3] px-4 py-4">
                      <p className="text-sm leading-6 text-[#3c332b]">{completionSummaryMedia.text}</p>
                    </div>
                  ) : null}
                </div>
              ) : null}
            </div>
          </div>
        ) : null}

        {summaryResultsUnlocked ? (
          <>
            <div className="rounded-3xl border border-[#efe7db] bg-white px-5 py-5">
              <div className="flex items-center gap-4">
                <LeadAssessmentBranding
                  titleLines={[]}
                  logoClassName="h-11 w-11 flex-none sm:h-12 sm:w-12"
                />
                <div className="min-w-0 flex-1 space-y-2">
                  <div className="flex items-end justify-between gap-4">
                    <div>
                      <p className="text-xs uppercase tracking-[0.22em] text-[#6b6257]">HealthSense Score</p>
                      <p className="mt-1 text-4xl font-semibold text-[#1e1b16]">{resultSummary.combined}</p>
                    </div>
                    <p className="text-xs font-semibold uppercase tracking-[0.18em] text-[#8c7f70]">out of 100</p>
                  </div>
                  <ProgressBar value={resultSummary.combined} max={100} tone="var(--accent)" />
                </div>
              </div>
            </div>

            {resultSummary.reflection?.selected_label && resultSummary.reflection?.top_label ? (
              <div className="rounded-2xl border border-[#efe7db] bg-white px-4 py-4">
                <p className="text-xs uppercase tracking-[0.22em] text-[#6b6257]">Your reflection</p>
                <p className="mt-2 text-sm text-[#3c332b]">
                  {resultSummary.reflection.matches_top
                    ? `You felt strongest in ${resultSummary.reflection.selected_label}, and your results backed that up. It came out highest at ${Math.round(Number(resultSummary.reflection.top_score || 0))}/100.`
                    : `You felt strongest in ${resultSummary.reflection.selected_label}, but your highest measured result was ${resultSummary.reflection.top_label} at ${Math.round(Number(resultSummary.reflection.top_score || 0))}/100.`}
                </p>
              </div>
            ) : null}

            {resultSummary.pillars.length ? (
              <div className="grid grid-cols-2 gap-3 sm:gap-4">
                {sortedResultPillars.map((pillar) => {
                  const palette = getPillarPalette(pillar.pillar_key);
                  const isStrongest =
                    resultExtremes.strongest?.pillar_key === pillar.pillar_key &&
                    resultExtremes.strongest?.score === pillar.score;
                  const isWeakest =
                    resultExtremes.weakest?.pillar_key === pillar.pillar_key &&
                    resultExtremes.weakest?.score === pillar.score;
                  return (
                    <div key={pillar.pillar_key} className="rounded-2xl border border-[#efe7db] bg-white px-4 py-5">
                      <div className="flex flex-col items-center text-center">
                        <ScoreRing value={pillar.score} tone={palette.accent} />
                        <p className="mt-3 text-sm font-semibold text-[#1e1b16]">
                          {pillar.label}
                          {isStrongest ? <strong> (strongest)</strong> : null}
                          {isWeakest ? <strong> (weakest)</strong> : null}
                        </p>
                      </div>
                    </div>
                  );
                })}
              </div>
            ) : null}

            {!showInlineCoachingPlan ? (
              <div className="border-t border-[#eadfce] pt-4">
                <button
                  type="button"
                  onClick={() => void onCoachingPlanClick()}
                  className="rounded-full border border-[var(--accent)] bg-[var(--accent)] px-4 py-2 text-center text-xs font-semibold uppercase tracking-[0.18em] whitespace-normal text-white disabled:cursor-not-allowed disabled:opacity-60"
                >
                  Get your personal coaching plan
                </button>
              </div>
            ) : null}
          </>
        ) : null}
      </div>
    </section>
  ) : null;

  const coachingPlanPanel = showInlineCoachingPlan ? (
    <form
      onSubmit={onClaimIdentity}
      className="overflow-hidden rounded-[28px] border border-[#e7e1d6] bg-white shadow-[0_30px_80px_-60px_rgba(30,27,22,0.45)]"
      autoComplete="on"
    >
      <div className="border-b border-[#efe7db] px-4 py-4 sm:px-6">
        <p className="text-xs uppercase tracking-[0.22em] text-[#6b6257]">Early access</p>
        <p className="mt-1 text-sm text-[#3c332b]">
          Watch the explainer below, then create your HealthSense mobile login and keep this assessment linked to your app account.
        </p>
      </div>
      {String(coachProductAvatar?.url || "").trim() ? (
        <div className="border-b border-[#efe7db] bg-[#f7f4ee] p-3 sm:p-4">
          <video
            controls
            preload="metadata"
            playsInline
            poster={String(coachProductAvatar?.posterUrl || "").trim() || undefined}
            className="w-full rounded-2xl border border-[#efe7db] bg-[#f7f4ee]"
          >
            <source src={String(coachProductAvatar?.url || "").trim()} />
          </video>
        </div>
      ) : null}
      <div className="space-y-4 px-4 py-5 sm:px-6 sm:py-6">
        <div className="space-y-2">
          <h2 className="text-2xl text-[#1e1b16]">Create your early access mobile login</h2>
          <p className="text-sm text-[#6b6257]">
            {identityRequired
              ? "Add your details below to create your HealthSense login. You will log in with your mobile number, and this assessment will stay linked to your account."
              : "Confirm your details below to finish your HealthSense login. You will log in with your mobile number, and this assessment will stay linked to your account."}
          </p>
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          <input
            className="rounded-xl border border-[#efe7db] bg-white px-3 py-2 text-sm"
            type="text"
            placeholder="First name"
            autoComplete="given-name"
            value={claimFirstName}
            onChange={(event) => setClaimFirstName(event.target.value)}
            disabled={claiming || claimSuccess}
            required
          />
          <input
            className="rounded-xl border border-[#efe7db] bg-white px-3 py-2 text-sm"
            type="text"
            placeholder="Surname"
            autoComplete="family-name"
            value={claimSurname}
            onChange={(event) => setClaimSurname(event.target.value)}
            disabled={claiming || claimSuccess}
            required
          />
          <input
            className="rounded-xl border border-[#efe7db] bg-white px-3 py-2 text-sm sm:col-span-2"
            type="tel"
            placeholder="Mobile number"
            autoComplete="tel"
            inputMode="tel"
            value={claimPhone}
            onChange={(event) => setClaimPhone(event.target.value)}
            disabled={claiming || claimSuccess}
            required
          />
          <input
            className="rounded-xl border border-[#efe7db] bg-white px-3 py-2 text-sm"
            type="password"
            placeholder="Create password"
            autoComplete="new-password"
            value={claimPassword}
            onChange={(event) => setClaimPassword(event.target.value)}
            disabled={claiming || claimSuccess}
            required
          />
          <input
            className="rounded-xl border border-[#efe7db] bg-white px-3 py-2 text-sm"
            type="password"
            placeholder="Confirm password"
            autoComplete="new-password"
            value={claimConfirmPassword}
            onChange={(event) => setClaimConfirmPassword(event.target.value)}
            disabled={claiming || claimSuccess}
            required
          />
        </div>
        <p className="text-xs text-[#6b6257]">
          Your mobile number is required and will be used for future login codes by WhatsApp or SMS.
        </p>

        <div>
          <button
            type="submit"
            className="w-full rounded-full border border-[var(--accent)] bg-[var(--accent)] px-4 py-3 text-center text-xs font-semibold uppercase tracking-[0.18em] whitespace-normal text-white disabled:cursor-not-allowed disabled:opacity-60"
            disabled={claiming || claimSuccess}
          >
            {claimSuccess
              ? "Your account is ready."
              : claiming
                ? "Creating your login…"
                : "Create my mobile login"}
          </button>
          {claimSuccess ? (
            <div className="mt-3 space-y-2">
              <p className="text-sm text-[#3c332b]">
                Your HealthSense account is ready. This assessment is linked to it, and you will log in with your mobile number.
              </p>
              {claimNextPath ? (
                <button
                  type="button"
                  onClick={() => {
                    window.location.href = claimNextPath;
                  }}
                  className="w-full rounded-full border border-[#d9cdbb] bg-white px-4 py-3 text-center text-xs font-semibold uppercase tracking-[0.18em] text-[#5d5348]"
                >
                  Open the app
                </button>
              ) : null}
            </div>
          ) : null}
          {claimError ? (
            <p className="mt-2 text-sm text-[#8a3e1a]">{claimError}</p>
          ) : null}
        </div>
      </div>
    </form>
  ) : null;

  const homeChatPanel = showGuidedHomeChatPanel ? (
    <section className="-mx-3 overflow-hidden border-y border-[#e7e1d6] bg-white sm:mx-0 sm:rounded-[28px] sm:border sm:shadow-[0_30px_80px_-60px_rgba(30,27,22,0.45)]">
      <div className={`flex ${homePanelHeightClass} min-h-0 flex-col`}>
        <div className="shrink-0 border-b border-[#efe7db] bg-[#fffaf3] px-4 py-4 sm:px-5">
          {homeSurface === "insight" && educationPlan?.available ? (
            <div className="min-w-0 space-y-1">
              <div className="flex min-w-0 items-center gap-3">
                {educationPillarIconSrc ? (
                  <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl border border-[#efe7db] bg-[#fffaf3]">
                    <Image
                      src={educationPillarIconSrc}
                      alt=""
                      aria-hidden="true"
                      width={24}
                      height={24}
                      className="h-6 w-6 object-contain"
                    />
                  </span>
                ) : null}
                <p className="min-w-0 text-xs uppercase tracking-[0.22em] text-[#6b6257]">
                  {[educationPillarLabel, homeSurfaceMeta.title].filter(Boolean).join(" · ")}
                </p>
              </div>
              {educationFocusStreakSummary ? (
                <p className="text-xs text-[#8c7f70]">{educationFocusStreakSummary}</p>
              ) : null}
            </div>
          ) : (
            <>
              <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[#6b6257]">
                {homeSurfaceEyebrow}
              </p>
              <p className="mt-1 text-lg font-semibold text-[#1e1b16]">{homeSurfaceMeta.title}</p>
              {homeSurfaceDescription ? (
                <p className="mt-1 text-sm text-[#6b6257]">{homeSurfaceDescription}</p>
              ) : null}
            </>
          )}
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-4 py-4 sm:px-5">
          {homeSurface === "tracking" ? (
            <div className="flex min-h-full flex-col gap-4">
              <div className="rounded-[24px] border border-[#efe7db] bg-[#fffaf3] px-4 py-4 sm:px-5 sm:py-5">
                <p className="text-sm text-[#6b6257]">
                  Tap a pillar to open just that daily check-in, or start the guided flow below to move through each pillar in order.
                </p>
                <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-4">
                  {TRACKING_STEP_PILLARS.map((pillar, index) => (
                    <button
                      key={pillar}
                      type="button"
                      onClick={() => {
                        if (typeof window !== "undefined") {
                          window.dispatchEvent(
                            new CustomEvent("healthsense-open-tracker", {
                              detail: {
                                pillarKey: pillar.toLowerCase(),
                                guided: false,
                                returnSurface: "tracking",
                              },
                            }),
                          );
                        }
                      }}
                      className="rounded-2xl border border-[#efe7db] bg-white px-3 py-3 text-left transition hover:border-[#dccfbe]"
                    >
                      <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-[var(--accent)]">
                        Pillar {index + 1}
                      </p>
                      <p className="mt-2 text-sm font-semibold text-[#1e1b16]">{pillar}</p>
                    </button>
                  ))}
                </div>
              </div>
              <div className="sticky bottom-0 mt-auto rounded-t-[24px] bg-white/95 pt-3 backdrop-blur">
                <div className="rounded-[24px] border border-[#efe7db] bg-white px-4 py-4 shadow-[0_-20px_50px_-42px_rgba(30,27,22,0.45)] sm:px-5">
                  <p className="text-sm text-[#6b6257]">
                    Start the tracker and we will take you through all four pillars one at a time.
                  </p>
                  <button
                    type="button"
                    onClick={() => {
                      if (typeof window !== "undefined") {
                        window.scrollTo({ top: 0, behavior: "smooth" });
                        window.dispatchEvent(
                          new CustomEvent("healthsense-open-tracker", {
                            detail: {
                              guided: true,
                            },
                          }),
                        );
                      }
                    }}
                    className="mt-4 w-full rounded-full border border-[var(--accent)] bg-[var(--accent)] px-4 py-3 text-center text-xs font-semibold uppercase tracking-[0.18em] text-white"
                  >
                    Start daily check-in
                  </button>
                </div>
              </div>
            </div>
          ) : homeSurface === "insight" ? (
            educationPlanLoading && !educationPlan ? (
              <div className="flex min-h-full items-center rounded-[24px] border border-[#efe7db] bg-[#fffaf3] px-4 py-5">
                <p className="text-sm text-[#6b6257]">
                  Loading today&apos;s education programme…
                </p>
              </div>
            ) : educationPlan?.available ? (
              <div className="flex min-h-full flex-col gap-3">
                {educationPlanLoading && educationPlan ? (
                  <p className="text-sm text-[#6b6257]">Refreshing today&apos;s lesson…</p>
                ) : null}
                <div className="rounded-[20px] border border-[#efe7db] bg-white px-4 py-3">
                  <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-[var(--accent)]">
                    {educationProgrammeName || "Education programme"}
                  </p>
                  <p className="mt-2 text-sm font-semibold text-[#1e1b16]">
                    {educationLesson?.title || educationConceptTitle || "Today's lesson"}
                  </p>
                  <p className="mt-1 text-xs uppercase tracking-[0.14em] text-[#8c7f70]">
                    {[
                      educationConceptTitle,
                      educationDayIndex > 0
                        ? educationDurationDays > 0
                          ? `Day ${educationDayIndex} of ${educationDurationDays}`
                          : `Day ${educationDayIndex}`
                        : "",
                      educationPlan.level ? `${educationPlan.level} level` : "",
                    ].filter(Boolean).join(" · ")}
                  </p>
                  {!educationHasVideo && educationLesson?.summary ? (
                    <p className="mt-3 text-sm leading-6 text-[#6b6257]">{educationLesson.summary}</p>
                  ) : null}
                </div>
                {educationPreviousLearningTitle || educationPreviousLearningText ? (
                  <div className="rounded-[20px] border border-[#efe7db] bg-[#fffaf3] px-4 py-4">
                    <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-[var(--accent)]">
                      What we learnt yesterday
                    </p>
                    {educationPreviousLearningTitle ? (
                      <p className="mt-2 text-sm font-semibold text-[#1e1b16]">
                        {educationPreviousLearningTitle}
                      </p>
                    ) : null}
                    {educationPreviousLearningText ? (
                      <p className="mt-2 text-sm leading-6 text-[#6b6257]">
                        {educationPreviousLearningText}
                      </p>
                    ) : null}
                  </div>
                ) : null}
                {educationHasVideo ? (
                  <div className="rounded-[24px] border border-[#efe7db] bg-[#f7f4ee]">
                    <video
                      key={`education-video-${educationMediaKey}`}
                      controls
                      preload="metadata"
                      playsInline
                      poster={educationVideoPosterUrl || undefined}
                      onTimeUpdate={(event) => {
                        const video = event.currentTarget;
                        if (!video.duration || !Number.isFinite(video.duration)) return;
                        const pct = (video.currentTime / video.duration) * 100;
                        if (pct >= 80 && !educationVideoProgressRef.current.sent80) {
                          educationVideoProgressRef.current.sent80 = true;
                          void recordEducationVideoProgress(pct, video.currentTime);
                        }
                      }}
                      onEnded={(event) => {
                        if (educationVideoProgressRef.current.sent100) return;
                        educationVideoProgressRef.current.sent100 = true;
                        void recordEducationVideoProgress(100, event.currentTarget.currentTime);
                      }}
                      className="max-h-[22rem] w-full rounded-[24px] bg-[#f7f4ee] object-contain"
                    >
                      <source src={educationVideoUrl} />
                    </video>
                  </div>
                ) : educationAvatarPending ? (
                  <div className="rounded-[20px] border border-[#efe7db] bg-[#fffaf3] px-4 py-4">
                    <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-[var(--accent)]">
                      Avatar video
                    </p>
                    <p className="mt-2 text-sm leading-6 text-[#6b6257]">
                      Today&apos;s avatar video is being prepared. This will update automatically when the video is ready.
                    </p>
                  </div>
                ) : educationContent?.script || educationContent?.body ? (
                  <div className="rounded-[20px] border border-[#efe7db] bg-[#fffaf3] px-4 py-4">
                    <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-[var(--accent)]">
                      Lesson
                    </p>
                    <p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-[#6b6257]">
                      {educationContent.script || educationContent.body}
                    </p>
                  </div>
                ) : (
                  <div className="rounded-[20px] border border-[#efe7db] bg-[#fffaf3] px-4 py-4">
                    <p className="text-sm text-[#6b6257]">Lesson content is not available right now.</p>
                  </div>
                )}
                {educationLesson?.action_prompt ? (
                  <div className="rounded-[20px] border border-[#efe7db] bg-white px-4 py-4">
                    <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-[var(--accent)]">
                      Today&apos;s action
                    </p>
                    <p className="mt-2 text-sm leading-6 text-[#1e1b16]">{educationLesson.action_prompt}</p>
                  </div>
                ) : null}
                {educationQuizQuestions.length ? (
                  <div className="rounded-[20px] border border-[#efe7db] bg-[#fffaf3] px-4 py-4">
                    <div className="flex items-center justify-between gap-3">
                      <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-[var(--accent)]">
                        Quick check
                      </p>
                      {educationQuizCompleted ? (
                        <p className="text-xs font-semibold text-[#5d5348]">
                          {educationPlan.progress?.quiz_score_pct != null
                            ? `${Math.round(Number(educationPlan.progress.quiz_score_pct))}%`
                            : "Complete"}
                        </p>
                      ) : null}
                    </div>
                    <div className="mt-3 space-y-4">
                      {educationQuizQuestions.map((question, index) => {
                        const questionId = Number(question?.id || 0);
                        const selectedAnswer = educationQuizAnswers[String(questionId)] ?? question?.submitted_answer;
                        const options = educationQuizOptions(question);
                        const answered = question?.submitted_answer !== undefined && question?.submitted_answer !== null;
                        const isCorrect = typeof question?.is_correct === "boolean" ? question.is_correct : null;
                        const correctAnswerLabel = educationQuizAnswerLabel(question?.correct_answer);
                        return (
                          <div key={questionId || index}>
                            <div className="flex items-start justify-between gap-3">
                              <p className="text-sm font-semibold text-[#1e1b16]">
                                {question?.question_text || `Question ${index + 1}`}
                              </p>
                              {answered && isCorrect !== null ? (
                                <p className={`shrink-0 text-xs font-semibold ${isCorrect ? "text-[#317a4d]" : "text-[#9a3f2d]"}`}>
                                  {isCorrect ? "Correct" : "Not quite"}
                                </p>
                              ) : null}
                            </div>
                            {options.length ? (
                              <div className="mt-2 grid gap-2 sm:grid-cols-2">
                                {options.map((option) => {
                                  const active = selectedAnswer === option;
                                  return (
                                    <button
                                      key={option}
                                      type="button"
                                      onClick={() => selectEducationQuizAnswer(questionId, option)}
                                      disabled={educationQuizCompleted || educationQuizSubmitting}
                                      className={`rounded-[14px] border px-3 py-2 text-left text-sm transition ${
                                        active && answered && isCorrect === true
                                          ? "border-[#7fb48f] bg-white text-[#1e1b16]"
                                          : active && answered && isCorrect === false
                                            ? "border-[#c98977] bg-white text-[#1e1b16]"
                                            : active
                                          ? "border-[var(--accent)] bg-white text-[#1e1b16]"
                                          : "border-[#efe7db] bg-white text-[#6b6257]"
                                      } disabled:cursor-not-allowed disabled:opacity-70`}
                                    >
                                      {option}
                                    </button>
                                  );
                                })}
                              </div>
                            ) : null}
                            {answered && isCorrect === false && correctAnswerLabel ? (
                              <p className="mt-2 text-xs text-[#6b6257]">Correct answer: {correctAnswerLabel}</p>
                            ) : null}
                            {answered && question?.explanation ? (
                              <p className="mt-2 text-xs leading-5 text-[#6b6257]">{question.explanation}</p>
                            ) : null}
                          </div>
                        );
                      })}
                    </div>
                    {educationPlan.takeaway ? (
                      <p className="mt-4 text-sm leading-6 text-[#5d5348]">{educationPlan.takeaway}</p>
                    ) : null}
                    {educationQuizMessage ? (
                      <p className="mt-3 text-sm text-[#8a3e1a]">{educationQuizMessage}</p>
                    ) : null}
                    {!educationQuizCompleted ? (
                      <div className="sticky bottom-0 -mx-4 mt-4 bg-[#fffaf3]/95 px-4 py-3 backdrop-blur">
                        <button
                          type="button"
                          onClick={() => void submitEducationQuiz()}
                          disabled={educationQuizSubmitting}
                          className="w-full rounded-full border border-[var(--accent)] bg-[var(--accent)] px-4 py-2 text-xs font-semibold uppercase tracking-[0.16em] text-white disabled:cursor-not-allowed disabled:opacity-60"
                        >
                          {educationQuizSubmitting ? "Saving" : "Submit quick check"}
                        </button>
                      </div>
                    ) : null}
                  </div>
                ) : null}
                {educationPlanError ? <p className="text-sm text-[#8a3e1a]">{educationPlanError}</p> : null}
              </div>
            ) : (
              <div className="flex min-h-full items-center rounded-[24px] border border-[#efe7db] bg-[#fffaf3] px-4 py-5">
                <p className="text-sm text-[#6b6257]">
                  {educationPlanError || educationPlan?.reason || "Today's lesson is not available right now."}
                </p>
              </div>
            )
          ) : homeSurface === "habits" ? (
            <div className="flex min-h-full flex-col">
              {dailyHabitPlanLoading && !dailyHabitPlan ? (
                <div className="flex min-h-full items-center rounded-[24px] border border-[#efe7db] bg-[#fffaf3] px-4 py-5">
                  <p className="text-sm text-[#6b6257]">
                    Reviewing your tracker and preparing today&apos;s plan…
                  </p>
                </div>
              ) : dailyHabitPlanError && !dailyHabitPlan ? (
                <div className="flex min-h-full items-center rounded-[24px] border border-[#efe7db] bg-[#fffaf3] px-4 py-5">
                  <p className="text-sm text-[#8a3e1a]">{dailyHabitPlanError}</p>
                </div>
              ) : (
                <div className="flex min-h-full flex-col">
                  {dailyHabitPlan?.title ? <p className="text-sm font-semibold text-[#1e1b16]">{dailyHabitPlan.title}</p> : null}
                  {dailyHabitPlan?.summary ? <p className="text-sm text-[#6b6257]">{dailyHabitPlan.summary}</p> : null}
                  {dailyHabitPlanLoading && dailyHabitPlan ? (
                    <p className="text-sm text-[#6b6257]">Refreshing today&apos;s plan…</p>
                  ) : null}
                  {dailyHabits.length ? (
                    <div className="mt-4 grid auto-rows-fr gap-3 md:grid-cols-3">
                      {dailyHabits.map((habit, index) => {
                        const momentLabel = String(habit?.moment_label || "").trim();
                        const title = String(habit?.title || "").trim();
                        const detail = String(habit?.detail || "").trim();
                        if (!title && !detail) return null;
                        return (
                          <div
                            key={`${String(habit?.id || "").trim() || `${title || detail}-${index}`}`}
                            className="rounded-[24px] border border-[#efe7db] bg-[#fffaf3] px-4 py-4"
                          >
                            <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-[var(--accent)]">
                              {momentLabel || `Moment ${index + 1}`}
                            </p>
                            {title ? <p className="mt-2 text-sm font-semibold text-[#1e1b16]">{title}</p> : null}
                            {detail ? <p className="mt-2 text-sm leading-6 text-[#6b6257]">{detail}</p> : null}
                          </div>
                        );
                      })}
                    </div>
                  ) : (
                    <div className="flex min-h-full items-center rounded-[24px] border border-[#efe7db] bg-[#fffaf3] px-4 py-5 text-sm text-[#6b6257]">
                      Today&apos;s plan is not available right now.
                    </div>
                  )}
                  {dailyHabitPlanError ? <p className="text-sm text-[#8a3e1a]">{dailyHabitPlanError}</p> : null}
                </div>
              )}
            </div>
          ) : (
            <div className="flex min-h-full flex-col">
              <div className="flex min-h-full flex-col justify-center">
                {finalGiaMessageLoading ? (
                  <div className="rounded-[24px] border border-[#efe7db] bg-[#fffaf3] px-4 py-5">
                    <p className="text-sm font-semibold text-[#1e1b16]">Gia is reviewing today&apos;s tracker results…</p>
                    <p className="mt-2 text-sm leading-6 text-[#6b6257]">
                      Preparing your message based on the latest results you entered.
                    </p>
                  </div>
                ) : finalGiaMessage ? (
                  <div className="rounded-[24px] border border-[#efe7db] bg-[#fffaf3] px-4 py-5 sm:px-5 sm:py-6">
                    <div className="flex items-center justify-between gap-3">
                      <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[var(--accent)]">Gia</p>
                      <button
                        type="button"
                        onClick={toggleFinalGiaListening}
                        aria-pressed={finalGiaListening}
                        className="rounded-full border border-[#d9cdbb] bg-white px-4 py-2 text-xs font-semibold uppercase tracking-[0.16em] text-[#5d5348]"
                      >
                        {finalGiaListening ? "Stop" : "Listen"}
                      </button>
                    </div>
                    {finalGiaListenError ? (
                      <p className="mt-2 text-sm text-[#8a3e1a]">{finalGiaListenError}</p>
                    ) : finalGiaListening ? (
                      <p className="mt-2 text-xs uppercase tracking-[0.16em] text-[#8c7f70]">Playing Gia&apos;s message</p>
                    ) : null}
                    <p className="mt-3 whitespace-pre-wrap text-[21px] leading-8 text-[#3c332b] sm:text-[24px] sm:leading-9">
                      {finalGiaMessage}
                    </p>
                  </div>
                ) : (
                  <div className="rounded-[24px] border border-[#efe7db] bg-[#fffaf3] px-4 py-5">
                    <p className="text-sm text-[#8a3e1a]">
                      {finalGiaMessageError || "Gia's message is not available right now."}
                    </p>
                    <button
                      type="button"
                      onClick={() => {
                        setFinalGiaMessageError(null);
                        setFinalGiaListenError(null);
                        stopFinalGiaListening();
                        void requestFinalGiaMessage();
                      }}
                      className="mt-4 rounded-full border border-[var(--accent)] bg-[var(--accent)] px-4 py-2 text-xs font-semibold uppercase tracking-[0.16em] text-white"
                    >
                      Try again
                    </button>
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
        <div className="border-t border-[#efe7db] px-4 py-3 sm:px-5">
          {viewingHomeSurfaceFromSummary ? (
            <div className="flex justify-end">
              <button
                type="button"
                onClick={() => setJourneyCompleted(true)}
                className="rounded-full border border-[#d9cdbb] bg-white px-4 py-2 text-xs font-semibold uppercase tracking-[0.16em] text-[#5d5348]"
              >
                Close
              </button>
            </div>
          ) : (
            <div className="flex items-center justify-between gap-2">
              <div className="text-[11px] uppercase tracking-[0.16em] text-[#8c7f70]">
                {`${currentHomeSurfaceIndex + 1} of ${HOME_SURFACE_SEQUENCE.length}`}
              </div>
              <div className="flex gap-2">
                {previousHomeSurface ? (
                  <button
                    type="button"
                    onClick={() => setHomeSurface(previousHomeSurface)}
                    className="rounded-full border border-[#d9cdbb] bg-white px-4 py-2 text-xs font-semibold uppercase tracking-[0.16em] text-[#5d5348]"
                  >
                    Back
                  </button>
                ) : null}
                {nextHomeSurface && homeSurfaceMeta.nextLabel ? (
                  <button
                    type="button"
                    onClick={() => setHomeSurface(nextHomeSurface)}
                    className="rounded-full border border-[var(--accent)] bg-[var(--accent)] px-4 py-2 text-xs font-semibold uppercase tracking-[0.16em] text-white"
                  >
                    {homeSurfaceMeta.nextLabel}
                  </button>
                ) : homeSurface === "ask" ? (
                  <button
                    type="button"
                    onClick={() => completeMorningSequence()}
                    disabled={finalGiaMessageLoading || !finalGiaMessage}
                    className="rounded-full border border-[var(--accent)] bg-[var(--accent)] px-4 py-2 text-xs font-semibold uppercase tracking-[0.16em] text-white disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    Completed
                  </button>
                ) : null}
              </div>
            </div>
          )}
        </div>
      </div>
    </section>
  ) : null;

  return (
    <div className="space-y-4">
      {showAssessmentControls ? (
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            className="rounded-full border border-[var(--accent)] bg-[var(--accent)] px-4 py-2 text-xs uppercase tracking-[0.2em] text-white disabled:cursor-not-allowed disabled:opacity-60"
            disabled={busy}
            onClick={() => void startAssessment(false)}
          >
            {starting ? "Starting…" : hasActiveSession ? "Continue assessment" : "Start assessment"}
          </button>
          <button
            type="button"
            className="rounded-full border border-[var(--border)] bg-[var(--surface-muted)] px-4 py-2 text-xs uppercase tracking-[0.2em] text-[var(--text-primary)] transition-colors disabled:cursor-not-allowed disabled:opacity-60"
            disabled={busy}
            onClick={() => void startAssessment(true)}
          >
            Restart
          </button>
        </div>
      ) : null}

      {currentPrompt ? (
        <div className="space-y-4">
          <AssessmentPromptCard
            prompt={currentPrompt}
            busy={busy}
            selectedValue={selectedPromptValue}
            showLeadBranding={showLeadBranding}
            introAvatar={introAvatar}
            introAvatarEnabledOverride={introAvatarEnabledOverride}
            onSelect={onPromptOptionClick}
            onRedo={onPromptRedo}
            onRestart={onPromptRestart}
          />
        </div>
      ) : showResultCard ? (
        <div key="assessment-results-card" className="space-y-4">
          {resultCard}
          {coachingPlanPanel}
        </div>
      ) : null}

      {homeChatPanel}

      {!showGuidedHomeChatPanel && !assessmentCompleted && !currentPrompt && !showResultCard ? (
        <form onSubmit={onSubmit}>
          <textarea
            id="assessment-chat-input"
            className="w-full rounded-[24px] border border-[#efe7db] bg-white px-4 py-3 text-sm shadow-[0_18px_50px_-40px_rgba(30,27,22,0.35)]"
            rows={2}
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={onDraftKeyDown}
            disabled={busy}
          />
        </form>
      ) : null}

      {!showGuidedHomeChatPanel && status ? <p className="text-sm text-[#6b6257]">{status}</p> : null}
    </div>
  );
}
