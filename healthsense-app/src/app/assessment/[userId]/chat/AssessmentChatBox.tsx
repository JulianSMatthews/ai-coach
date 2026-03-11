"use client";

import { useSearchParams } from "next/navigation";
import { type ReactNode, FormEvent, KeyboardEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import AssessmentPromptCard, {
  type AssessmentCurrentPrompt,
  type AssessmentPromptOption,
  type AssessmentPromptSection,
} from "./AssessmentPromptCard";

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
  messages?: ChatMessage[];
  user_id?: number | string;
  next_path?: string;
  error?: string;
};

type AssessmentChatBoxProps = {
  userId: string;
  assessmentCompleted?: boolean;
  isLeadGuest?: boolean;
};

type AssessmentCta = {
  cleanedText: string;
  href: string | null;
};

type QuickReplyPayload = {
  cleanedText: string;
  quickReplies: string[];
};

type QuickReplyOption = {
  label: string;
  value: string;
};

type MediaPayload = {
  cleanedText: string;
  mediaUrl: string | null;
  isPodcast: boolean;
};

function parseApiError(text: string, fallback: string) {
  if (!text) return fallback;
  try {
    const parsed = JSON.parse(text) as { error?: string; detail?: string };
    return parsed.error || parsed.detail || text;
  } catch {
    return text;
  }
}

function renderFormattedText(text: string): ReactNode {
  const raw = String(text || "");
  if (!raw.includes("*")) return raw;
  const parts = raw.split(/(\*[^*]+\*)/g).filter(Boolean);
  return parts.map((part, index) => {
    if (part.startsWith("*") && part.endsWith("*") && part.length > 2) {
      return (
        <strong key={`strong-${index}`} className="font-bold">
          {part.slice(1, -1)}
        </strong>
      );
    }
    return <span key={`text-${index}`}>{part}</span>;
  });
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

function normalizeCurrentPrompt(raw: unknown): AssessmentCurrentPrompt | null {
  if (!raw || typeof raw !== "object") return null;
  const row = raw as Record<string, unknown>;
  const kind = typeof row.kind === "string" ? row.kind.trim() : "";
  if (kind !== "concept_scale" && kind !== "readiness_scale") return null;
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
    options,
    sections,
  };
}

function resolveAssessmentHref(rawUrl: string, userId: string): string {
  const fallback = `/assessment/${encodeURIComponent(userId)}`;
  const candidate = String(rawUrl || "").trim();
  if (!candidate) return fallback;
  if (candidate.startsWith("/assessment/")) return candidate;
  try {
    const parsed = new URL(candidate);
    if (parsed.pathname.startsWith("/assessment/")) {
      return `${parsed.pathname}${parsed.search}${parsed.hash}`;
    }
  } catch {
    return fallback;
  }
  return fallback;
}

function extractAssessmentCta(text: string, userId: string): AssessmentCta {
  const raw = String(text || "");
  const marker = /View your assessment in the HealthSense app:\s*(https?:\/\/\S+|\/assessment\/\S+)/i;
  const match = raw.match(marker);
  if (!match) {
    return { cleanedText: raw, href: null };
  }
  const href = resolveAssessmentHref(match[1] || "", userId);
  const cleanedText = raw
    .replace(marker, "")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
  return { cleanedText, href };
}

function extractQuickReplies(text: string, quickRepliesFromMeta?: string[]): QuickReplyPayload {
  const raw = String(text || "");
  const metaReplies = Array.isArray(quickRepliesFromMeta)
    ? quickRepliesFromMeta
        .map((item) => String(item || "").trim())
        .filter((item) => Boolean(item))
        .slice(0, 6)
    : [];
  const marker = /\n{0,2}Quick replies:\s*([^\n]+)\s*$/i;
  const match = raw.match(marker);
  const footerReplies =
    match && !metaReplies.length
      ? String(match[1] || "")
          .split(/·|\||,/g)
          .map((item) => item.trim())
          .filter((item) => Boolean(item))
          .slice(0, 6)
      : [];
  const deduped = [...metaReplies, ...footerReplies].filter(
    (item, index, all) => all.indexOf(item) === index,
  );
  const cleanedText = raw
    .replace(marker, "")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
  return {
    cleanedText,
    quickReplies: deduped.slice(0, 6),
  };
}

function normalizeMediaUrl(raw: string | null | undefined): string | null {
  const candidate = String(raw || "").trim();
  if (!candidate) return null;
  if (!/^https?:\/\//i.test(candidate)) return null;
  return candidate;
}

function isPodcastUrl(url: string | null): boolean {
  const val = String(url || "").toLowerCase();
  if (!val) return false;
  return [".mp3", ".m4a", ".wav", ".aac", ".ogg", "podcast", "/audio", "audio/"].some((token) =>
    val.includes(token),
  );
}

function extractMediaPayload(text: string, mediaUrlFromMeta?: string | null): MediaPayload {
  const raw = String(text || "");
  let mediaUrl = normalizeMediaUrl(mediaUrlFromMeta);

  if (!mediaUrl) {
    const matches = raw.match(/https?:\/\/\S+/gi) || [];
    const likelyPodcast = [...matches].reverse().find((candidate) => isPodcastUrl(candidate));
    mediaUrl = normalizeMediaUrl(likelyPodcast || null);
  }

  if (!mediaUrl) {
    return {
      cleanedText: raw,
      mediaUrl: null,
      isPodcast: false,
    };
  }

  const cleanedText = raw
    .replace(mediaUrl, "")
    .replace(/\n{3,}/g, "\n\n")
    .trim();

  return {
    cleanedText,
    mediaUrl,
    isPodcast: isPodcastUrl(mediaUrl),
  };
}

function quickReplyOptions(quickReplies: string[]): QuickReplyOption[] {
  return quickReplies
    .map((raw) => {
      const value = String(raw || "").trim();
      if (!value) return null;
      if (value.includes("||")) {
        const [titleRaw, payloadRaw] = value.split("||", 2);
        const title = String(titleRaw || "").trim();
        const payload = String(payloadRaw || "").trim();
        return {
          label: title || payload || value,
          value: payload || title || value,
        };
      }
      return {
        label: value,
        value,
      };
    })
    .filter((item): item is QuickReplyOption => Boolean(item));
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

export default function AssessmentChatBox({
  userId,
  assessmentCompleted = false,
  isLeadGuest = false,
}: AssessmentChatBoxProps) {
  const searchParams = useSearchParams();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [status, setStatus] = useState<string | null>(null);
  const [hasActiveSession, setHasActiveSession] = useState(false);
  const [identityRequired, setIdentityRequired] = useState(false);
  const [currentPrompt, setCurrentPrompt] = useState<AssessmentCurrentPrompt | null>(null);
  const [selectedPromptValue, setSelectedPromptValue] = useState<string | null>(null);
  const [showIdentityGate, setShowIdentityGate] = useState(false);
  const [claimFirstName, setClaimFirstName] = useState("");
  const [claimSurname, setClaimSurname] = useState("");
  const [claimPhone, setClaimPhone] = useState("");
  const [claiming, setClaiming] = useState(false);
  const [pendingAssessmentHref, setPendingAssessmentHref] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [starting, setStarting] = useState(false);
  const [sending, setSending] = useState(false);
  const [showScrollToLatest, setShowScrollToLatest] = useState(false);
  const logRef = useRef<HTMLDivElement | null>(null);

  const autoStart = useMemo(() => isTruthyToken(searchParams?.get("autostart")), [searchParams]);
  const leadFlow = useMemo(() => isTruthyToken(searchParams?.get("lead")), [searchParams]);
  const busy = loading || starting || sending || claiming;
  const chatReady = hasActiveSession || assessmentCompleted || messages.length > 0;
  const promptActive = Boolean(currentPrompt);
  const showAssessmentControls = !assessmentCompleted && !isLeadGuest && !promptActive && (!leadFlow || !chatReady);

  const applyChatPayload = useCallback((data: ChatResponse) => {
    const nextPrompt = normalizeCurrentPrompt(data.current_prompt);
    setMessages(normalizeMessages(data.messages));
    setHasActiveSession(Boolean(data.has_active_session));
    setCurrentPrompt(nextPrompt);
    setSelectedPromptValue(null);
    const required = Boolean(data.identity_required);
    setIdentityRequired(required);
    if (!required) {
      setShowIdentityGate(false);
    }
  }, []);

  const startAssessment = useCallback(async (forceIntro = false) => {
    setStarting(true);
    setStatus(null);
    try {
      const res = await fetch("/api/assessment/chat/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ userId, force_intro: forceIntro }),
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
  }, [userId, assessmentCompleted, applyChatPayload]);

  const scrollToLatest = useCallback((behavior: ScrollBehavior = "smooth") => {
    const target = logRef.current;
    if (!target) return;
    target.scrollTo({ top: target.scrollHeight, behavior });
  }, []);

  const updateScrollCtaState = useCallback(() => {
    const target = logRef.current;
    if (!target) return;
    const remaining = target.scrollHeight - target.scrollTop - target.clientHeight;
    setShowScrollToLatest((current) => {
      const next = remaining > 96;
      return current === next ? current : next;
    });
  }, []);

  useEffect(() => {
    const target = logRef.current;
    if (!target) return;
    const onScroll = () => {
      updateScrollCtaState();
    };
    target.addEventListener("scroll", onScroll, { passive: true });
    updateScrollCtaState();
    return () => {
      target.removeEventListener("scroll", onScroll);
    };
  }, [messages.length, updateScrollCtaState]);

  useEffect(() => {
    let cancelled = false;
    const run = async () => {
      setLoading(true);
      setStatus(null);
      try {
        const res = await fetch(`/api/assessment/chat/state?userId=${encodeURIComponent(userId)}`, {
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
  }, [userId, autoStart, leadFlow, assessmentCompleted, startAssessment, applyChatPayload, isLeadGuest]);

  useEffect(() => {
    let cancelled = false;
    const poll = async () => {
      try {
        const res = await fetch(`/api/assessment/chat/state?userId=${encodeURIComponent(userId)}`, {
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
  }, [userId, applyChatPayload]);

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

  function onQuickReplyClick(reply: string, label?: string) {
    const textValue = String(reply || "").trim();
    if (!textValue || busy) return;
    void sendMessage(textValue, {
      quickReply: {
        used: true,
        hideInChat: true,
        label,
      },
    });
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

  function onAssessmentCtaClick(href: string) {
    if (!identityRequired) {
      if (typeof window !== "undefined") {
        window.location.href = href;
      }
      return;
    }
    setPendingAssessmentHref(href);
    setShowIdentityGate(true);
    setStatus("Please add your name and mobile number to unlock your results.");
  }

  async function onClaimIdentity(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const firstName = claimFirstName.trim();
    const surname = claimSurname.trim();
    const phone = claimPhone.trim();
    if (!firstName || !surname || !phone) {
      setStatus("First name, surname, and mobile number are required.");
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
        }),
      });
      const text = await res.text().catch(() => "");
      if (!res.ok) {
        throw new Error(parseApiError(text, "Failed to save your details."));
      }
      setIdentityRequired(false);
      setShowIdentityGate(false);
      const targetHref = pendingAssessmentHref || `/assessment/${encodeURIComponent(userId)}`;
      setPendingAssessmentHref(null);
      if (typeof window !== "undefined") {
        window.location.href = targetHref;
      }
    } catch (error) {
      setStatus(error instanceof Error ? error.message : String(error));
    } finally {
      setClaiming(false);
    }
  }

  const conversationLog = (
    <div className="relative">
      <div
        ref={logRef}
        className="max-h-[56vh] min-h-[320px] overflow-y-auto rounded-2xl border border-[#efe7db] bg-white p-4"
      >
        {messages.length === 0 ? (
          <p className="text-sm text-[#6b6257]">
            {leadFlow
              ? "Connecting you to Gia and preparing your assessment…"
              : assessmentCompleted
                ? "Gia is ready. Send your message to continue coaching."
                : hasActiveSession
                  ? "Your assessment is in progress. Continue by sending your next answer."
                  : "Start your assessment to begin chatting in-app."}
          </p>
        ) : (
          <div className="space-y-3">
            {messages.map((message, index) => {
              const isUser = (message.direction || "").toLowerCase() === "inbound";
              const cta = extractAssessmentCta(String(message.text || ""), userId);
              const quickReplyPayload = extractQuickReplies(cta.cleanedText, message.quick_replies);
              const mediaPayload = extractMediaPayload(quickReplyPayload.cleanedText, message.media_url);
              const options = quickReplyOptions(quickReplyPayload.quickReplies);
              const selectedQuickReply = String(message.selected_quick_reply || "").trim();
              const ts = message.created_at
                ? new Date(message.created_at).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" })
                : "";
              return (
                <div
                  key={`${message.id || "msg"}-${index}`}
                  className="flex justify-start"
                >
                  {isUser ? (
                    <div className="max-w-[95%] rounded-2xl bg-[#1e1b16] px-4 py-3 text-sm whitespace-pre-wrap text-white">
                      {mediaPayload.cleanedText ? <p>{renderFormattedText(mediaPayload.cleanedText)}</p> : null}
                      {ts ? <p className="mt-2 text-[10px] text-[#e6ddd1]">{ts}</p> : null}
                    </div>
                  ) : (
                    <div className="max-w-[95%] rounded-2xl border border-[#efe7db] bg-white px-4 py-3 text-sm leading-relaxed whitespace-pre-wrap text-[#3c332b]">
                      {mediaPayload.cleanedText ? <p>{renderFormattedText(mediaPayload.cleanedText)}</p> : null}
                      {cta.href ? (
                        <button
                          type="button"
                          onClick={() => onAssessmentCtaClick(cta.href || `/assessment/${encodeURIComponent(userId)}`)}
                          className="mt-3 inline-flex rounded-full border border-[var(--accent)] bg-[var(--accent)] px-3 py-1 text-xs font-semibold uppercase tracking-[0.18em] text-white"
                        >
                          {identityRequired ? "Add details to view results" : "View assessment"}
                        </button>
                      ) : null}
                      {mediaPayload.mediaUrl && mediaPayload.isPodcast ? (
                        <div className="mt-3 space-y-2">
                          <audio
                            controls
                            preload="none"
                            src={mediaPayload.mediaUrl}
                            className="w-full"
                          >
                            Your browser does not support audio playback.
                          </audio>
                          <a
                            href={mediaPayload.mediaUrl}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="inline-flex rounded-full border border-[#e0d4c3] bg-[#fff8ef] px-3 py-1 text-xs font-semibold text-[#3c332b]"
                          >
                            Open podcast in new tab
                          </a>
                        </div>
                      ) : null}
                      {mediaPayload.mediaUrl && !mediaPayload.isPodcast ? (
                        <a
                          href={mediaPayload.mediaUrl}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="mt-3 inline-flex rounded-full border border-[var(--accent)] bg-[var(--accent)] px-3 py-1 text-xs font-semibold uppercase tracking-[0.18em] text-white"
                        >
                          Open media
                        </a>
                      ) : null}
                      {options.length > 0 ? (
                        <div className="mt-3 flex flex-wrap gap-2">
                          {options.map((option, replyIndex) => {
                            const selected = Boolean(selectedQuickReply) && selectedQuickReply === option.value;
                            return (
                              <button
                                key={`quick-reply-${message.id || index}-${replyIndex}`}
                                type="button"
                                onClick={() => onQuickReplyClick(option.value, option.label)}
                                disabled={busy || selected}
                                title={option.value}
                                className={
                                  selected
                                    ? "rounded-full border border-[var(--accent)] bg-white px-3 py-1 text-xs font-semibold text-[var(--accent)]"
                                    : "rounded-full border border-[var(--accent)] bg-[var(--accent)] px-3 py-1 text-xs font-semibold text-white transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60"
                                }
                              >
                                {option.label}
                              </button>
                            );
                          })}
                        </div>
                      ) : null}
                      {ts ? <p className="mt-2 text-[10px] text-[#8c7f70]">{ts}</p> : null}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
      {showScrollToLatest ? (
        <button
          type="button"
          onClick={() => scrollToLatest("smooth")}
          className="absolute bottom-3 right-3 inline-flex h-10 w-10 items-center justify-center rounded-full border border-[#e0d4c3] bg-white text-lg text-[#3c332b] shadow-sm transition hover:bg-[#fff3dc]"
          aria-label="Jump to latest message"
          title="Latest message"
        >
          ↓
        </button>
      ) : null}
    </div>
  );

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
            onSelect={onPromptOptionClick}
            onRedo={onPromptRedo}
            onRestart={onPromptRestart}
          />
          <details className="rounded-2xl border border-[#efe7db] bg-white p-4">
            <summary className="cursor-pointer text-xs uppercase tracking-[0.2em] text-[#6b6257]">
              Conversation
            </summary>
            <div className="mt-4">{conversationLog}</div>
          </details>
        </div>
      ) : (
        conversationLog
      )}

      {showIdentityGate ? (
        <div className="rounded-2xl border border-[#efe7db] bg-white p-4">
          <h3 className="text-sm uppercase tracking-[0.2em] text-[#6b6257]">Unlock your results</h3>
          <p className="mt-2 text-sm text-[#6b6257]">
            Add your name and mobile number to view your assessment report.
          </p>
          <form onSubmit={onClaimIdentity} className="mt-3 grid gap-3 sm:grid-cols-2" autoComplete="on">
            <input
              className="rounded-xl border border-[#efe7db] bg-white px-3 py-2 text-sm"
              type="text"
              placeholder="First name"
              value={claimFirstName}
              onChange={(event) => setClaimFirstName(event.target.value)}
              disabled={claiming}
              required
            />
            <input
              className="rounded-xl border border-[#efe7db] bg-white px-3 py-2 text-sm"
              type="text"
              placeholder="Surname"
              value={claimSurname}
              onChange={(event) => setClaimSurname(event.target.value)}
              disabled={claiming}
              required
            />
            <input
              className="sm:col-span-2 rounded-xl border border-[#efe7db] bg-white px-3 py-2 text-sm"
              type="tel"
              placeholder="Mobile number (e.g. +447700900123)"
              value={claimPhone}
              onChange={(event) => setClaimPhone(event.target.value)}
              disabled={claiming}
              required
            />
            <div className="sm:col-span-2 flex flex-wrap gap-2">
              <button
                type="submit"
                className="rounded-full border border-[var(--accent)] bg-[var(--accent)] px-4 py-2 text-xs font-semibold uppercase tracking-[0.18em] text-white disabled:cursor-not-allowed disabled:opacity-60"
                disabled={claiming}
              >
                {claiming ? "Saving…" : "Save and view results"}
              </button>
              <button
                type="button"
                className="rounded-full border border-[#efe7db] bg-white px-4 py-2 text-xs uppercase tracking-[0.18em] text-[#3c332b]"
                onClick={() => setShowIdentityGate(false)}
                disabled={claiming}
              >
                Cancel
              </button>
            </div>
          </form>
        </div>
      ) : null}

      {!currentPrompt ? (
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
