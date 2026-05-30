"use client";

import { useEffect, useMemo, useRef, useState } from "react";

type IntroPayload = {
  enabled?: boolean;
  should_show?: boolean;
  content_id?: number | null;
  title?: string | null;
  message?: string | null;
  body?: string | null;
  podcast_url?: string | null;
};

type IntroWelcomeModalProps = {
  userId: string | number;
  intro?: IntroPayload | null;
};

export default function IntroWelcomeModal({ userId, intro }: IntroWelcomeModalProps) {
  const [dismissed, setDismissed] = useState(false);
  const [readOpen, setReadOpen] = useState(false);
  const [completed, setCompleted] = useState(false);
  const presentedRef = useRef(false);
  const listenedRef = useRef(false);
  const readRef = useRef(false);

  const shouldShow = Boolean(intro?.enabled && intro?.should_show && !dismissed);
  const hasPodcast = Boolean((intro?.podcast_url || "").trim());
  const hasBody = Boolean((intro?.body || "").trim());

  const eventBaseMeta = useMemo(
    () => ({
      surface: "intro_modal",
      content_id: intro?.content_id ?? null,
      podcast_id: intro?.content_id ?? null,
    }),
    [intro?.content_id],
  );

  const sendEvent = (eventType: "intro_presented" | "intro_listened" | "intro_read") => {
    fetch("/api/engagement", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        userId,
        event_type: eventType,
        surface: "intro_modal",
        podcast_id: intro?.content_id ?? null,
        meta: eventBaseMeta,
      }),
      cache: "no-store",
    }).catch(() => {
      // Best-effort telemetry only.
    });
  };

  useEffect(() => {
    if (!shouldShow) return;
    if (presentedRef.current) return;
    presentedRef.current = true;
    sendEvent("intro_presented");
  }, [shouldShow]);

  if (!shouldShow) return null;

  const onListenComplete = () => {
    if (listenedRef.current) return;
    listenedRef.current = true;
    sendEvent("intro_listened");
    setCompleted(true);
  };

  const onReadOpen = () => {
    setReadOpen(true);
    if (readRef.current) return;
    readRef.current = true;
    sendEvent("intro_read");
    setCompleted(true);
  };

  const onContinue = () => {
    if (!completed && !hasPodcast && !hasBody) {
      onReadOpen();
    }
    setDismissed(true);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 px-4 py-6">
      <div className="w-full max-w-2xl rounded-3xl border border-[#e7e1d6] bg-white p-6 shadow-[0_30px_80px_-60px_rgba(30,27,22,0.5)]">
        <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">{intro?.title || "Welcome"}</p>
        <p className="mt-3 whitespace-pre-wrap text-base text-[#1e1b16]">{intro?.message || "Welcome to HealthSense."}</p>

        {hasPodcast ? (
          <div className="mt-4 rounded-2xl border border-[#efe7db] bg-[#fdfaf4] p-3">
            <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Intro podcast</p>
            <audio controls className="mt-2 w-full" onEnded={onListenComplete}>
              <source src={intro?.podcast_url || ""} />
            </audio>
            <p className="mt-2 text-xs text-[#8a8176]">Listening to the end marks intro complete.</p>
          </div>
        ) : null}

        {hasBody ? (
          <div className="mt-4">
            <button
              type="button"
              onClick={onReadOpen}
              className="rounded-full border border-[#efe7db] px-4 py-2 text-xs uppercase tracking-[0.2em] text-[#3c332b]"
            >
              {readOpen ? "Read guide opened" : "Read instead"}
            </button>
            {readOpen ? (
              <div className="mt-3 max-h-64 overflow-y-auto whitespace-pre-wrap rounded-2xl border border-[#efe7db] bg-[#fdfaf4] p-3 text-sm text-[#3c332b]">
                {intro?.body}
              </div>
            ) : null}
          </div>
        ) : null}

        <div className="mt-5 flex flex-wrap items-center justify-end gap-2">
          <button
            type="button"
            onClick={onContinue}
            disabled={!completed && (hasPodcast || hasBody)}
            className="rounded-full border border-[var(--accent)] bg-[var(--accent)] px-5 py-2 text-xs uppercase tracking-[0.2em] text-white disabled:cursor-not-allowed disabled:opacity-60"
          >
            {completed || (!hasPodcast && !hasBody) ? "Continue to home" : "Continue"}
          </button>
        </div>
      </div>
    </div>
  );
}
