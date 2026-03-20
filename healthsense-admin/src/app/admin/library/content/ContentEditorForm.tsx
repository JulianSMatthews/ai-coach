"use client";

import { useActionState, useEffect, useState } from "react";
import type { ContentLibraryDetail } from "@/lib/api";

type SaveState = { ok: boolean; error?: string };
type AvatarState = { ok: boolean; error?: string; avatar?: Record<string, unknown> | null };

type ContentEditorFormProps = {
  content?: ContentLibraryDetail | null;
  action: (state: SaveState, formData: FormData) => Promise<SaveState>;
  avatarGenerateAction?: (state: AvatarState, formData: FormData) => Promise<AvatarState>;
  avatarRefreshAction?: (state: AvatarState, formData: FormData) => Promise<AvatarState>;
  submitLabel?: string;
};

const emptyState = { ok: false, error: undefined as string | undefined };
const emptyAvatarState = {
  ok: false,
  error: undefined as string | undefined,
  avatar: null as Record<string, unknown> | null,
};
const pillarOptions = [
  { value: "nutrition", label: "Nutrition" },
  { value: "recovery", label: "Recovery" },
  { value: "training", label: "Training" },
  { value: "resilience", label: "Resilience" },
  { value: "habit_forming", label: "Habit forming" },
];

function normalizeAvatar(raw: Record<string, unknown> | null | undefined, fallbackTitle: string, fallbackScript: string) {
  return {
    url: String(raw?.url || "").trim(),
    title: String(raw?.title || "").trim() || fallbackTitle,
    script: String(raw?.script || "").trim() || fallbackScript,
    poster_url: String(raw?.poster_url || "").trim(),
    character: String(raw?.character || "").trim() || "lisa",
    style: String(raw?.style || "").trim() || "graceful-sitting",
    voice: String(raw?.voice || "").trim() || "en-GB-SoniaNeural",
    status: String(raw?.status || "").trim(),
    job_id: String(raw?.job_id || "").trim(),
    error: String(raw?.error || "").trim(),
    generated_at: String(raw?.generated_at || "").trim(),
    summary_url: String(raw?.summary_url || "").trim(),
  };
}

export default function ContentEditorForm({
  content,
  action,
  avatarGenerateAction,
  avatarRefreshAction,
  submitLabel,
}: ContentEditorFormProps) {
  const [state, formAction, pending] = useActionState(action, emptyState);
  const [avatarGenerationState, avatarGenerationFormAction, generatingAvatar] = useActionState(
    avatarGenerateAction || (async () => emptyAvatarState),
    emptyAvatarState,
  );
  const [avatarRefreshState, avatarRefreshFormAction, refreshingAvatar] = useActionState(
    avatarRefreshAction || (async () => emptyAvatarState),
    emptyAvatarState,
  );
  const tagsValue = Array.isArray(content?.tags) ? content?.tags?.join(", ") : "";
  const publishedDate = content?.published_at ? String(content.published_at).slice(0, 10) : "";
  const initialAvatar = normalizeAvatar(
    (content?.avatar as Record<string, unknown> | null | undefined) || null,
    String(content?.title || "").trim(),
    String(content?.body || "").trim(),
  );
  const [avatarUrl, setAvatarUrl] = useState(initialAvatar.url);
  const [avatarTitle, setAvatarTitle] = useState(initialAvatar.title);
  const [avatarScript, setAvatarScript] = useState(initialAvatar.script);
  const [avatarPosterUrl, setAvatarPosterUrl] = useState(initialAvatar.poster_url);
  const [avatarCharacter, setAvatarCharacter] = useState(initialAvatar.character);
  const [avatarStyle, setAvatarStyle] = useState(initialAvatar.style);
  const [avatarVoice, setAvatarVoice] = useState(initialAvatar.voice);
  const [avatarStatus, setAvatarStatus] = useState(initialAvatar.status);
  const [avatarJobId, setAvatarJobId] = useState(initialAvatar.job_id);
  const [avatarError, setAvatarError] = useState(initialAvatar.error);
  const [avatarGeneratedAt, setAvatarGeneratedAt] = useState(initialAvatar.generated_at);
  const [avatarSummaryUrl, setAvatarSummaryUrl] = useState(initialAvatar.summary_url);
  const canManageAvatar = Boolean(content?.id);

  useEffect(() => {
    const next = avatarGenerationState.avatar || avatarRefreshState.avatar;
    if (!next) return;
    const normalized = normalizeAvatar(
      next,
      String(content?.title || "").trim(),
      String(content?.body || "").trim(),
    );
    queueMicrotask(() => {
      setAvatarUrl(normalized.url);
      setAvatarTitle(normalized.title);
      setAvatarScript(normalized.script);
      setAvatarPosterUrl(normalized.poster_url);
      setAvatarCharacter(normalized.character);
      setAvatarStyle(normalized.style);
      setAvatarVoice(normalized.voice);
      setAvatarStatus(normalized.status);
      setAvatarJobId(normalized.job_id);
      setAvatarError(normalized.error);
      setAvatarGeneratedAt(normalized.generated_at);
      setAvatarSummaryUrl(normalized.summary_url);
    });
  }, [
    avatarGenerationState.avatar,
    avatarRefreshState.avatar,
    content?.body,
    content?.title,
  ]);

  return (
    <form action={formAction} className="space-y-4">
      <div className="grid gap-3 md:grid-cols-2">
        <div>
          <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Pillar</label>
          <select
            name="pillar_key"
            className="mt-2 w-full rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
            defaultValue={content?.pillar_key || "nutrition"}
          >
            {pillarOptions.map((p) => (
              <option key={p.value} value={p.value}>
                {p.label}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Concept (optional)</label>
          <input
            name="concept_code"
            defaultValue={content?.concept_code || ""}
            className="mt-2 w-full rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
            placeholder="hydration"
          />
          <p className="mt-2 text-xs text-[#6b6257]">
            Use the tracker concept key, for example <code>hydration</code>, <code>protein_intake</code>, or <code>sleep_duration</code>.
          </p>
        </div>
      </div>
      <div>
        <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Title</label>
        <input
          name="title"
          defaultValue={content?.title || ""}
          className="mt-2 w-full rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
        />
      </div>
      <div>
        <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Body</label>
        <textarea
          name="body"
          rows={10}
          defaultValue={content?.body || ""}
          className="mt-2 w-full rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
        />
      </div>
      <div className="grid gap-3 md:grid-cols-2">
        <div>
          <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Status</label>
          <select
            name="status"
            className="mt-2 w-full rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
            defaultValue={content?.status || "draft"}
          >
            <option value="draft">Draft</option>
            <option value="published">Published</option>
          </select>
        </div>
        <div>
          <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Published date</label>
          <input
            type="date"
            name="published_at"
            defaultValue={publishedDate}
            className="mt-2 w-full rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
          />
        </div>
      </div>
      <div className="grid gap-3 md:grid-cols-2">
        <div>
          <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Source type</label>
          <input
            name="source_type"
            defaultValue={content?.source_type || ""}
            className="mt-2 w-full rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
            placeholder="journal | blog | manual"
          />
        </div>
        <div>
          <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Source URL</label>
          <input
            name="source_url"
            defaultValue={content?.source_url || ""}
            className="mt-2 w-full rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
            placeholder="https://..."
          />
        </div>
        <div>
          <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">License</label>
          <input
            name="license"
            defaultValue={content?.license || ""}
            className="mt-2 w-full rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
            placeholder="cc-by"
          />
        </div>
        <div>
          <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Level</label>
          <input
            name="level"
            defaultValue={content?.level || ""}
            className="mt-2 w-full rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
            placeholder="intro | intermediate | advanced"
          />
        </div>
        <div className="md:col-span-2">
          <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Tags (comma-separated)</label>
          <input
            name="tags"
            defaultValue={tagsValue}
            className="mt-2 w-full rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
            placeholder="sleep, cbt-i, routines"
          />
        </div>
      </div>
      <div className="grid gap-3 md:grid-cols-2">
        <div>
          <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Media URL (optional)</label>
          <input
            name="podcast_url"
            defaultValue={content?.podcast_url || ""}
            className="mt-2 w-full rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
            placeholder="https://..."
          />
        </div>
        <div>
          <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Podcast voice</label>
          <input
            name="podcast_voice"
            defaultValue={content?.podcast_voice || ""}
            className="mt-2 w-full rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
            placeholder="alloy"
          />
        </div>
      </div>

      {canManageAvatar ? (
        <div className="rounded-2xl border border-[#efe7db] bg-[#fffaf3] p-4">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <p className="text-sm font-semibold text-[#1e1b16]">Insight avatar</p>
              <p className="mt-1 text-sm text-[#6b6257]">
                Generate an avatar for this existing content item, save the avatar settings, and preview the result below.
              </p>
            </div>
          </div>

          <div className="mt-4 grid gap-3 md:grid-cols-2">
            <div>
              <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Video URL</label>
              <input
                name="avatar_url"
                value={avatarUrl}
                onChange={(event) => setAvatarUrl(event.target.value)}
                className="mt-2 w-full rounded-xl border border-[#efe7db] bg-white px-3 py-2 text-sm"
                placeholder="https://..."
              />
            </div>
            <div>
              <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Avatar title</label>
              <input
                name="avatar_title"
                value={avatarTitle}
                onChange={(event) => setAvatarTitle(event.target.value)}
                className="mt-2 w-full rounded-xl border border-[#efe7db] bg-white px-3 py-2 text-sm"
              />
            </div>
            <div>
              <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Poster URL</label>
              <input
                name="avatar_poster_url"
                value={avatarPosterUrl}
                onChange={(event) => setAvatarPosterUrl(event.target.value)}
                className="mt-2 w-full rounded-xl border border-[#efe7db] bg-white px-3 py-2 text-sm"
                placeholder="https://..."
              />
            </div>
            <div>
              <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Character</label>
              <input
                name="avatar_character"
                value={avatarCharacter}
                onChange={(event) => setAvatarCharacter(event.target.value)}
                className="mt-2 w-full rounded-xl border border-[#efe7db] bg-white px-3 py-2 text-sm"
                placeholder="lisa"
              />
            </div>
            <div>
              <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Style</label>
              <input
                name="avatar_style"
                value={avatarStyle}
                onChange={(event) => setAvatarStyle(event.target.value)}
                className="mt-2 w-full rounded-xl border border-[#efe7db] bg-white px-3 py-2 text-sm"
                placeholder="graceful-sitting"
              />
            </div>
            <div>
              <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Voice</label>
              <input
                name="avatar_voice"
                value={avatarVoice}
                onChange={(event) => setAvatarVoice(event.target.value)}
                className="mt-2 w-full rounded-xl border border-[#efe7db] bg-white px-3 py-2 text-sm"
                placeholder="en-GB-SoniaNeural"
              />
            </div>
            <div className="md:col-span-2">
              <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Avatar script</label>
              <textarea
                name="avatar_script"
                rows={8}
                value={avatarScript}
                onChange={(event) => setAvatarScript(event.target.value)}
                className="mt-2 w-full rounded-xl border border-[#efe7db] bg-white px-3 py-2 text-sm"
              />
            </div>
          </div>

          <div className="mt-4 rounded-xl border border-[#efe7db] bg-white p-3 text-sm text-[#6b6257]">
            <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Azure avatar status</p>
            <p className="mt-2">Status: {avatarStatus || "not generated"}</p>
            {avatarJobId ? <p className="mt-1 break-all">Job ID: {avatarJobId}</p> : null}
            {avatarGeneratedAt ? <p className="mt-1">Generated: {avatarGeneratedAt}</p> : null}
            {avatarSummaryUrl ? (
              <a
                href={avatarSummaryUrl}
                target="_blank"
                rel="noreferrer"
                className="mt-2 inline-flex text-[11px] uppercase tracking-[0.2em] text-[var(--accent)]"
              >
                Open Azure summary
              </a>
            ) : null}
            {avatarError ? <p className="mt-2 text-red-600">{avatarError}</p> : null}
          </div>

          <div className="mt-4 flex flex-wrap gap-2">
            <button
              type="submit"
              formAction={formAction}
              disabled={pending || generatingAvatar || refreshingAvatar}
              className="rounded-full border border-[#e7e1d6] bg-white px-5 py-2 text-xs uppercase tracking-[0.2em] text-[#3c332b] disabled:cursor-not-allowed disabled:opacity-60"
            >
              {pending ? "Saving avatar…" : "Save avatar settings"}
            </button>
            {avatarGenerateAction ? (
              <button
                type="submit"
                formAction={avatarGenerationFormAction}
                disabled={pending || generatingAvatar || refreshingAvatar}
                className="rounded-full border border-[var(--accent)] bg-[var(--accent)] px-5 py-2 text-xs uppercase tracking-[0.2em] text-white disabled:cursor-not-allowed disabled:opacity-60"
              >
                {generatingAvatar ? "Generating avatar…" : "Generate avatar"}
              </button>
            ) : null}
            {avatarRefreshAction ? (
              <button
                type="submit"
                formAction={avatarRefreshFormAction}
                disabled={pending || generatingAvatar || refreshingAvatar || !avatarJobId}
                className="rounded-full border border-[#e7e1d6] bg-white px-5 py-2 text-xs uppercase tracking-[0.2em] text-[#3c332b] disabled:cursor-not-allowed disabled:opacity-60"
              >
                {refreshingAvatar ? "Refreshing…" : "Refresh avatar status"}
              </button>
            ) : null}
          </div>
          {avatarGenerationState.error ? <p className="mt-3 text-sm text-red-600">{avatarGenerationState.error}</p> : null}
          {avatarRefreshState.error ? <p className="mt-3 text-sm text-red-600">{avatarRefreshState.error}</p> : null}

          {avatarUrl ? (
            <div className="mt-4 rounded-xl border border-[#efe7db] bg-white p-3">
              <p className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Video preview</p>
              <video
                key={avatarUrl}
                controls
                preload="metadata"
                playsInline
                poster={avatarPosterUrl || undefined}
                className="mt-2 w-full rounded-2xl border border-[#efe7db]"
              >
                <source src={avatarUrl} />
              </video>
              <a
                href={avatarUrl}
                target="_blank"
                rel="noreferrer"
                className="mt-2 inline-flex text-[11px] uppercase tracking-[0.2em] text-[var(--accent)]"
              >
                Open video
              </a>
            </div>
          ) : (
            <div className="mt-4 rounded-xl border border-dashed border-[#d9cdbb] bg-white px-4 py-4 text-sm text-[#6b6257]">
              Save avatar settings, generate an avatar, or paste a video URL to preview it here.
            </div>
          )}
        </div>
      ) : (
        <div className="rounded-2xl border border-[#efe7db] bg-[#fffaf3] p-4">
          <p className="text-sm font-semibold text-[#1e1b16]">Insight avatar</p>
          <p className="mt-1 text-sm text-[#6b6257]">
            Create this content first. Once it exists, you can open it again to save avatar settings, generate the avatar, and preview the video on that same content item.
          </p>
        </div>
      )}

      <button
        type="submit"
        disabled={pending || generatingAvatar || refreshingAvatar}
        className="rounded-full border border-[var(--accent)] bg-[var(--accent)] px-5 py-2 text-xs uppercase tracking-[0.2em] text-white disabled:cursor-not-allowed disabled:opacity-60"
      >
        {pending ? "Saving…" : submitLabel || "Save content"}
      </button>
      {state.error ? <p className="text-sm text-red-600">{state.error}</p> : null}
      {state.ok ? <p className="text-sm text-[var(--accent)]">Saved.</p> : null}
    </form>
  );
}
