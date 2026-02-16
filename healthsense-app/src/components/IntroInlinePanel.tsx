"use client";

import { useEffect, useRef, useState } from "react";

type IntroPayload = {
  enabled?: boolean;
  content_id?: number | null;
  body?: string | null;
  podcast_url?: string | null;
};

type IntroInlinePanelProps = {
  userId: string | number;
  intro?: IntroPayload | null;
  introCompleted?: boolean;
};

export default function IntroInlinePanel({ userId, intro, introCompleted }: IntroInlinePanelProps) {
  const [readOpen, setReadOpen] = useState(false);
  const [audioError, setAudioError] = useState(false);
  const presentedRef = useRef(false);
  const listenedRef = useRef(false);
  const readRef = useRef(false);

  const enabled = Boolean(intro?.enabled);
  const completed = Boolean(introCompleted);
  const podcastUrl = String(intro?.podcast_url || "").trim();
  const hasPodcast = Boolean(podcastUrl);
  const hasBody = Boolean((intro?.body || "").trim());
  const show = enabled && !completed && (hasPodcast || hasBody);

  const sendEvent = (eventType: "intro_presented" | "intro_listened" | "intro_read") => {
    fetch("/api/engagement", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        userId,
        event_type: eventType,
        surface: "progress_home",
        podcast_id: intro?.content_id ?? null,
        meta: {
          surface: "progress_home",
          content_id: intro?.content_id ?? null,
          podcast_id: intro?.content_id ?? null,
        },
      }),
      cache: "no-store",
    }).catch(() => {
      // Best-effort telemetry only.
    });
  };

  useEffect(() => {
    if (!show || presentedRef.current) return;
    presentedRef.current = true;
    sendEvent("intro_presented");
  }, [show]);

  if (!show) return null;

  return (
    <div className="mt-3 rounded-xl border border-[#efe7db] bg-white p-3">
      {hasPodcast ? (
        <div>
          <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Intro podcast</p>
          <audio
            key={podcastUrl}
            controls
            preload="none"
            className="mt-2 w-full"
            src={podcastUrl}
            onPlay={() => {
              setAudioError(false);
            }}
            onError={() => {
              setAudioError(true);
            }}
            onEnded={() => {
              if (listenedRef.current) return;
              listenedRef.current = true;
              sendEvent("intro_listened");
            }}
          />
          <a
            href={podcastUrl}
            target="_blank"
            rel="noreferrer"
            className="mt-2 inline-flex text-[11px] uppercase tracking-[0.2em] text-[var(--accent)]"
          >
            Open audio
          </a>
          {audioError ? (
            <p className="mt-2 text-xs text-[#b42318]">Audio unavailable. Use Open audio or regenerate intro podcast.</p>
          ) : null}
        </div>
      ) : null}
      {hasBody ? (
        <details
          className={hasPodcast ? "mt-3" : ""}
          open={readOpen}
          onToggle={(e) => {
            const isOpen = (e.currentTarget as HTMLDetailsElement).open;
            setReadOpen(isOpen);
            if (!isOpen || readRef.current) return;
            readRef.current = true;
            sendEvent("intro_read");
          }}
        >
          <summary className="cursor-pointer text-xs uppercase tracking-[0.2em] text-[var(--accent)]">Read</summary>
          <div className="mt-2 rounded-xl border border-[#efe7db] bg-[#fffaf0] p-3 text-sm text-[#2f2a21]">
            {intro?.body}
          </div>
        </details>
      ) : null}
    </div>
  );
}
