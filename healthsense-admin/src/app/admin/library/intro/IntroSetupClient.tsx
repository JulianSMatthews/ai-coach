"use client";

import { useActionState, useEffect, useMemo, useState } from "react";
import type { ContentPromptTemplateSummary, IntroLibrarySettings } from "@/lib/api";
import {
  generateIntroAvatarAction,
  generateIntroDraftAction,
  refreshIntroAvatarAction,
  saveIntroSettingsAction,
  type IntroAvatarState,
  type IntroGenerationState,
  type IntroSaveState,
} from "./actions";

type IntroSetupClientProps = {
  intro: IntroLibrarySettings;
  templates: ContentPromptTemplateSummary[];
};

const emptyGenerationState: IntroGenerationState = { ok: false, error: null };
const emptySaveState: IntroSaveState = { ok: false, error: null };
const emptyAvatarState: IntroAvatarState = { ok: false, error: null };

const voiceOptions = [
  { value: "", label: "Default" },
  { value: "alloy", label: "Alloy" },
  { value: "breeze", label: "Breeze" },
  { value: "echo", label: "Echo" },
  { value: "verse", label: "Verse" },
  { value: "shimmer", label: "Shimmer" },
  { value: "onyx", label: "Onyx" },
  { value: "coral", label: "Coral" },
  { value: "amber", label: "Amber" },
];

const modelOptions = [
  "",
  "gpt-5.2-pro",
  "gpt-5.2",
  "gpt-5.1",
  "gpt-5-mini",
  "gpt-5-nano",
  "gpt-4.1",
  "gpt-4.1-mini",
  "gpt-4.1-nano",
  "gpt-4o",
  "gpt-4o-mini",
  "o3",
  "o4-mini",
  "gpt-3.5-turbo",
];

export default function IntroSetupClient({ intro, templates }: IntroSetupClientProps) {
  const [generationState, generationAction, generating] = useActionState(generateIntroDraftAction, emptyGenerationState);
  const [saveState, saveAction, saving] = useActionState(saveIntroSettingsAction, emptySaveState);
  const [avatarGenerationState, avatarGenerationAction, generatingAvatar] = useActionState(
    generateIntroAvatarAction,
    emptyAvatarState,
  );
  const [avatarRefreshState, avatarRefreshAction, refreshingAvatar] = useActionState(
    refreshIntroAvatarAction,
    emptyAvatarState,
  );

  const [active, setActive] = useState(Boolean(intro.active));
  const [title, setTitle] = useState(intro.title || "Welcome to HealthSense");
  const [welcomeTemplate, setWelcomeTemplate] = useState(
    intro.welcome_message_template ||
      "{first_name}, Welcome to HealthSense please listen to our introductory podcast to get started on your journey.",
  );
  const [body, setBody] = useState(intro.body || "");
  const [podcastUrl, setPodcastUrl] = useState(intro.podcast_url || "");
  const [podcastVoice, setPodcastVoice] = useState(intro.podcast_voice || "");
  const [assessmentIntroAvatarUrl, setAssessmentIntroAvatarUrl] = useState(
    intro.assessment_intro_avatar?.url || "",
  );
  const [assessmentIntroAvatarTitle, setAssessmentIntroAvatarTitle] = useState(
    intro.assessment_intro_avatar?.title || "Assessment introduction",
  );
  const [assessmentIntroAvatarScript, setAssessmentIntroAvatarScript] = useState(
    intro.assessment_intro_avatar?.script || "",
  );
  const [assessmentIntroAvatarPosterUrl, setAssessmentIntroAvatarPosterUrl] = useState(
    intro.assessment_intro_avatar?.poster_url || "",
  );
  const [assessmentIntroAvatarCharacter, setAssessmentIntroAvatarCharacter] = useState(
    intro.assessment_intro_avatar?.character || "lisa",
  );
  const [assessmentIntroAvatarStyle, setAssessmentIntroAvatarStyle] = useState(
    intro.assessment_intro_avatar?.style || "graceful-sitting",
  );
  const [assessmentIntroAvatarVoice, setAssessmentIntroAvatarVoice] = useState(
    intro.assessment_intro_avatar?.voice || "en-GB-SoniaNeural",
  );
  const [assessmentIntroAvatarStatus, setAssessmentIntroAvatarStatus] = useState(
    intro.assessment_intro_avatar?.status || "",
  );
  const [assessmentIntroAvatarJobId, setAssessmentIntroAvatarJobId] = useState(
    intro.assessment_intro_avatar?.job_id || "",
  );
  const [assessmentIntroAvatarError, setAssessmentIntroAvatarError] = useState(
    intro.assessment_intro_avatar?.error || "",
  );
  const [assessmentIntroAvatarGeneratedAt, setAssessmentIntroAvatarGeneratedAt] = useState(
    intro.assessment_intro_avatar?.generated_at || "",
  );
  const [assessmentIntroAvatarSummaryUrl, setAssessmentIntroAvatarSummaryUrl] = useState(
    intro.assessment_intro_avatar?.summary_url || "",
  );

  const generatedResult = generationState.result || {};
  const generatedPayload = useMemo(
    () => ((generatedResult.result || {}) as Record<string, unknown>),
    [generatedResult],
  );
  const generatedLlm = useMemo(
    () => ((generatedPayload.llm || {}) as Record<string, unknown>),
    [generatedPayload],
  );
  const generatedText = String(generatedLlm.content || "").trim();
  const generatedPodcastUrl = String(generatedResult.podcast_url || "").trim();
  const generatedPodcastVoice = String(generatedResult.podcast_voice || "").trim();

  useEffect(() => {
    if (!generationState.ok) return;
    if (generatedText) setBody(generatedText);
    if (generatedPodcastUrl) setPodcastUrl(generatedPodcastUrl);
    if (generatedPodcastVoice) setPodcastVoice(generatedPodcastVoice);
  }, [generationState.ok, generatedText, generatedPodcastUrl, generatedPodcastVoice]);

  useEffect(() => {
    const result = avatarGenerationState.result || avatarRefreshState.result;
    const avatar =
      result && typeof result.assessment_intro_avatar === "object" && result.assessment_intro_avatar
        ? (result.assessment_intro_avatar as Record<string, unknown>)
        : null;
    if (!avatar) return;
    setAssessmentIntroAvatarUrl(String(avatar.url || "").trim());
    setAssessmentIntroAvatarTitle(String(avatar.title || "").trim() || "Assessment introduction");
    setAssessmentIntroAvatarScript(String(avatar.script || "").trim());
    setAssessmentIntroAvatarPosterUrl(String(avatar.poster_url || "").trim());
    setAssessmentIntroAvatarCharacter(String(avatar.character || "").trim() || "lisa");
    setAssessmentIntroAvatarStyle(String(avatar.style || "").trim() || "graceful-sitting");
    setAssessmentIntroAvatarVoice(String(avatar.voice || "").trim() || "en-GB-SoniaNeural");
    setAssessmentIntroAvatarStatus(String(avatar.status || "").trim());
    setAssessmentIntroAvatarJobId(String(avatar.job_id || "").trim());
    setAssessmentIntroAvatarError(String(avatar.error || "").trim());
    setAssessmentIntroAvatarGeneratedAt(String(avatar.generated_at || "").trim());
    setAssessmentIntroAvatarSummaryUrl(String(avatar.summary_url || "").trim());
  }, [avatarGenerationState.result, avatarRefreshState.result]);

  return (
    <div className="space-y-6">
      <section className="rounded-2xl border border-[#efe7db] bg-[#fdfaf4] p-4">
        <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Generate intro draft</p>
        <p className="mt-2 text-sm text-[#6b6257]">
          Uses the same template generation flow as library content, including optional podcast audio.
        </p>
        <form action={generationAction} className="mt-4 grid gap-4 md:grid-cols-2">
          <div>
            <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Content template</label>
            <select
              name="template_id"
              className="mt-2 w-full rounded-xl border border-[#efe7db] bg-white px-3 py-2 text-sm"
              defaultValue={templates[0]?.id ?? ""}
            >
              <option value="">Select template</option>
              {templates.map((tpl) => (
                <option key={tpl.id} value={tpl.id}>
                  {tpl.template_key}
                  {tpl.label ? ` · ${tpl.label}` : ""}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Provider</label>
            <select
              name="provider"
              defaultValue="openai"
              className="mt-2 w-full rounded-xl border border-[#efe7db] bg-white px-3 py-2 text-sm"
            >
              <option value="openai">OpenAI</option>
              <option value="anthropic">Anthropic</option>
              <option value="google">Google</option>
            </select>
          </div>
          <div>
            <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">LLM model (optional)</label>
            <select name="model_override" className="mt-2 w-full rounded-xl border border-[#efe7db] bg-white px-3 py-2 text-sm">
              {modelOptions.map((model) => (
                <option key={model || "default"} value={model}>
                  {model || "Default"}
                </option>
              ))}
            </select>
          </div>
          <label className="flex items-center gap-2 text-sm text-[#6b6257]">
            <input type="checkbox" name="run_llm" defaultChecked />
            Run LLM (generate text)
          </label>
          <label className="flex items-center gap-2 text-sm text-[#6b6257]">
            <input type="checkbox" name="generate_podcast" defaultChecked />
            Generate podcast audio
          </label>
          <div>
            <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Podcast voice</label>
            <select
              name="podcast_voice"
              defaultValue={podcastVoice}
              className="mt-2 w-full rounded-xl border border-[#efe7db] bg-white px-3 py-2 text-sm"
            >
              {voiceOptions.map((voice) => (
                <option key={voice.value || "default"} value={voice.value}>
                  {voice.label}
                </option>
              ))}
            </select>
          </div>
          <button
            type="submit"
            disabled={generating}
            className="w-fit rounded-full border border-[var(--accent)] bg-[var(--accent)] px-3 py-1.5 text-[10px] uppercase tracking-[0.12em] text-white disabled:cursor-not-allowed disabled:opacity-60"
          >
            {generating ? "Generating…" : "Generate draft"}
          </button>
        </form>
        {generationState.error ? <p className="mt-3 text-sm text-red-600">{generationState.error}</p> : null}
        {generatedText ? (
          <p className="mt-3 text-xs text-[#6b6257]">Generated text loaded into the read content field below.</p>
        ) : null}
      </section>

      <section className="rounded-2xl border border-[#efe7db] bg-white p-4">
        <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Intro settings</p>
        <form action={saveAction} className="mt-4 space-y-4">
          <label className="flex items-center gap-2 text-sm text-[#3c332b]">
            <input type="checkbox" name="active" checked={active} onChange={(e) => setActive(e.target.checked)} />
            Intro flow active
          </label>
          <div>
            <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Title</label>
            <input
              name="title"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              className="mt-2 w-full rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
            />
          </div>
          <div>
            <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Welcome message template</label>
            <input
              name="welcome_message_template"
              value={welcomeTemplate}
              onChange={(e) => setWelcomeTemplate(e.target.value)}
              className="mt-2 w-full rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
            />
            <p className="mt-1 text-xs text-[#8a8176]">Supports {"{first_name}"} and {"{display_name}"}.</p>
          </div>
          <div>
            <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Read content</label>
            <textarea
              name="body"
              rows={8}
              value={body}
              onChange={(e) => setBody(e.target.value)}
              className="mt-2 w-full rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
            />
          </div>
          <div className="grid gap-3 md:grid-cols-2">
            <div>
              <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Podcast URL</label>
              <input
                name="podcast_url"
                value={podcastUrl}
                onChange={(e) => setPodcastUrl(e.target.value)}
                className="mt-2 w-full rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
              />
            </div>
            <div>
              <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Podcast voice</label>
              <select
                name="podcast_voice"
                value={podcastVoice}
                onChange={(e) => setPodcastVoice(e.target.value)}
                className="mt-2 w-full rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
              >
                {voiceOptions.map((voice) => (
                  <option key={voice.value || "default"} value={voice.value}>
                    {voice.label}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <div className="space-y-4 rounded-2xl border border-[#efe7db] bg-[#fdfaf4] p-4">
            <div>
              <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Assessment intro avatar</p>
              <p className="mt-1 text-sm text-[#6b6257]">
                Managed video for the lead assessment landing page. The frontend on/off switch still controls whether it renders.
              </p>
            </div>
            <div className="grid gap-3 md:grid-cols-2">
              <div>
                <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Video URL</label>
                <input
                  name="assessment_intro_avatar_url"
                  value={assessmentIntroAvatarUrl}
                  onChange={(e) => setAssessmentIntroAvatarUrl(e.target.value)}
                  className="mt-2 w-full rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
                />
              </div>
              <div>
                <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Label</label>
                <input
                  name="assessment_intro_avatar_title"
                  value={assessmentIntroAvatarTitle}
                  onChange={(e) => setAssessmentIntroAvatarTitle(e.target.value)}
                  className="mt-2 w-full rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
                />
              </div>
              <div>
                <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Poster URL</label>
                <input
                  name="assessment_intro_avatar_poster_url"
                  value={assessmentIntroAvatarPosterUrl}
                  onChange={(e) => setAssessmentIntroAvatarPosterUrl(e.target.value)}
                  className="mt-2 w-full rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
                />
              </div>
              <div>
                <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Character</label>
                <input
                  name="assessment_intro_avatar_character"
                  value={assessmentIntroAvatarCharacter}
                  onChange={(e) => setAssessmentIntroAvatarCharacter(e.target.value)}
                  className="mt-2 w-full rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
                />
              </div>
              <div>
                <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Style</label>
                <input
                  name="assessment_intro_avatar_style"
                  value={assessmentIntroAvatarStyle}
                  onChange={(e) => setAssessmentIntroAvatarStyle(e.target.value)}
                  className="mt-2 w-full rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
                />
              </div>
              <div>
                <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Voice</label>
                <input
                  name="assessment_intro_avatar_voice"
                  value={assessmentIntroAvatarVoice}
                  onChange={(e) => setAssessmentIntroAvatarVoice(e.target.value)}
                  className="mt-2 w-full rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
                />
              </div>
            </div>
            <div>
              <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Avatar script</label>
              <textarea
                name="assessment_intro_avatar_script"
                rows={8}
                value={assessmentIntroAvatarScript}
                onChange={(e) => setAssessmentIntroAvatarScript(e.target.value)}
                className="mt-2 w-full rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
              />
              <p className="mt-1 text-xs text-[#8a8176]">
                Store the transcript used to create the intro video so it can be edited without changing code.
              </p>
            </div>
            <div className="rounded-xl border border-[#efe7db] bg-white p-3 text-sm text-[#6b6257]">
              <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Azure avatar status</p>
              <p className="mt-2">Status: {assessmentIntroAvatarStatus || "not generated"}</p>
              {assessmentIntroAvatarJobId ? <p className="mt-1 break-all">Job ID: {assessmentIntroAvatarJobId}</p> : null}
              {assessmentIntroAvatarGeneratedAt ? <p className="mt-1">Generated: {assessmentIntroAvatarGeneratedAt}</p> : null}
              {assessmentIntroAvatarSummaryUrl ? (
                <a
                  href={assessmentIntroAvatarSummaryUrl}
                  target="_blank"
                  rel="noreferrer"
                  className="mt-2 inline-flex text-[11px] uppercase tracking-[0.2em] text-[var(--accent)]"
                >
                  Open Azure summary
                </a>
              ) : null}
              {assessmentIntroAvatarError ? <p className="mt-2 text-red-600">{assessmentIntroAvatarError}</p> : null}
            </div>
            <div className="flex flex-wrap gap-2">
              <button
                type="submit"
                formAction={avatarGenerationAction}
                disabled={generatingAvatar || refreshingAvatar}
                className="rounded-full border border-[var(--accent)] bg-[var(--accent)] px-5 py-2 text-xs uppercase tracking-[0.2em] text-white disabled:cursor-not-allowed disabled:opacity-60"
              >
                {generatingAvatar ? "Generating avatar…" : "Generate avatar"}
              </button>
              <button
                type="submit"
                formAction={avatarRefreshAction}
                disabled={refreshingAvatar || generatingAvatar}
                className="rounded-full border border-[#e7e1d6] bg-white px-5 py-2 text-xs uppercase tracking-[0.2em] text-[#3c332b] disabled:cursor-not-allowed disabled:opacity-60"
              >
                {refreshingAvatar ? "Refreshing…" : "Refresh avatar status"}
              </button>
            </div>
            {avatarGenerationState.error ? <p className="text-sm text-red-600">{avatarGenerationState.error}</p> : null}
            {avatarRefreshState.error ? <p className="text-sm text-red-600">{avatarRefreshState.error}</p> : null}
            {assessmentIntroAvatarUrl ? (
              <div className="rounded-xl border border-[#efe7db] bg-white p-3">
                <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Video preview</p>
                <video
                  key={assessmentIntroAvatarUrl}
                  controls
                  preload="metadata"
                  playsInline
                  poster={assessmentIntroAvatarPosterUrl || undefined}
                  className="mt-2 w-full rounded-2xl border border-[#efe7db]"
                >
                  <source src={assessmentIntroAvatarUrl} />
                </video>
                <a
                  href={assessmentIntroAvatarUrl}
                  target="_blank"
                  rel="noreferrer"
                  className="mt-2 inline-flex text-[11px] uppercase tracking-[0.2em] text-[var(--accent)]"
                >
                  Open video
                </a>
              </div>
            ) : null}
          </div>
          {podcastUrl ? (
            <div className="rounded-xl border border-[#efe7db] bg-[#fdfaf4] p-3">
              <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Podcast preview</p>
              <audio key={podcastUrl} controls preload="none" className="mt-2 w-full" src={podcastUrl} />
              <a
                href={podcastUrl}
                target="_blank"
                rel="noreferrer"
                className="mt-2 inline-flex text-[11px] uppercase tracking-[0.2em] text-[var(--accent)]"
              >
                Open audio
              </a>
            </div>
          ) : null}
          <button
            type="submit"
            disabled={saving}
            className="rounded-full border border-[var(--accent)] bg-[var(--accent)] px-5 py-2 text-xs uppercase tracking-[0.2em] text-white disabled:cursor-not-allowed disabled:opacity-60"
          >
            {saving ? "Saving…" : "Save intro settings"}
          </button>
          {saveState.error ? <p className="text-sm text-red-600">{saveState.error}</p> : null}
          {saveState.ok ? <p className="text-sm text-[var(--accent)]">Saved.</p> : null}
        </form>
      </section>
    </div>
  );
}
