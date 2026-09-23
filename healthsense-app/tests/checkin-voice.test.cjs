// Run with: node --test tests/checkin-voice.test.cjs
// Exercise the voice controller with simulated browser audio and Speech SDK.
const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const ts = require("typescript");

function harness({ utterances = ["Save.", "Pause."], permissionError, recognitionReason = 1, getMedia, nativeIOS = false, microphoneReady } = {}) {
  const states = [], effects = [], events = [], streams = [];
  let microphoneLive = false;
  const react = {
    useState(initial) { const slot = states.length; states.push(initial); return [initial, (value) => { states[slot] = value; events.push(["state", slot, value]); }]; },
    useRef: (current) => ({ current }),
    useCallback: (fn) => fn,
    useEffect: (fn) => effects.push(fn),
  };
  const media = async () => {
    if (permissionError) throw permissionError;
    microphoneLive = true;
    const stream = { stopped: false, getTracks() { return [{ stop() { stream.stopped = true; microphoneLive = false; events.push(["mic-stop"]); } }]; } };
    streams.push(stream);
    return stream;
  };
  class AudioContext {
    state = "running";
    resume() { return Promise.resolve(); }
    close() { this.state = "closed"; events.push(["audio-close"]); return Promise.resolve(); }
    decodeAudioData() { return Promise.resolve({ duration: 0.01 }); }
    createBufferSource() {
      return {
        connect() {}, disconnect() {}, stop() { events.push(["playback-stop"]); },
        start() { assert.equal(microphoneLive, false, "microphone must be off while coach speaks"); events.push(["play"]); queueMicrotask(() => this.onended()); },
      };
    }
  }
  const sdk = {
    SpeechConfig: { fromAuthorizationToken: () => ({}) },
    SpeechSynthesisOutputFormat: { Audio24Khz48KBitRateMonoMp3: 1 },
    ResultReason: { RecognizedSpeech: 1, SynthesizingAudioCompleted: 2 },
    AudioConfig: { fromStreamInput: (stream) => stream },
    SpeechSynthesizer: class {
      speakTextAsync(text, success) { events.push(["say", text]); queueMicrotask(() => success({ reason: 2, audioData: new ArrayBuffer(1) })); }
      close() { events.push(["synth-close"]); }
    },
    SpeechRecognizer: class {
      recognizeOnceAsync(success) { const text = utterances.shift(); events.push(["hear", text]); queueMicrotask(() => success({ reason: recognitionReason, text: text || "" })); }
      close() { events.push(["recognizer-close"]); }
    },
  };
  const js = ts.transpileModule(fs.readFileSync(require.resolve("../src/lib/useCheckinVoice.ts"), "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
  }).outputText;
  const context = {
    exports: {}, require: (name) => name === "react" ? react : name === "@capacitor/core" ? {
      Capacitor: { isNativePlatform: () => nativeIOS, getPlatform: () => nativeIOS ? "ios" : "web" },
    } : sdk,
    navigator: { mediaDevices: { getUserMedia: getMedia || media } },
    window: { AudioContext, __healthsenseNativeMicrophoneReady: microphoneReady }, AudioContext,
    document: { hidden: false, addEventListener() {}, removeEventListener() {} },
    fetch: async () => ({ ok: true, json: async () => ({ token: "test", region: "test", voice: "test", locale: "en-GB", expires_in: 540 }) }),
    setTimeout, clearTimeout, console, Date, Error, Promise,
  };
  vm.runInNewContext(js, context);
  const exchanges = [];
  const voice = context.exports.useCheckinVoice("1", async (text) => { exchanges.push(text); return `Coach reply to ${text}`; });
  const cleanups = effects.map((effect) => effect());
  return { voice, states, events, streams, exchanges, cleanup: () => cleanups.forEach((fn) => fn?.()) };
}

test("speaks, listens, submits spoken confirmation, then pauses without an extra turn", async () => {
  const h = harness();
  await h.voice.start("start");
  assert.deepEqual(h.exchanges, ["start", "Save.", "Pause."]);
  assert.equal(h.events.filter((event) => event[0] === "play").length, 3);
  assert.ok(h.streams.every((stream) => stream.stopped));
  assert.equal(h.states[0], "idle");
  assert.equal(h.states[1], null);
  h.cleanup();
});

test("older iOS shells cannot access the microphone or begin an activity", async () => {
  for (const microphoneReady of [undefined, false]) {
    const h = harness({ nativeIOS: true, microphoneReady });
    await h.voice.start("start");
    assert.equal(h.streams.length, 0);
    assert.equal(h.exchanges.length, 0);
    assert.match(h.states[1], /installed app needs an update/);
    assert.equal(h.states[0], "idle");
    h.cleanup();
  }
});

test("iOS builds declaring microphone capability can complete spoken turns", async () => {
  const h = harness({ nativeIOS: true, microphoneReady: true });
  await h.voice.start("start");
  assert.deepEqual(h.exchanges, ["start", "Save.", "Pause."]);
  assert.equal(h.states[1], null);
  h.cleanup();
});

test("permission denied stops before sending any check-in message", async () => {
  const err = new Error("denied"); err.name = "NotAllowedError";
  const h = harness({ permissionError: err });
  await h.voice.start("start");
  assert.equal(h.exchanges.length, 0);
  assert.match(h.states[1], /Microphone access was denied/);
  assert.equal(h.states[0], "idle");
  h.cleanup();
});

test("silence releases microphone and offers retry without submitting an empty answer", async () => {
  const h = harness({ recognitionReason: 0 });
  await h.voice.start("resume");
  assert.deepEqual(h.exchanges, ["resume"]);
  assert.ok(h.streams.every((stream) => stream.stopped));
  assert.match(h.states[1], /didn’t catch/);
  h.cleanup();
});

test("pausing while permission is pending stops the late stream without starting a conversation", async () => {
  let grant;
  let stopped = false;
  const h = harness({ getMedia: () => new Promise((resolve) => { grant = resolve; }) });
  const running = h.voice.start("start");
  await new Promise(setImmediate);
  h.voice.stop();
  grant({ getTracks: () => [{ stop: () => { stopped = true; } }] });
  await running;
  assert.equal(stopped, true);
  assert.equal(h.exchanges.length, 0);
  assert.equal(h.states[1], null);
  h.cleanup();
});
