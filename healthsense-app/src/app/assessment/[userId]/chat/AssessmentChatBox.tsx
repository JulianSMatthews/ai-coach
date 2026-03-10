"use client";

import { useSearchParams } from "next/navigation";
import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";

type ChatMessage = {
  id?: number;
  direction?: string;
  channel?: string;
  text?: string;
  created_at?: string | null;
};

type ChatResponse = {
  ok?: boolean;
  handled?: boolean;
  needs_start?: boolean;
  has_active_session?: boolean;
  identity_required?: boolean;
  messages?: ChatMessage[];
  error?: string;
};

type AssessmentChatBoxProps = {
  userId: string;
};

type AssessmentCta = {
  cleanedText: string;
  href: string | null;
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

function normalizeMessages(raw: unknown): ChatMessage[] {
  if (!Array.isArray(raw)) return [];
  const normalized: ChatMessage[] = [];
  raw.forEach((msg) => {
    if (!msg || typeof msg !== "object") return;
    const row = msg as Record<string, unknown>;
    const text = typeof row.text === "string" ? row.text : "";
    if (!text) return;
    normalized.push({
      id: typeof row.id === "number" ? row.id : undefined,
      direction: typeof row.direction === "string" ? row.direction : "",
      channel: typeof row.channel === "string" ? row.channel : "app",
      text,
      created_at: typeof row.created_at === "string" ? row.created_at : null,
    });
  });
  return normalized;
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

function isTruthyToken(value: string | null | undefined): boolean {
  const token = String(value || "").trim().toLowerCase();
  return token === "1" || token === "true" || token === "yes" || token === "on";
}

export default function AssessmentChatBox({ userId }: AssessmentChatBoxProps) {
  const searchParams = useSearchParams();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [status, setStatus] = useState<string | null>(null);
  const [hasActiveSession, setHasActiveSession] = useState(false);
  const [identityRequired, setIdentityRequired] = useState(false);
  const [showIdentityGate, setShowIdentityGate] = useState(false);
  const [claimFirstName, setClaimFirstName] = useState("");
  const [claimSurname, setClaimSurname] = useState("");
  const [claimPhone, setClaimPhone] = useState("");
  const [claiming, setClaiming] = useState(false);
  const [pendingAssessmentHref, setPendingAssessmentHref] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [starting, setStarting] = useState(false);
  const [sending, setSending] = useState(false);
  const logRef = useRef<HTMLDivElement | null>(null);

  const autoStart = useMemo(() => isTruthyToken(searchParams?.get("autostart")), [searchParams]);
  const busy = loading || starting || sending || claiming;

  const messageCountLabel = useMemo(() => {
    const count = messages.length;
    if (count === 1) return "1 message";
    return `${count} messages`;
  }, [messages.length]);

  function applyChatPayload(data: ChatResponse) {
    setMessages(normalizeMessages(data.messages));
    setHasActiveSession(Boolean(data.has_active_session));
    const required = Boolean(data.identity_required);
    setIdentityRequired(required);
    if (!required) {
      setShowIdentityGate(false);
    }
  }

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
      if (!data.handled && !data.has_active_session) {
        setStatus("Chat is not active yet. Provide requested details, then start chat again.");
      }
    } catch (error) {
      setStatus(error instanceof Error ? error.message : String(error));
    } finally {
      setStarting(false);
    }
  }, [userId]);

  useEffect(() => {
    if (!logRef.current) return;
    const target = logRef.current;
    target.scrollTop = target.scrollHeight;
  }, [messages]);

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
        if (autoStart && !Boolean(data.has_active_session)) {
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
  }, [userId, autoStart, startAssessment]);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const textValue = draft.trim();
    if (!textValue || sending) return;

    setSending(true);
    setStatus(null);
    setDraft("");

    try {
      const res = await fetch("/api/assessment/chat/send", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ userId, text: textValue }),
      });
      const text = await res.text().catch(() => "");
      if (!res.ok) {
        throw new Error(parseApiError(text, "Failed to send message."));
      }
      const data = (text ? (JSON.parse(text) as ChatResponse) : {}) as ChatResponse;
      applyChatPayload(data);
      if (data.needs_start) {
        setStatus("No active chat session. Use Start chat to begin.");
      }
    } catch (error) {
      setStatus(error instanceof Error ? error.message : String(error));
      setDraft(textValue);
    } finally {
      setSending(false);
    }
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

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2 text-xs uppercase tracking-[0.2em] text-[#6b6257]">
        <span className="rounded-full border border-[#efe7db] bg-[#fffaf0] px-3 py-1">
          {hasActiveSession ? "Chat active" : "Chat not started"}
        </span>
        {identityRequired ? (
          <span className="rounded-full border border-[#f5d0a0] bg-[#fff3dc] px-3 py-1">Results locked</span>
        ) : null}
        <span className="rounded-full border border-[#efe7db] bg-white px-3 py-1">{messageCountLabel}</span>
      </div>

      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          className="rounded-full border border-[var(--accent)] bg-[var(--accent)] px-4 py-2 text-xs uppercase tracking-[0.2em] text-white disabled:cursor-not-allowed disabled:opacity-60"
          disabled={busy}
          onClick={() => void startAssessment(false)}
        >
          {starting ? "Starting…" : hasActiveSession ? "Continue chat" : "Start chat"}
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

      <div
        ref={logRef}
        className="max-h-[56vh] min-h-[320px] overflow-y-auto rounded-2xl border border-[#efe7db] bg-[#fffaf0] p-4"
      >
        {messages.length === 0 ? (
          <p className="text-sm text-[#6b6257]">Start the assessment to begin chatting in-app.</p>
        ) : (
          <div className="space-y-3">
            {messages.map((message, index) => {
              const isUser = (message.direction || "").toLowerCase() === "inbound";
              const cta = extractAssessmentCta(String(message.text || ""), userId);
              const ts = message.created_at
                ? new Date(message.created_at).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" })
                : "";
              return (
                <div
                  key={`${message.id || "msg"}-${index}`}
                  className={`flex ${isUser ? "justify-end" : "justify-start"}`}
                >
                  <div
                    className={`max-w-[86%] rounded-2xl px-4 py-3 text-sm whitespace-pre-wrap ${
                      isUser
                        ? "bg-[var(--accent)] text-white"
                        : "border border-[#efe7db] bg-white text-[#3c332b]"
                    }`}
                  >
                    {cta.cleanedText ? <p>{cta.cleanedText}</p> : null}
                    {!isUser && cta.href ? (
                      <button
                        type="button"
                        onClick={() => onAssessmentCtaClick(cta.href || `/assessment/${encodeURIComponent(userId)}`)}
                        className="mt-3 inline-flex rounded-full border border-[var(--accent)] bg-[var(--accent)] px-3 py-1 text-xs font-semibold uppercase tracking-[0.18em] text-white"
                      >
                        {identityRequired ? "Add details to view results" : "View assessment"}
                      </button>
                    ) : null}
                    {ts ? (
                      <p className={`mt-2 text-[10px] ${isUser ? "text-[#f5e5d8]" : "text-[#8c7f70]"}`}>{ts}</p>
                    ) : null}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

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
            placeholder="Type your answer…"
            disabled={busy}
          />
        </div>
        <button
          type="submit"
          className="rounded-full border border-[var(--accent)] bg-[var(--accent)] px-5 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-60"
          disabled={busy || !draft.trim()}
        >
          {sending ? "Sending…" : "Send"}
        </button>
      </form>

      {status ? <p className="text-sm text-[#6b6257]">{status}</p> : null}
    </div>
  );
}
