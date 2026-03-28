"use client";

import { useCallback, useEffect, useRef, useState } from "react";

type RealtimeSessionResponse = {
  session_id?: string;
  speech_token?: string;
  speech_region?: string;
  ssml?: string;
  summary_text?: string;
  audio_url?: string;
  relay?: {
    urls?: string[];
    username?: string;
    password?: string;
  };
  avatar?: {
    character?: string;
    style?: string;
    voice?: string;
    background_color?: string;
  };
  session?: {
    max_session_seconds?: number;
    max_replays?: number;
  };
  error?: string;
};

type RealtimeSummaryAvatarProps = {
  userId: string;
  runId?: number | null;
  text: string | null;
  audioUrl: string | null;
  maxSessionSeconds?: number | null;
  maxReplays?: number | null;
  autoStart?: boolean;
  introMessage?: string | null;
  sessionRequestPath?: string;
  completeRequestPath?: string;
  sessionRequestBody?: Record<string, unknown>;
  completeRequestBody?: Record<string, unknown>;
  playbackStorageKey?: string | null;
  persistPlayback?: boolean;
  showReadAction?: boolean;
  showListenAction?: boolean;
  showStopAction?: boolean;
  onPhaseChange?: (phase: "idle" | "preparing" | "playing" | "completed" | "failed" | "stopped" | "timeout") => void;
};

function parseApiError(text: string, fallback: string) {
  if (!text) return fallback;
  try {
    const parsed = JSON.parse(text) as { error?: string; detail?: string };
    const message = parsed.error || parsed.detail || text;
    return String(message || fallback);
  } catch {
    return text;
  }
}

export default function RealtimeSummaryAvatar({
  userId,
  runId = null,
  text,
  audioUrl,
  maxSessionSeconds,
  autoStart = false,
  introMessage = null,
  sessionRequestPath = "/api/assessment/summary-avatar/realtime-session",
  completeRequestPath = "/api/assessment/summary-avatar/realtime-complete",
  sessionRequestBody,
  completeRequestBody,
  playbackStorageKey = null,
  persistPlayback = true,
  showReadAction = true,
  showListenAction = true,
  showStopAction = true,
  onPhaseChange,
}: RealtimeSummaryAvatarProps) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const peerConnectionRef = useRef<RTCPeerConnection | null>(null);
  const synthesizerRef = useRef<unknown>(null);
  const mediaStreamRef = useRef<MediaStream | null>(null);
  const timeoutRef = useRef<number | null>(null);
  const sessionIdRef = useRef<string | null>(null);
  const startedAtRef = useRef<number | null>(null);
  const finalizingRef = useRef(false);
  const autoStartedRef = useRef(false);
  const playbackStorageKeyRef = useRef<string | null>(
    playbackStorageKey ?? (runId ? `hs:assessment-summary-video:${userId}:${runId}` : null),
  );

  const [starting, setStarting] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [statusText, setStatusText] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [alreadyPlayed, setAlreadyPlayed] = useState(false);
  const [detailMode, setDetailMode] = useState<"read" | "listen" | null>(null);
  const [resolvedText, setResolvedText] = useState<string | null>(text);
  const [resolvedAudioUrl, setResolvedAudioUrl] = useState<string | null>(audioUrl);
  const [phase, setPhase] = useState<"idle" | "preparing" | "playing" | "completed" | "failed" | "stopped" | "timeout">(
    "idle",
  );

  const effectiveText = resolvedText ?? text;
  const effectiveAudioUrl = resolvedAudioUrl ?? audioUrl;
  const canStart = !starting && !playing && !alreadyPlayed;

  useEffect(() => {
    onPhaseChange?.(phase);
  }, [onPhaseChange, phase]);

  const cleanupMedia = useCallback(async () => {
    if (timeoutRef.current) {
      window.clearTimeout(timeoutRef.current);
      timeoutRef.current = null;
    }
    const peerConnection = peerConnectionRef.current;
    peerConnectionRef.current = null;
    if (peerConnection) {
      try {
        peerConnection.ontrack = null;
        peerConnection.onicecandidate = null;
        peerConnection.onicegatheringstatechange = null;
        peerConnection.getSenders().forEach((sender) => {
          try {
            sender.track?.stop();
          } catch {
            // Ignore track stop failures.
          }
        });
        peerConnection.close();
      } catch {
        // Ignore peer cleanup failures.
      }
    }
    const synthesizer = synthesizerRef.current as { close?: () => Promise<void> | void } | null;
    synthesizerRef.current = null;
    if (synthesizer?.close) {
      try {
        await synthesizer.close();
      } catch {
        // Ignore synthesizer cleanup failures.
      }
    }
    const stream = mediaStreamRef.current;
    mediaStreamRef.current = null;
    if (stream) {
      stream.getTracks().forEach((track) => {
        try {
          track.stop();
        } catch {
          // Ignore track cleanup failures.
        }
      });
    }
    if (videoRef.current) {
      videoRef.current.srcObject = null;
    }
  }, []);

  const syncVideoElement = useCallback(() => {
    const videoEl = videoRef.current;
    const stream = mediaStreamRef.current;
    if (!videoEl || !stream) {
      return;
    }
    if (videoEl.srcObject !== stream) {
      videoEl.srcObject = stream;
    }
    void videoEl.play().catch(() => undefined);
  }, []);

  const finalizeSession = useCallback(
    async (finalStatus: "completed" | "failed" | "stopped" | "timeout", finalError?: string | null) => {
      if (finalizingRef.current) return;
      finalizingRef.current = true;
      const startedAt = startedAtRef.current;
      const sessionId = sessionIdRef.current;
      const durationMs = startedAt ? Math.max(0, Date.now() - startedAt) : 0;
      startedAtRef.current = null;
      setPlaying(false);
      setStarting(false);
      setPhase(finalStatus);
      if (finalError) {
        setError(finalError);
      }
      try {
        await cleanupMedia();
      } finally {
        if (sessionId) {
          void fetch(completeRequestPath, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              ...(completeRequestBody ?? {
                userId,
                run_id: runId,
              }),
              session_id: sessionId,
              duration_ms: durationMs,
              status: finalStatus,
              error: finalError || undefined,
            }),
          }).catch(() => undefined);
        }
        sessionIdRef.current = null;
        finalizingRef.current = false;
      }
    },
    [cleanupMedia, completeRequestBody, completeRequestPath, runId, userId],
  );

  useEffect(() => {
    return () => {
      void finalizeSession("stopped");
    };
  }, [finalizeSession]);

  const startRealtimeAvatar = useCallback(async () => {
    if (!canStart) return;
    if (typeof window === "undefined" || typeof window.RTCPeerConnection === "undefined") {
      setError("Realtime video is not supported in this browser.");
      setPhase("failed");
      return;
    }

    setStarting(true);
    setError(null);
    setPhase("preparing");
      setStatusText(introMessage ? introMessage : null);

    try {
      const response = await fetch(sessionRequestPath, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(
          sessionRequestBody ?? {
            userId,
            runId,
          },
        ),
      });
      const rawText = await response.text().catch(() => "");
      if (!response.ok) {
        throw new Error(parseApiError(rawText, "We couldn't start the summary video right now."));
      }
      const payload = (rawText ? JSON.parse(rawText) : {}) as RealtimeSessionResponse;
      const speechToken = String(payload.speech_token || "").trim();
      const speechRegion = String(payload.speech_region || "").trim();
      const ssml = String(payload.ssml || "").trim();
      const nextSummaryText = String(payload.summary_text || "").trim();
      const nextAudioUrl = String(payload.audio_url || "").trim();
      const relayUrls = Array.isArray(payload.relay?.urls)
        ? payload.relay?.urls.filter((item): item is string => typeof item === "string" && Boolean(item.trim()))
        : [];
      const relayUsername = String(payload.relay?.username || "").trim();
      const relayPassword = String(payload.relay?.password || "").trim();
      const character = String(payload.avatar?.character || "").trim();
      const style = String(payload.avatar?.style || "").trim();
      const backgroundColor = String(payload.avatar?.background_color || "").trim();
      const sessionId = String(payload.session_id || "").trim();
      const sessionMaxSeconds = Math.max(
        15,
        Number(payload.session?.max_session_seconds || maxSessionSeconds || 70),
      );
      if (nextSummaryText) {
        setResolvedText(nextSummaryText);
      }
      if (nextAudioUrl) {
        setResolvedAudioUrl(nextAudioUrl);
      }

      if (!speechToken || !speechRegion || !ssml || !relayUrls.length || !relayUsername || !relayPassword) {
        throw new Error("Realtime summary video returned incomplete Azure session details.");
      }
      if (!character || !style) {
        throw new Error("Realtime summary video is missing avatar settings.");
      }

      const SpeechSDK = await import("microsoft-cognitiveservices-speech-sdk");
      const speechConfig = SpeechSDK.SpeechConfig.fromAuthorizationToken(speechToken, speechRegion);
      const videoFormat = new SpeechSDK.AvatarVideoFormat();
      const avatarConfig = new SpeechSDK.AvatarConfig(character, style, videoFormat);
      if (backgroundColor) {
        avatarConfig.backgroundColor = backgroundColor;
      }

      const peerConnection = new RTCPeerConnection({
        iceServers: [
          {
            urls: relayUrls,
            username: relayUsername,
            credential: relayPassword,
          },
        ],
      });
      const mediaStream = new MediaStream();
      mediaStreamRef.current = mediaStream;

      peerConnection.addTransceiver("video", { direction: "sendrecv" });
      peerConnection.addTransceiver("audio", { direction: "sendrecv" });
      peerConnection.ontrack = (event) => {
        const stream = mediaStreamRef.current;
        if (!stream) return;
        if (!stream.getTracks().some((track) => track.id === event.track.id)) {
          stream.addTrack(event.track);
        }
        syncVideoElement();
      };

      peerConnectionRef.current = peerConnection;
      const synthesizer = new SpeechSDK.AvatarSynthesizer(speechConfig, avatarConfig);
      synthesizerRef.current = synthesizer;
      sessionIdRef.current = sessionId;
      startedAtRef.current = Date.now();

      const startResult = await synthesizer.startAvatarAsync(peerConnection);
      if (startResult.reason !== SpeechSDK.ResultReason.SynthesizingAudioCompleted) {
        throw new Error(startResult.errorDetails || "Azure realtime avatar connection failed.");
      }

      if (persistPlayback && typeof window !== "undefined" && playbackStorageKeyRef.current) {
        try {
          window.localStorage.setItem(playbackStorageKeyRef.current, "1");
        } catch {
          // Ignore local storage failures and continue playback.
        }
      }
      setAlreadyPlayed(true);
      setStarting(false);
      setPlaying(true);
      setPhase("playing");
      setStatusText(null);
      syncVideoElement();

      timeoutRef.current = window.setTimeout(() => {
        void finalizeSession("timeout", "The summary video session timed out.");
      }, sessionMaxSeconds * 1000);

      const speakResult = await synthesizer.speakSsmlAsync(ssml);
      if (speakResult.reason !== SpeechSDK.ResultReason.SynthesizingAudioCompleted) {
        throw new Error(speakResult.errorDetails || "Azure realtime avatar did not complete.");
      }
      setStatusText(null);
      await finalizeSession("completed");
    } catch (errorValue) {
      const message = errorValue instanceof Error ? errorValue.message : String(errorValue);
      setStatusText(null);
      await finalizeSession("failed", message);
    }
  }, [
    canStart,
    finalizeSession,
    introMessage,
    maxSessionSeconds,
    persistPlayback,
    runId,
    sessionRequestBody,
    sessionRequestPath,
    syncVideoElement,
    userId,
  ]);

  useEffect(() => {
    if (!autoStart || autoStartedRef.current || !canStart) return;
    autoStartedRef.current = true;
    void startRealtimeAvatar();
  }, [autoStart, canStart, startRealtimeAvatar]);

  useEffect(() => {
    playbackStorageKeyRef.current = playbackStorageKey ?? (runId ? `hs:assessment-summary-video:${userId}:${runId}` : null);
    let played = false;
    if (persistPlayback && playbackStorageKeyRef.current && typeof window !== "undefined") {
      try {
        played = window.localStorage.getItem(playbackStorageKeyRef.current) === "1";
      } catch {
        played = false;
      }
    }
    autoStartedRef.current = false;
    setPhase("idle");
    setStatusText(null);
    setError(null);
    setPlaying(false);
    setStarting(false);
    setAlreadyPlayed(played);
    setDetailMode(null);
    setResolvedText(text);
    setResolvedAudioUrl(audioUrl);
  }, [audioUrl, persistPlayback, playbackStorageKey, runId, text, userId]);

  const showVideoSurface = playing;
  const showSummaryActions =
    phase !== "preparing" &&
    ((showReadAction && Boolean(effectiveText)) || (showListenAction && Boolean(effectiveAudioUrl)));

  useEffect(() => {
    if (!showVideoSurface) return;
    syncVideoElement();
  }, [showVideoSurface, syncVideoElement]);

  return (
    <div className="space-y-3">
      <div className="space-y-2">
        {showVideoSurface ? (
          <div className="overflow-hidden rounded-2xl border border-[#efe7db] bg-[#f6efe5]">
            <video ref={videoRef} className="w-full" playsInline />
          </div>
        ) : null}
        <div className="flex flex-wrap items-center gap-2">
          {showStopAction && playing ? (
            <button
              type="button"
              onClick={() => void finalizeSession("stopped")}
              className="rounded-full border border-[#d9cdbb] bg-white px-4 py-2 text-xs font-semibold uppercase tracking-[0.18em] text-[#5d5348]"
            >
              Stop video
            </button>
          ) : null}
          {showSummaryActions && showReadAction && effectiveText ? (
            <button
              type="button"
              onClick={() => setDetailMode((current) => (current === "read" ? null : "read"))}
              className="rounded-full border border-[#d9cdbb] bg-white px-4 py-2 text-xs font-semibold uppercase tracking-[0.18em] text-[#5d5348]"
            >
              {detailMode === "read" ? "Hide read" : "Read"}
            </button>
          ) : null}
          {showSummaryActions && showListenAction && effectiveAudioUrl ? (
            <button
              type="button"
              onClick={() => setDetailMode((current) => (current === "listen" ? null : "listen"))}
              className="rounded-full border border-[#d9cdbb] bg-white px-4 py-2 text-xs font-semibold uppercase tracking-[0.18em] text-[#5d5348]"
            >
              {detailMode === "listen" ? "Hide listen" : "Listen"}
            </button>
          ) : null}
        </div>
      </div>

      {statusText ? <p className="text-sm text-[#6b6257]">{statusText}</p> : null}
      {error ? <p className="text-sm text-[#8a3e1a]">{error}</p> : null}

      {showSummaryActions ? (
        <div className="space-y-2">
          {detailMode === "listen" && effectiveAudioUrl ? (
            <audio className="w-full" controls preload="metadata">
              <source src={effectiveAudioUrl} type="audio/mpeg" />
            </audio>
          ) : null}

          {detailMode === "read" && effectiveText ? (
            <div className="rounded-2xl border border-[#efe7db] bg-[#fffaf3] px-4 py-3">
              <p className="text-sm leading-6 text-[#3c332b]">{effectiveText}</p>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
