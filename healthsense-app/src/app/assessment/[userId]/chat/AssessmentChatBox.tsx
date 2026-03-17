"use client";

import { useSearchParams } from "next/navigation";
import { FormEvent, KeyboardEvent, useCallback, useEffect, useMemo, useState } from "react";
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

function parseApiError(text: string, fallback: string) {
  if (!text) return fallback;
  try {
    const parsed = JSON.parse(text) as { error?: string; detail?: string };
    const message = parsed.error || parsed.detail || text;
    const normalized = String(message || "").trim().toLowerCase();
    if (!normalized || normalized === "internal server error") {
      return fallback;
    }
    return message;
  } catch {
    const normalized = String(text || "").trim().toLowerCase();
    if (!normalized || normalized === "internal server error") {
      return fallback;
    }
    return text;
  }
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

function looksLikeEmail(value: string): boolean {
  const token = String(value || "").trim().toLowerCase();
  if (!token) return false;
  if (!token.includes("@")) return false;
  const domain = token.split("@")[1] || "";
  return domain.includes(".");
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
  const [claimEmail, setClaimEmail] = useState("");
  const [claiming, setClaiming] = useState(false);
  const [showCoachingPlan, setShowCoachingPlan] = useState(false);
  const [coachingInterestSubmitting, setCoachingInterestSubmitting] = useState(false);
  const [coachingInterestLogged, setCoachingInterestLogged] = useState(false);
  const [coachingInterestError, setCoachingInterestError] = useState<string | null>(null);
  const [completionSummaryMedia, setCompletionSummaryMedia] =
    useState<AssessmentCompletionSummaryMedia | null>(null);
  const [completionSummaryLoading, setCompletionSummaryLoading] = useState(false);
  const [completionSummaryError, setCompletionSummaryError] = useState<string | null>(null);
  const [loadedCompletionSummaryRunId, setLoadedCompletionSummaryRunId] = useState<number | null>(null);
  const [completionSummaryVideoSeen, setCompletionSummaryVideoSeen] = useState(false);
  const [summaryDetailMode, setSummaryDetailMode] = useState<"read" | "listen" | null>(null);
  const [realtimeSummaryPhase, setRealtimeSummaryPhase] = useState<
    "idle" | "preparing" | "playing" | "completed" | "failed" | "stopped" | "timeout"
  >("idle");
  const [loading, setLoading] = useState(true);
  const [starting, setStarting] = useState(false);
  const [sending, setSending] = useState(false);

  const autoStart = useMemo(() => isTruthyToken(searchParams?.get("autostart")), [searchParams]);
  const leadFlow = useMemo(() => isTruthyToken(searchParams?.get("lead")), [searchParams]);
  const leadTokenQuery = useMemo(() => {
    const token = String(leadToken || "").trim();
    return token ? `&lt=${encodeURIComponent(token)}` : "";
  }, [leadToken]);
  const busy = loading || starting || sending || claiming;
  const chatReady = hasActiveSession || assessmentCompleted || messages.length > 0;
  const promptActive = Boolean(currentPrompt);
  const showResultsGate = Boolean(resultSummary) && !promptActive && identityRequired;
  const showResultCard = Boolean(resultSummary) && !promptActive && !identityRequired;
  const showAssessmentControls = !assessmentCompleted && !isLeadGuest && !promptActive && (!leadFlow || !chatReady);
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
    !completionSummaryVideoSeen;
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
  const showRealtimeSummaryIntroMessage =
    Boolean(completionSummaryUsesRealtime && completionSummaryRunId) &&
    !completionSummaryError &&
    (completionSummaryBootstrapPending ||
      realtimeSummaryPhase === "idle" ||
      realtimeSummaryPhase === "preparing");
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

  const applyChatPayload = useCallback((data: ChatResponse) => {
    const nextPrompt = normalizeCurrentPrompt(data.current_prompt);
    const persistedMessages = normalizeMessages(data.messages);
    const fallbackOutboxMessages = normalizeMessages(data.outbox);
    setMessages(persistedMessages.length > 0 ? persistedMessages : fallbackOutboxMessages);
    setHasActiveSession(Boolean(data.has_active_session));
    setCurrentPrompt(nextPrompt);
    setResultSummary(normalizeResultSummary(data.result_summary));
    setSelectedPromptValue(null);
    setIdentityRequired(Boolean(data.identity_required));
  }, []);

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

  useEffect(() => {
    let cancelled = false;
    const run = async () => {
      setLoading(true);
      setStatus(null);
      try {
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
        if (cancelled) return;
        applyChatPayload(data);
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
  }, [userId, autoStart, leadFlow, assessmentCompleted, startAssessment, applyChatPayload, isLeadGuest, leadTokenQuery]);

  useEffect(() => {
    let cancelled = false;
    const poll = async () => {
      try {
        const res = await fetch(`/api/assessment/chat/state?userId=${encodeURIComponent(userId)}${leadTokenQuery}`, {
          method: "GET",
          cache: "no-store",
        });
        if (!res.ok) return;
        const text = await res.text().catch(() => "");
        if (!text) return;
        let data: ChatResponse = {};
        try {
          data = JSON.parse(text) as ChatResponse;
        } catch {
          return;
        }
        if (cancelled) return;
        applyChatPayload(data);
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
  }, [userId, applyChatPayload, leadTokenQuery]);

  useEffect(() => {
    setShowCoachingPlan(false);
    setCoachingInterestSubmitting(false);
    setCoachingInterestLogged(false);
    setCoachingInterestError(null);
    setCompletionSummaryMedia(null);
    setCompletionSummaryError(null);
    setCompletionSummaryLoading(false);
    setLoadedCompletionSummaryRunId(null);
    setRealtimeSummaryPhase("idle");
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
    const email = claimEmail.trim().toLowerCase();
    if (!firstName || !surname) {
      setStatus("First name and surname are required.");
      return;
    }
    if (!phone && !email) {
      setStatus("Add either a mobile number or an email address to continue.");
      return;
    }
    if (email && !looksLikeEmail(email)) {
      setStatus("That email doesn’t look right. Please check it.");
      return;
    }

    setClaiming(true);
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
          email,
          lead_token: leadToken || undefined,
          consent: true,
        }),
      });
      const text = await res.text().catch(() => "");
      if (!res.ok) {
        throw new Error(parseApiError(text, "Failed to save your details."));
      }
      if (text) {
        JSON.parse(text);
      }
      setIdentityRequired(false);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : String(error));
    } finally {
      setClaiming(false);
    }
  }

  async function onCoachingPlanClick() {
    if (showCoachingPlan) {
      return;
    }
    setShowCoachingPlan(true);
  }

  async function onCoachingInterestClick() {
    if (coachingInterestSubmitting || coachingInterestLogged) {
      return;
    }
    setCoachingInterestSubmitting(true);
    setCoachingInterestError(null);
    try {
      const res = await fetch("/api/engagement", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          userId,
          event_type: "coaching_interest",
          surface: "assessment_results",
          meta: {
            surface: "assessment_results",
            source: "personal_coaching_plan",
            component: "how_healthsense_works",
          },
        }),
      });
      const text = await res.text().catch(() => "");
      if (!res.ok) {
        throw new Error(parseApiError(text, "Failed to record your interest."));
      }
      setCoachingInterestLogged(true);
    } catch (error) {
      setCoachingInterestError(error instanceof Error ? error.message : String(error));
    } finally {
      setCoachingInterestSubmitting(false);
    }
  }

  const resultExtremes = resultSummary ? resultPillarExtremes(resultSummary.pillars) : { strongest: null, weakest: null };
  const sortedResultPillars = resultSummary ? sortResultPillars(resultSummary.pillars) : [];
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

              {showRealtimeSummaryIntroMessage ? (
                <p className="text-sm text-[#6b6257]">{summaryIntroMessage}</p>
              ) : null}

              {!completionSummaryUsesRealtime && (completionSummaryPending || completionSummaryLoading) ? (
                <p className="text-sm text-[#6b6257]">{summaryIntroMessage}</p>
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

            <div className="border-t border-[#eadfce] pt-4">
              <button
                type="button"
                onClick={() => void onCoachingPlanClick()}
                className="rounded-full border border-[var(--accent)] bg-[var(--accent)] px-4 py-2 text-center text-xs font-semibold uppercase tracking-[0.18em] whitespace-normal text-white disabled:cursor-not-allowed disabled:opacity-60"
              >
                View your personal coaching plan and find out how HealthSense works
              </button>
            </div>
          </>
        ) : null}
      </div>
    </section>
  ) : null;

  const coachingPlanPanel = showCoachingPlan ? (
    <section className="overflow-hidden rounded-[28px] border border-[#e7e1d6] bg-white shadow-[0_30px_80px_-60px_rgba(30,27,22,0.45)]">
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
        <div>
          <button
            type="button"
            onClick={() => void onCoachingInterestClick()}
            disabled={coachingInterestSubmitting || coachingInterestLogged}
            className="w-full rounded-full border border-[var(--accent)] bg-[var(--accent)] px-4 py-3 text-center text-xs font-semibold uppercase tracking-[0.18em] whitespace-normal text-white disabled:cursor-not-allowed disabled:opacity-60"
          >
            {coachingInterestLogged
              ? "Your place has been secured."
              : coachingInterestSubmitting
                ? "Saving interest…"
                : "Click here to secure your space"}
          </button>
          {coachingInterestError ? (
            <p className="mt-2 text-sm text-[#8a3e1a]">{coachingInterestError}</p>
          ) : null}
        </div>
      </div>
    </section>
  ) : null;

  const resultsGate = resultSummary ? (
    <form onSubmit={onClaimIdentity} className="space-y-4" autoComplete="on">
      <section className="rounded-[28px] border border-[#e7e1d6] bg-[#fffaf3] px-4 py-6 shadow-[0_30px_80px_-60px_rgba(30,27,22,0.45)] sm:px-6 sm:py-8">
        <div className="space-y-4">
          <div className="space-y-2">
            <h2 className="text-2xl text-[#1e1b16]">Your details</h2>
            <p className="text-sm text-[#6b6257]">
              Please add your first name, surname, and either a mobile number or email address.
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
              disabled={claiming}
              required
            />
            <input
              className="rounded-xl border border-[#efe7db] bg-white px-3 py-2 text-sm"
              type="text"
              placeholder="Surname"
              autoComplete="family-name"
              value={claimSurname}
              onChange={(event) => setClaimSurname(event.target.value)}
              disabled={claiming}
              required
            />
            <input
              className="rounded-xl border border-[#efe7db] bg-white px-3 py-2 text-sm"
              type="tel"
              placeholder="Mobile number"
              autoComplete="tel"
              value={claimPhone}
              onChange={(event) => setClaimPhone(event.target.value)}
              disabled={claiming}
            />
            <input
              className="rounded-xl border border-[#efe7db] bg-white px-3 py-2 text-sm"
              type="email"
              placeholder="Email address"
              autoComplete="email"
              value={claimEmail}
              onChange={(event) => setClaimEmail(event.target.value)}
              disabled={claiming}
            />
          </div>
        </div>
      </section>

      <section className="rounded-[28px] border border-[#e7e1d6] bg-[#fffaf3] px-4 py-6 shadow-[0_30px_80px_-60px_rgba(30,27,22,0.45)] sm:px-6 sm:py-8">
        <div className="space-y-4">
          <div className="space-y-2">
            <h2 className="text-2xl text-[#1e1b16]">Confirm your consent</h2>
          </div>

          <div className="space-y-3 text-sm text-[#6b6257]">
            <div className="rounded-2xl border border-[#efe7db] bg-white px-4 py-4 text-[#3c332b]">
              <p className="mt-2">Your answers are stored securely and only used to personalise your wellbeing programme.</p>
              <p className="mt-2">We never share your information with third parties, and you can stop at any time.</p>
              <p className="mt-2">Replying is optional, and you can request deletion of your data whenever you want.</p>
            </div>
          </div>

          <div className="flex flex-wrap gap-2">
            <button
              type="submit"
              className="rounded-full border border-[var(--accent)] bg-[var(--accent)] px-4 py-2 text-xs font-semibold uppercase tracking-[0.18em] text-white disabled:cursor-not-allowed disabled:opacity-60"
              disabled={claiming}
            >
              {claiming ? "Saving…" : "Confirm consent for results and personal coaching plan"}
            </button>
          </div>
        </div>
      </section>
    </form>
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
            className="rounded-full border border-[#efe7db] bg-white px-4 py-2 text-xs uppercase tracking-[0.2em] text-[#3c332b] disabled:cursor-not-allowed disabled:opacity-60"
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
      ) : showResultsGate ? (
        resultsGate
      ) : showResultCard && showCoachingPlan ? (
        <div key="coaching-plan-card" className="space-y-4">{coachingPlanPanel}</div>
      ) : showResultCard ? (
        <div key="assessment-results-card" className="space-y-4">{resultCard}</div>
      ) : null}

      {!currentPrompt && !showResultCard && !showResultsGate ? (
        <form onSubmit={onSubmit} className="flex flex-col gap-3 sm:flex-row sm:items-end">
          <div className="flex-1">
            <label htmlFor="assessment-chat-input" className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">
              Your reply
            </label>
            <textarea
              id="assessment-chat-input"
              className="mt-2 w-full rounded-2xl border border-[#efe7db] bg-white px-3 py-2 text-sm"
              rows={3}
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={onDraftKeyDown}
              placeholder="Type your answer…"
              disabled={busy}
            />
            <p className="mt-2 text-[11px] text-[#8c7f70]">Press Enter to send, Shift+Enter for a new line.</p>
          </div>
          <button
            type="submit"
            className="rounded-full border border-[var(--accent)] bg-[var(--accent)] px-5 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-60"
            disabled={busy || !draft.trim()}
          >
            {sending ? "Sending…" : "Send"}
          </button>
        </form>
      ) : null}

      {status ? <p className="text-sm text-[#6b6257]">{status}</p> : null}
    </div>
  );
}
