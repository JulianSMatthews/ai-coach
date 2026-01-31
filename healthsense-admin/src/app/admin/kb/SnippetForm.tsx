"use client";

import { useActionState } from "react";
import type { KbSnippetDetail } from "@/lib/api";
import { saveKbSnippetAction } from "./actions";

type SnippetFormProps = {
  snippet: KbSnippetDetail | null;
};

const emptyState = { ok: false, error: null as string | null };

const PILLAR_OPTIONS = ["nutrition", "training", "resilience", "recovery", "goals"];

export default function SnippetForm({ snippet }: SnippetFormProps) {
  const [saveState, saveAction, savePending] = useActionState(saveKbSnippetAction, emptyState);

  return (
    <form action={saveAction} className="space-y-4">
      <input type="hidden" name="id" value={snippet?.id ?? ""} />

      <div className="grid gap-4 md:grid-cols-2">
        <div>
          <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Pillar</label>
          <select
            name="pillar_key"
            defaultValue={snippet?.pillar_key || "nutrition"}
            className="mt-2 w-full rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
            required
          >
            {PILLAR_OPTIONS.map((opt) => (
              <option key={opt} value={opt}>
                {opt.charAt(0).toUpperCase() + opt.slice(1)}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Concept code</label>
          <input
            name="concept_code"
            defaultValue={snippet?.concept_code || ""}
            className="mt-2 w-full rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
            placeholder="sleep_quality"
          />
          <p className="mt-1 text-xs text-[#8a8074]">Optional. Leave blank for pillar-wide snippets.</p>
        </div>
      </div>

      <div>
        <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Title</label>
        <input
          name="title"
          defaultValue={snippet?.title || ""}
          className="mt-2 w-full rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
          placeholder="Hydration basics"
        />
      </div>

      <div>
        <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Tags</label>
        <input
          name="tags"
          defaultValue={(snippet?.tags || []).join(", ")}
          className="mt-2 w-full rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
          placeholder="hydration, sodium, habits"
        />
      </div>

      <div>
        <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Snippet text</label>
        <textarea
          name="text"
          defaultValue={snippet?.text || ""}
          rows={10}
          className="mt-2 w-full rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
          required
        />
      </div>

      <button
        type="submit"
        disabled={savePending}
        className="rounded-full border border-[#0f766e] bg-[#0f766e] px-5 py-2 text-xs uppercase tracking-[0.2em] text-white disabled:cursor-not-allowed disabled:opacity-60"
      >
        {savePending ? "Saving…" : "Save snippet"}
      </button>
      {saveState.error ? <p className="text-sm text-red-600">{saveState.error}</p> : null}
      {saveState.ok ? <p className="text-sm text-[#0f766e]">Saved.</p> : null}
    </form>
  );
}
