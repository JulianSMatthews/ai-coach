"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { mergePlayedRanges, playbackProgress } from "@/lib/lessonPlayback";

export default function EducationLessonMedia({ userId, lessonVariantId, src, poster, mode }: {
  userId: string; lessonVariantId: number; src: string; poster?: string; mode: "watch" | "listen";
}) {
  const mediaRef = useRef<HTMLMediaElement | null>(null);
  const ranges = useRef<Array<[number, number]>>([]);
  const pending = useRef<{ watch_pct: number; watched_seconds: number } | null>(null);
  const saving = useRef(false);
  const lastSaved = useRef(-1);
  const lastAttempt = useRef(0);
  const [error, setError] = useState(false);

  async function save() {
    if (saving.current || !pending.current) return;
    saving.current = true;
    const progress = pending.current;
    pending.current = null;
    try {
      const res = await fetch("/api/education-plan/video-progress", {
        method: "POST", headers: { "Content-Type": "application/json" }, keepalive: true,
        body: JSON.stringify({ userId, lesson_variant_id: lessonVariantId, ...progress }),
      });
      if (!res.ok) throw new Error("Progress was not saved");
      const data = await res.json();
      if (data.video_progress_applied !== true) throw new Error("Lesson progress was not applied");
      lastSaved.current = progress.watch_pct;
      setError(false);
    } catch {
      pending.current = pending.current || progress;
      setError(true);
      saving.current = false;
      return;
    }
    saving.current = false;
    if (pending.current) void save();
  }

  function record(force = false, media = mediaRef.current) {
    if (!media || !lessonVariantId) return;
    ranges.current = mergePlayedRanges(ranges.current, media.played);
    const progress = playbackProgress(ranges.current, media.duration);
    if (!progress || progress.watch_pct <= lastSaved.current) return;
    if (force || Date.now() - lastAttempt.current >= 10000) {
      pending.current = progress;
      lastAttempt.current = Date.now();
      void save();
    }
  }

  useEffect(() => {
    const flush = () => record(true);
    const hide = () => { if (document.visibilityState === "hidden") flush(); };
    window.addEventListener("pagehide", flush);
    document.addEventListener("visibilitychange", hide);
    return () => {
      flush();
      window.removeEventListener("pagehide", flush);
      document.removeEventListener("visibilitychange", hide);
    };
    // This component is keyed by user, lesson and media URL in its parent.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const events = {
    onTimeUpdate: () => record(), onPause: () => record(true), onEnded: () => record(true),
  };
  const attach = useCallback((media: HTMLMediaElement | null) => {
    if (!media && mediaRef.current) record(true, mediaRef.current);
    mediaRef.current = media;
    // Lesson identity is fixed by the parent key.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return <>
    {mode === "watch" ? (
      <video ref={attach} className="mt-3 w-full rounded-[24px] bg-black" src={src} controls playsInline poster={poster} {...events} />
    ) : (
      <div className="mt-3 rounded-[24px] bg-[var(--surface-muted)] px-4 py-5">
        <p className="mb-3 text-sm font-semibold text-[var(--text-primary)]">Listen to this lesson</p>
        <audio ref={attach} className="w-full" src={src} controls preload="metadata" {...events} />
      </div>
    )}
    {error ? <p role="status" className="mt-2 text-sm">Playback progress could not be saved. <button type="button" className="underline" onClick={() => void save()}>Retry</button></p> : null}
  </>;
}
