"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Capacitor } from "@capacitor/core";
import type { SpeechRecognizer, SpeechSynthesizer } from "microsoft-cognitiveservices-speech-sdk";

type Credentials = { token: string; region: string; voice: string; locale: string; expires_in: number };
type Status = "idle" | "connecting" | "listening" | "thinking" | "speaking";

declare global {
  interface Window {
    __healthsenseNativeMicrophoneReady?: boolean;
  }
}

/** Alternating spoken turns. The microphone is released before synthesis/playback. */
export function useCheckinVoice(userId: string, exchange: (text: string) => Promise<string>) {
  const [status, setStatus] = useState<Status>("idle");
  const [error, setError] = useState<string | null>(null);
  const [transcript, setTranscript] = useState("");
  const generation = useRef(0);
  const exchangeRef = useRef(exchange);
  useEffect(() => { exchangeRef.current = exchange; }, [exchange]);
  const resources = useRef<{
    stream?: MediaStream;
    recognizer?: SpeechRecognizer;
    synthesizer?: SpeechSynthesizer;
    audio?: AudioContext;
    source?: AudioBufferSourceNode;
    cancel?: () => void;
    requestingMicrophone?: boolean;
  }>({});

  const stop = useCallback(() => {
    generation.current += 1;
    const current = resources.current;
    resources.current = {};
    current.cancel?.();
    current.stream?.getTracks().forEach((track) => track.stop());
    try { current.recognizer?.close(); } catch { /* Already closed. */ }
    try { current.synthesizer?.close(); } catch { /* Already closed. */ }
    try { current.source?.stop(); } catch { /* Already ended. */ }
    if (current.audio && current.audio.state !== "closed") void current.audio.close().catch(() => undefined);
    setStatus("idle");
    setTranscript("");
  }, []);

  useEffect(() => {
    const onVisibility = () => {
      // iOS can temporarily hide the webview while its permission sheet is open.
      // Once that request resolves, the foreground check below still prevents
      // capture if the user actually left the app.
      if (document.hidden && !resources.current.requestingMicrophone) stop();
    };
    document.addEventListener("visibilitychange", onVisibility);
    return () => { document.removeEventListener("visibilitychange", onVisibility); stop(); };
  }, [stop]);

  async function start(command: string) {
    stop();
    const run = generation.current;
    const active = () => generation.current === run;
    setError(null);
    setStatus("connecting");
    const assertActive = () => { if (!active()) throw new Error("Voice paused"); };
    // Ensure pending SDK operations settle when the user pauses or leaves.
    function operation<T>(work: (resolve: (value: T) => void, reject: (error: Error) => void) => void, timeoutMs = 45000): Promise<T> {
      return new Promise<T>((resolve, reject) => {
        const finish = (error?: Error, value?: T) => {
          clearTimeout(timer);
          if (resources.current.cancel === cancel) resources.current.cancel = undefined;
          if (error) reject(error); else resolve(value as T);
        };
        const cancel = () => finish(new Error("Voice paused"));
        const timer = setTimeout(() => finish(new Error("Voice took too long to respond. Please resume to try again.")), timeoutMs);
        resources.current.cancel = cancel;
        work((value) => finish(undefined, value), (error) => finish(error));
      });
    }
    const getMicrophone = async () => {
      resources.current.requestingMicrophone = true;
      let stream: MediaStream;
      try {
        stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
      } finally {
        if (active()) resources.current.requestingMicrophone = false;
      }
      if (!active() || document.hidden) {
        stream.getTracks().forEach((track) => track.stop());
        assertActive();
        throw new Error("Voice paused while the app was in the background. Resume when you’re ready.");
      }
      resources.current.stream = stream;
      return stream;
    };
    try {
      if (Capacitor.isNativePlatform() && Capacitor.getPlatform() === "ios" && window.__healthsenseNativeMicrophoneReady !== true) {
        throw new Error("This installed app needs an update before it can use the microphone. Open CoachSense in Safari for a voice check-in, or use text here.");
      }
      if (!navigator.mediaDevices?.getUserMedia || !window.AudioContext) throw new Error("Voice is not supported here. Please open the app in a supported browser or use text.");
      // Resume audio on the initiating tap so mobile browsers can play replies.
      const audio = new AudioContext();
      resources.current.audio = audio;
      await audio.resume();
      assertActive();
      const permissionStream = await getMicrophone();
      permissionStream.getTracks().forEach((track) => track.stop());
      assertActive();
      resources.current.stream = undefined;
      const sdk = await import("microsoft-cognitiveservices-speech-sdk");
      assertActive();
      let credentials: Credentials | undefined;
      let expiresAt = 0;
      const config = async () => {
        if (!credentials || Date.now() >= expiresAt) {
          const res = await fetch("/api/pillar-checkin", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ userId, action: "voice-session" }),
          });
          const data = await res.json();
          assertActive();
          if (!res.ok) throw new Error(data.error || "Voice is unavailable right now.");
          credentials = data as Credentials;
          expiresAt = Date.now() + Math.max(30, credentials.expires_in - 60) * 1000;
        }
        const settings = sdk.SpeechConfig.fromAuthorizationToken(credentials.token, credentials.region);
        settings.speechRecognitionLanguage = credentials.locale;
        settings.speechSynthesisVoiceName = credentials.voice;
        settings.speechSynthesisOutputFormat = sdk.SpeechSynthesisOutputFormat.Audio24Khz48KBitRateMonoMp3;
        settings.setProperty(sdk.PropertyId.SpeechServiceConnection_InitialSilenceTimeoutMs, "15000");
        return settings;
      };
      // Verify speech access before beginning a check-in turn.
      await config();
      assertActive();
      let next = command;
      while (active()) {
        setStatus("thinking");
        const reply = await exchangeRef.current(next);
        assertActive();
        if (!reply.trim()) throw new Error("There was no coach response. Please resume to try again.");
        setTranscript("");
        setStatus("speaking");
        const speechConfig = await config();
        assertActive();
        const synth = new sdk.SpeechSynthesizer(speechConfig, null);
        resources.current.synthesizer = synth;
        const data = await operation<ArrayBuffer>((resolve, reject) => {
          synth.speakTextAsync(reply, (result) => {
            if (result.reason !== sdk.ResultReason.SynthesizingAudioCompleted) reject(new Error("Your coach’s audio could not be played. Please resume to try again."));
            else resolve(result.audioData);
          }, () => reject(new Error("Your coach’s voice is unavailable. Please resume or use text.")));
        });
        assertActive();
        synth.close();
        resources.current.synthesizer = undefined;
        assertActive();
        const buffer = await audio.decodeAudioData(data.slice(0));
        assertActive();
        // Permission sheets and microphone routing can suspend Web Audio on iOS.
        await operation<void>((resolve, reject) => { audio.resume().then(resolve, reject); });
        assertActive();
        const source = audio.createBufferSource();
        resources.current.source = source;
        source.buffer = buffer;
        source.connect(audio.destination);
        await operation<void>((resolve) => { source.onended = () => resolve(); source.start(); }, Math.max(45000, (buffer.duration + 10) * 1000));
        assertActive();
        source.disconnect();
        resources.current.source = undefined;
        assertActive();
        if (/^(stop|pause|cancel|done|finish|stop listening|that['’]s all)[.!?\s]*$/i.test(next)) { stop(); return; }
        next = "";
        for (let attempt = 0; attempt < 3 && !next; attempt += 1) {
          const recognitionConfig = await config();
          assertActive();
          const stream = await getMicrophone();
          assertActive();
          resources.current.stream = stream;
          const recognizer = new sdk.SpeechRecognizer(recognitionConfig, sdk.AudioConfig.fromStreamInput(stream));
          resources.current.recognizer = recognizer;
          recognizer.recognizing = (_sender, event) => { if (active()) setTranscript(event.result.text); };
          setStatus("listening");
          next = await operation<string>((resolve, reject) => {
            recognizer.recognizeOnceAsync((result) => {
              if (result.reason === sdk.ResultReason.RecognizedSpeech && result.text.trim()) resolve(result.text);
              else if (result.reason === sdk.ResultReason.NoMatch) resolve("");
              else reject(new Error("Speech recognition is unavailable right now. Please resume to reconnect, or use text."));
            }, () => reject(new Error("The microphone could not hear you. Check permission and resume, or use text.")));
          });
          assertActive();
          stream.getTracks().forEach((track) => track.stop());
          recognizer.close();
          resources.current.stream = undefined;
          resources.current.recognizer = undefined;
          if (!next) setTranscript("I’m still listening. Take your time, then speak your answer.");
        }
        if (!next) throw new Error("I didn’t catch that. Resume when you’re ready, or use text.");
        setTranscript(next);
      }
    } catch (err) {
      if (!active()) return;
      stop();
      setError(err instanceof Error && err.name === "NotAllowedError" ? "Microphone access was denied. Allow it in your device settings, or use text." : err instanceof Error ? err.message : "Voice is unavailable. Please try again or use text.");
    }
  }

  return { start, stop, status, error, transcript, active: status !== "idle" };
}
