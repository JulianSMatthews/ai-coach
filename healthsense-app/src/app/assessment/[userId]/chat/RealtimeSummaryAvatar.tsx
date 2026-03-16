"use client";

import { useCallback, useEffect, useRef, useState } from "react";

type RealtimeSessionResponse = {
  session_id?: string;
  speech_token?: string;
  speech_region?: string;
  ssml?: string;
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
  runId: number;
  text: string | null;
  audioUrl: string | null;
  maxSessionSeconds?: number | null;
  maxReplays?: number | null;
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
  runId,
  text,
  audioUrl,
  maxSessionSeconds,
  maxReplays,
}: RealtimeSummaryAvatarProps) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const peerConnectionRef = useRef<RTCPeerConnection | null>(null);
  const synthesizerRef = useRef<unknown>(null);
  const mediaStreamRef = useRef<MediaStream | null>(null);
  const timeoutRef = useRef<number | null>(null);
  const sessionIdRef = useRef<string | null>(null);
  const startedAtRef = useRef<number | null>(null);
  const finalizingRef = useRef(false);

  const [starting, setStarting] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [statusText, setStatusText] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [playsUsed, setPlaysUsed] = useState(0);

  const replayLimit = Math.max(0, Number(maxReplays ?? 1));
  const canStart = Boolean(text) && !starting && !playing && playsUsed <= replayLimit;

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
      if (finalError) {
        setError(finalError);
      }
      try {
        await cleanupMedia();
      } finally {
        if (sessionId) {
          void fetch("/api/assessment/summary-avatar/realtime-complete", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              userId,
              run_id: runId,
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
    [cleanupMedia, runId, userId],
  );

  useEffect(() => {
    return () => {
      void finalizeSession("stopped");
    };
  }, [finalizeSession]);

  const startRealtimeAvatar = useCallback(async () => {
    if (!text || !canStart) return;
    if (typeof window === "undefined" || typeof window.RTCPeerConnection === "undefined") {
      setError("Realtime video is not supported in this browser.");
      return;
    }

    setStarting(true);
    setError(null);
    setStatusText("Connecting your summary video…");

    try {
      const response = await fetch("/api/assessment/summary-avatar/realtime-session", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ userId, runId }),
      });
      const rawText = await response.text().catch(() => "");
      if (!response.ok) {
        throw new Error(parseApiError(rawText, "We couldn't start the summary video right now."));
      }
      const payload = (rawText ? JSON.parse(rawText) : {}) as RealtimeSessionResponse;
      const speechToken = String(payload.speech_token || "").trim();
      const speechRegion = String(payload.speech_region || "").trim();
      const ssml = String(payload.ssml || "").trim();
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
        if (videoRef.current && videoRef.current.srcObject !== stream) {
          videoRef.current.srcObject = stream;
        }
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

      setPlaysUsed((current) => current + 1);
      setStarting(false);
      setPlaying(true);
      setStatusText("Playing your summary video…");
      if (videoRef.current && mediaStreamRef.current) {
        videoRef.current.srcObject = mediaStreamRef.current;
        void videoRef.current.play().catch(() => undefined);
      }

      timeoutRef.current = window.setTimeout(() => {
        void finalizeSession("timeout", "The summary video session timed out.");
      }, sessionMaxSeconds * 1000);

      const speakResult = await synthesizer.speakSsmlAsync(ssml);
      if (speakResult.reason !== SpeechSDK.ResultReason.SynthesizingAudioCompleted) {
        throw new Error(speakResult.errorDetails || "Azure realtime avatar did not complete.");
      }
      setStatusText("Summary video complete.");
      await finalizeSession("completed");
    } catch (errorValue) {
      const message = errorValue instanceof Error ? errorValue.message : String(errorValue);
      setStatusText(null);
      await finalizeSession("failed", message);
    }
  }, [canStart, cleanupMedia, finalizeSession, maxSessionSeconds, runId, text, userId]);

  return (
    <div className="space-y-4">
      <div className="space-y-3">
        <div className="overflow-hidden rounded-2xl border border-[#efe7db] bg-[#f6efe5]">
          <video ref={videoRef} className="w-full" playsInline controls={playing} />
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <button
            type="button"
            onClick={() => void startRealtimeAvatar()}
            disabled={!canStart}
            className="rounded-full border border-[var(--accent)] bg-[var(--accent)] px-4 py-2 text-xs font-semibold uppercase tracking-[0.18em] text-white disabled:cursor-not-allowed disabled:opacity-60"
          >
            {starting ? "Starting video…" : playsUsed > 0 ? "Replay summary video" : "Play summary video"}
          </button>
          {playing ? (
            <button
              type="button"
              onClick={() => void finalizeSession("stopped")}
              className="rounded-full border border-[#d9cdbb] bg-white px-4 py-2 text-xs font-semibold uppercase tracking-[0.18em] text-[#5d5348]"
            >
              Stop video
            </button>
          ) : null}
        </div>
      </div>

      {statusText ? <p className="text-sm text-[#6b6257]">{statusText}</p> : null}
      {error ? <p className="text-sm text-[#8a3e1a]">{error}</p> : null}

      {audioUrl ? (
        <div>
          <p className="text-xs uppercase tracking-[0.18em] text-[#6b6257]">Listen instead</p>
          <audio className="mt-2 w-full" controls preload="metadata">
            <source src={audioUrl} type="audio/mpeg" />
          </audio>
        </div>
      ) : null}

      {text ? <p className="text-sm leading-6 text-[#3c332b]">{text}</p> : null}
    </div>
  );
}
