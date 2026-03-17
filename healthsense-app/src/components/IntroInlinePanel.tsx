"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

type IntroPayload = {
  enabled?: boolean;
  content_id?: number | null;
  body?: string | null;
  podcast_url?: string | null;
  app_intro_avatar?: {
    url?: string | null;
    title?: string | null;
    poster_url?: string | null;
  } | null;
};

type IntroInlinePanelProps = {
  userId: string | number;
  intro?: IntroPayload | null;
  introCompleted?: boolean;
};

export default function IntroInlinePanel({ userId, intro, introCompleted }: IntroInlinePanelProps) {
  const [readOpen, setReadOpen] = useState(false);
  const [audioRetryToken, setAudioRetryToken] = useState(0);
  const [audioDurationSec, setAudioDurationSec] = useState<number | null>(null);
  const presentedRef = useRef(false);
  const listenedRef = useRef(false);
  const readRef = useRef(false);
  const retriedPodcastUrlRef = useRef("");

  const enabled = Boolean(intro?.enabled);
  const completed = Boolean(introCompleted);
  const podcastUrl = String(intro?.podcast_url || "").trim().replace(/^['"]+|['"]+$/g, "");
  const appIntroAvatarUrl = String(intro?.app_intro_avatar?.url || "").trim().replace(/^['"]+|['"]+$/g, "");
  const appIntroAvatarTitle = String(intro?.app_intro_avatar?.title || "").trim();
  const appIntroAvatarPosterUrl = String(intro?.app_intro_avatar?.poster_url || "").trim().replace(/^['"]+|['"]+$/g, "");
  const hasPodcast = Boolean(podcastUrl);
  const hasAvatar = Boolean(appIntroAvatarUrl);
  const hasBody = Boolean((intro?.body || "").trim());
  const show = enabled && !completed && (hasAvatar || hasPodcast || hasBody);
  const audioSrc = useMemo(() => {
    if (!podcastUrl) return "";
    if (!audioRetryToken) return podcastUrl;
    const sep = podcastUrl.includes("?") ? "&" : "?";
    return `${podcastUrl}${sep}r=${audioRetryToken}`;
  }, [podcastUrl, audioRetryToken]);

  const formattedDuration = useMemo(() => {
    if (audioDurationSec == null || !Number.isFinite(audioDurationSec) || audioDurationSec <= 0) return null;
    const total = Math.round(audioDurationSec);
    const mins = Math.floor(total / 60);
    const secs = total % 60;
    return `${mins}m ${secs}s`;
  }, [audioDurationSec]);

  const sendEvent = useCallback((eventType: "intro_presented" | "intro_listened" | "intro_read") => {
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
  }, [intro?.content_id, userId]);

  useEffect(() => {
    if (!show || presentedRef.current) return;
    presentedRef.current = true;
    sendEvent("intro_presented");
  }, [sendEvent, show]);

  if (!show) return null;

  return (
    <div className="mt-3 rounded-xl border border-[#efe7db] bg-white p-3">
      {hasAvatar ? (
        <div className={hasPodcast ? "mb-3" : ""}>
          <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">
            {appIntroAvatarTitle || "Intro video"}
          </p>
          <video
            key={appIntroAvatarUrl}
            controls
            preload="metadata"
            playsInline
            poster={appIntroAvatarPosterUrl || undefined}
            className="mt-2 w-full rounded-2xl border border-[#efe7db]"
          >
            <source src={appIntroAvatarUrl} />
          </video>
        </div>
      ) : null}
      {hasPodcast ? (
        <div>
          <div className="flex items-center justify-between gap-2">
            <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Intro podcast</p>
            <p className="text-xs text-[#8a8176]">{formattedDuration || "Duration loading…"}</p>
          </div>
          <audio
            key={audioSrc}
            controls
            preload="metadata"
            className="mt-2 w-full"
            src={audioSrc}
            onLoadedMetadata={(e) => {
              const d = e.currentTarget.duration;
              if (Number.isFinite(d) && d > 0) setAudioDurationSec(d);
            }}
            onDurationChange={(e) => {
              const d = e.currentTarget.duration;
              if (Number.isFinite(d) && d > 0) setAudioDurationSec(d);
            }}
            onError={() => {
              if (podcastUrl && retriedPodcastUrlRef.current !== podcastUrl) {
                retriedPodcastUrlRef.current = podcastUrl;
                setAudioRetryToken(Date.now());
              }
            }}
            onEnded={() => {
              if (listenedRef.current) return;
              listenedRef.current = true;
              sendEvent("intro_listened");
            }}
          />
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
          <div className="mt-2 whitespace-pre-wrap rounded-xl border border-[#efe7db] bg-[#fffaf0] p-3 text-sm text-[#2f2a21]">
            {intro?.body}
          </div>
        </details>
      ) : null}
    </div>
  );
}
