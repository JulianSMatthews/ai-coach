"use client";

import { useEffect, useRef } from "react";

type TrackedAudioProps = {
  userId: string | number;
  src: string;
  surface: "assessment" | "library";
  podcastId?: string | number;
  className?: string;
};

export default function TrackedAudio({
  userId,
  src,
  surface,
  podcastId,
  className,
}: TrackedAudioProps) {
  const playLoggedRef = useRef(false);
  const completeLoggedRef = useRef(false);

  useEffect(() => {
    playLoggedRef.current = false;
    completeLoggedRef.current = false;
  }, [src, surface, podcastId]);

  const sendEvent = (eventType: "podcast_play" | "podcast_complete") => {
    fetch("/api/engagement", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        userId,
        event_type: eventType,
        surface,
        podcast_id: podcastId ?? null,
        meta: {
          surface,
          podcast_id: podcastId ?? null,
          src,
        },
      }),
      cache: "no-store",
    }).catch(() => {
      // Best-effort tracking only.
    });
  };

  const onPlay = () => {
    if (playLoggedRef.current) return;
    playLoggedRef.current = true;
    sendEvent("podcast_play");
  };

  const onEnded = () => {
    if (completeLoggedRef.current) return;
    completeLoggedRef.current = true;
    sendEvent("podcast_complete");
  };

  return (
    <div>
      <audio controls className={className} onPlay={onPlay} onEnded={onEnded}>
        <source src={src} />
      </audio>
      <a
        href={src}
        target="_blank"
        rel="noreferrer"
        className="mt-1 inline-flex text-[11px] uppercase tracking-[0.2em] text-[var(--accent)]"
      >
        Open audio
      </a>
    </div>
  );
}
