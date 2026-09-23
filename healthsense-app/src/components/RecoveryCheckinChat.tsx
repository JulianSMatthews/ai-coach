"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { useCheckinVoice } from "@/lib/useCheckinVoice";

type Conversation = {
  phase?: "collecting" | "confirming" | "completed";
  score_date?: string;
  saved_date?: string;
  messages?: { role: "user" | "assistant"; text: string }[];
};

export default function RecoveryCheckinChat({ userId, onSaved }: {
  userId: string;
  onSaved: (date: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [conversation, setConversation] = useState<Conversation>({});
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const pending = useRef<{ text: string; id: string } | null>(null);
  const inFlight = useRef(false);
  const end = useRef<HTMLDivElement>(null);
  const voice = useCheckinVoice(userId, async (text) => {
    const result = await send(text);
    if (!result) throw new Error("Your message could not be completed. Resume to try again, or use text.");
    return [...(result.messages || [])].reverse().find((message) => message.role === "assistant")?.text || "";
  });

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    fetch(`/api/pillar-checkin?userId=${encodeURIComponent(userId)}`, { cache: "no-store" })
      .then(async (res) => {
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || "Could not load your conversation.");
        if (!cancelled) { setConversation(data); setReady(true); setError(null); }
      })
      .catch((err) => { if (!cancelled) setError(err.message); });
    return () => { cancelled = true; };
  }, [open, userId]);

  useEffect(() => { if (open) end.current?.scrollIntoView({ block: "nearest", behavior: "smooth" }); }, [conversation, open]);

  async function send(text: string): Promise<Conversation | null> {
    if (!text.trim() || inFlight.current || !ready) return null;
    inFlight.current = true;
    setBusy(true);
    setError(null);
    if (!pending.current || pending.current.text !== text) pending.current = { text, id: crypto.randomUUID() };
    try {
      const res = await fetch("/api/pillar-checkin", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ userId, text, request_id: pending.current.id }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Could not send your message.");
      setConversation(data);
      setDraft("");
      pending.current = null;
      if (data.phase === "completed" && conversation.phase !== "completed" && data.saved_date) onSaved(data.saved_date);
      return data as Conversation;
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not send your message.");
      return null;
    } finally { inFlight.current = false; setBusy(false); }
  }

  function submit(event: FormEvent) { event.preventDefault(); void send(draft.trim()); }
  const buttonClass = "rounded-full bg-[var(--action-primary-bg)] px-5 py-3 text-sm font-semibold text-[var(--action-primary-text)] disabled:opacity-45";

  return (
    <section className="rounded-[24px] bg-[var(--surface-muted)] p-5">
      <button type="button" aria-expanded={open} onClick={() => { voice.stop(); if (!open) setReady(false); setOpen(!open); }} className="text-sm font-semibold text-[var(--text-primary)]">
        {open ? "Close conversation" : "Talk to your coach"}
      </button>
      {!open ? <p className="mt-2 text-sm text-[var(--text-secondary)]">Complete today’s Recovery check-in by voice.</p> : (
        <div className="mt-4 space-y-4">
          <p className="text-sm text-[var(--text-secondary)]">Recovery{conversation.score_date ? ` · ${conversation.score_date}` : ""}. You can close this and resume later.</p>
          <div className="space-y-3">
            <button type="button" disabled={!ready || (busy && !voice.active)} onClick={() => voice.active ? voice.stop() : void voice.start(pending.current?.text || (conversation.phase ? "resume" : "start"))} className={buttonClass}>
              {voice.active ? "Pause voice conversation" : conversation.phase ? "Resume voice conversation" : "Start voice conversation"}
            </button>
            <p role="status" className="text-sm text-[var(--text-secondary)]">
              {voice.status === "listening" ? "Listening — speak your answer. You can say ‘pause’ at any time." : voice.status === "speaking" ? "Your coach is speaking…" : voice.status === "thinking" ? "Your coach is thinking…" : voice.status === "connecting" ? "Connecting your microphone…" : "Your coach will speak, then listen. You can correct answers and say ‘save’ to confirm."}
            </p>
            {voice.transcript ? <p className="text-sm italic text-[var(--text-secondary)]">{voice.transcript}</p> : null}
            {voice.error ? <p role="alert" className="text-sm text-[#8a3e1a]">{voice.error}</p> : null}
          </div>
          <div role="log" aria-label="Recovery check-in conversation" aria-live="polite" className="max-h-[50vh] space-y-3 overflow-y-auto">
            {(conversation.messages || []).map((message, index) => (
              <div key={index} className={`rounded-2xl p-4 ${message.role === "user" ? "ml-6 bg-[var(--surface)]" : "mr-6 bg-[var(--background)]"}`}>
                <p className="text-xs font-semibold text-[var(--text-secondary)]">{message.role === "user" ? "You" : "Coach"}</p>
                <p className="mt-1 whitespace-pre-wrap text-sm leading-6 text-[var(--text-primary)]">{message.text}</p>
              </div>
            ))}
            <div ref={end} />
          </div>
          {error ? <p role="alert" className="text-sm text-[#8a3e1a]">{error}</p> : null}
          {!ready ? <p className="text-sm text-[var(--text-secondary)]">{error ? "Close and reopen to try loading again." : "Loading your conversation…"}</p> : !conversation.phase ? (
            <button type="button" disabled={busy || voice.active} onClick={() => void send("start")} className="text-sm underline disabled:opacity-45">Use text instead</button>
          ) : (
            <details>
              <summary className="cursor-pointer text-sm text-[var(--text-secondary)]">Type instead</summary>
              <form onSubmit={submit} className="flex items-end gap-2">
                <label className="flex-1 text-sm text-[var(--text-secondary)]">
                  Your message
                  <textarea value={draft} onChange={(event) => setDraft(event.target.value)} maxLength={4000} disabled={busy || voice.active} rows={2} className="mt-1 block w-full rounded-xl border border-[var(--border)] bg-[var(--surface)] p-3 text-[var(--text-primary)]" placeholder={conversation.phase === "completed" ? "Share a reflection, or type edit to change your answers…" : "Tell your coach how things went…"} />
                </label>
                <button type="submit" disabled={busy || voice.active || !draft.trim()} className={buttonClass}>Send</button>
              </form>
              <div className="flex flex-wrap gap-2">
                {conversation.phase === "confirming" ? <button type="button" disabled={busy || voice.active} onClick={() => void send("save")} className={buttonClass}>Save check-in</button> : null}
                {conversation.phase === "completed" ? <button type="button" disabled={busy || voice.active} onClick={() => void send("edit")} className={buttonClass}>Edit answers</button> : null}
                <button type="button" disabled={busy || voice.active} onClick={() => void send("restart")} className="px-3 py-2 text-sm underline disabled:opacity-45">Start over for today</button>
              </div>
            </details>
          )}
          {busy ? <p role="status" className="text-sm text-[var(--text-secondary)]">Your coach is responding…</p> : null}
        </div>
      )}
    </section>
  );
}
