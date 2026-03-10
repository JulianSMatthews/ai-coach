"use client";

import { FormEvent, useEffect, useMemo, useRef, useState } from "react";

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
  messages?: ChatMessage[];
  error?: string;
};

type AssessmentChatBoxProps = {
  userId: string;
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

export default function AssessmentChatBox({ userId }: AssessmentChatBoxProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [status, setStatus] = useState<string | null>(null);
  const [hasActiveSession, setHasActiveSession] = useState(false);
  const [loading, setLoading] = useState(true);
  const [starting, setStarting] = useState(false);
  const [sending, setSending] = useState(false);
  const logRef = useRef<HTMLDivElement | null>(null);

  const busy = loading || starting || sending;

  const messageCountLabel = useMemo(() => {
    const count = messages.length;
    if (count === 1) return "1 message";
    return `${count} messages`;
  }, [messages.length]);

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
          throw new Error(parseApiError(text, "Failed to load assessment chat."));
        }
        let data: ChatResponse = {};
        if (text) {
          try {
            data = JSON.parse(text) as ChatResponse;
          } catch {
            throw new Error("Assessment chat returned invalid JSON.");
          }
        }
        if (cancelled) return;
        setMessages(normalizeMessages(data.messages));
        setHasActiveSession(Boolean(data.has_active_session));
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
  }, [userId]);

  async function startAssessment(forceIntro = false) {
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
        throw new Error(parseApiError(text, "Failed to start assessment."));
      }
      const data = (text ? (JSON.parse(text) as ChatResponse) : {}) as ChatResponse;
      setMessages(normalizeMessages(data.messages));
      setHasActiveSession(Boolean(data.has_active_session));
      if (!data.handled && !data.has_active_session) {
        setStatus("Assessment is not active yet. Provide requested details in chat, then start again.");
      }
    } catch (error) {
      setStatus(error instanceof Error ? error.message : String(error));
    } finally {
      setStarting(false);
    }
  }

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
      setMessages(normalizeMessages(data.messages));
      setHasActiveSession(Boolean(data.has_active_session));
      if (data.needs_start) {
        setStatus("No active assessment session. Use Start assessment to begin.");
      }
    } catch (error) {
      setStatus(error instanceof Error ? error.message : String(error));
      setDraft(textValue);
    } finally {
      setSending(false);
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2 text-xs uppercase tracking-[0.2em] text-[#6b6257]">
        <span className="rounded-full border border-[#efe7db] bg-[#fffaf0] px-3 py-1">
          {hasActiveSession ? "Assessment active" : "Not active"}
        </span>
        <span className="rounded-full border border-[#efe7db] bg-white px-3 py-1">{messageCountLabel}</span>
      </div>

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
                    <p>{message.text}</p>
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
