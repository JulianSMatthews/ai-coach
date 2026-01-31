"use client";

import { useActionState } from "react";
import type { ContentLibraryDetail } from "@/lib/api";

type ContentEditorFormProps = {
  content?: ContentLibraryDetail | null;
  action: (state: { ok: boolean; error?: string }, formData: FormData) => Promise<{ ok: boolean; error?: string }>;
  submitLabel?: string;
};

const emptyState = { ok: false, error: null as string | null };
const pillarOptions = [
  { value: "nutrition", label: "Nutrition" },
  { value: "recovery", label: "Recovery" },
  { value: "training", label: "Training" },
  { value: "resilience", label: "Resilience" },
  { value: "habit_forming", label: "Habit forming" },
];

export default function ContentEditorForm({ content, action, submitLabel }: ContentEditorFormProps) {
  const [state, formAction, pending] = useActionState(action, emptyState);
  const tagsValue = Array.isArray(content?.tags) ? content?.tags?.join(", ") : "";
  const publishedDate = content?.published_at ? String(content.published_at).slice(0, 10) : "";

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
          <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Podcast URL (optional)</label>
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
      <button
        type="submit"
        disabled={pending}
        className="rounded-full border border-[#0f766e] bg-[#0f766e] px-5 py-2 text-xs uppercase tracking-[0.2em] text-white disabled:cursor-not-allowed disabled:opacity-60"
      >
        {pending ? "Saving…" : submitLabel || "Save content"}
      </button>
      {state.error ? <p className="text-sm text-red-600">{state.error}</p> : null}
      {state.ok ? <p className="text-sm text-[#0f766e]">Saved.</p> : null}
    </form>
  );
}
