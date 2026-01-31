"use client";

import { useActionState, useMemo, useState } from "react";
import type { ContentPromptTemplateDetail } from "@/lib/api";
import { saveContentTemplateAction } from "../actions";

type TemplateFormProps = {
  template: ContentPromptTemplateDetail | null;
  conceptsByPillar: Record<string, { code: string; name: string }[]>;
};

const emptyState = { ok: false, error: null as string | null };
const pillarOptions = [
  { value: "", label: "Any pillar" },
  { value: "nutrition", label: "Nutrition" },
  { value: "recovery", label: "Recovery" },
  { value: "training", label: "Training" },
  { value: "resilience", label: "Resilience" },
  { value: "habit_forming", label: "Habit forming" },
];

export default function ContentTemplateForm({ template, conceptsByPillar }: TemplateFormProps) {
  const [saveState, saveAction, savePending] = useActionState(saveContentTemplateAction, emptyState);
  const [pillar, setPillar] = useState(template?.pillar_key || "");
  const conceptOptions = useMemo(() => {
    return pillar ? conceptsByPillar[pillar] || [] : [];
  }, [pillar, conceptsByPillar]);
  const conceptValue = template?.concept_code || "";

  return (
    <div className="space-y-6">
      <form action={saveAction} className="space-y-4">
        <input type="hidden" name="id" value={template?.id ?? ""} />
        <div>
          <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Template key</label>
          <input
            name="template_key"
            defaultValue={template?.template_key || ""}
            className="mt-2 w-full rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
            placeholder="library_snippet"
            readOnly={Boolean(template?.id)}
          />
        </div>
        <div className="grid gap-4 md:grid-cols-2">
          <div>
            <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Label</label>
            <input
              name="label"
              defaultValue={template?.label || ""}
              className="mt-2 w-full rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
              placeholder="Library snippet"
            />
          </div>
          <div>
            <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Response format</label>
            <input
              name="response_format"
              defaultValue={template?.response_format || ""}
              className="mt-2 w-full rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
              placeholder="text | json"
            />
          </div>
        </div>
        <div className="grid gap-4 md:grid-cols-2">
          <div>
            <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Pillar (optional)</label>
            <select
              name="pillar_key"
              value={pillar}
              onChange={(event) => setPillar(event.target.value)}
              className="mt-2 w-full rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
            >
              {pillarOptions.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Concept (optional)</label>
            <select
              name="concept_code"
              defaultValue={conceptValue}
              className="mt-2 w-full rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
            >
              <option value="">Any concept</option>
              {conceptValue && !conceptOptions.find((item) => item.code === conceptValue) ? (
                <option value={conceptValue}>{conceptValue}</option>
              ) : null}
              {conceptOptions.map((item) => (
                <option key={item.code} value={item.code}>
                  {item.name || item.code}
                </option>
              ))}
            </select>
          </div>
        </div>
        <div>
          <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Blocks (order = include)</label>
          <input
            name="block_order"
            defaultValue={(template?.block_order || template?.include_blocks || []).join(", ")}
            className="mt-2 w-full rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
            placeholder="system, locale, context, task"
          />
        </div>
        <div>
          <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Task block</label>
          <textarea
            name="task_block"
            defaultValue={template?.task_block || ""}
            rows={8}
            className="mt-2 w-full rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
          />
        </div>
        <div>
          <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Notes</label>
          <textarea
            name="note"
            defaultValue={template?.note || ""}
            rows={3}
            className="mt-2 w-full rounded-xl border border-[#efe7db] px-3 py-2 text-sm"
          />
        </div>
        <label className="flex items-center gap-2 text-sm text-[#6b6257]">
          <input type="checkbox" name="is_active" defaultChecked={template?.is_active ?? true} />
          Active
        </label>
        <button
          type="submit"
          disabled={savePending}
          className="rounded-full border border-[#0f766e] bg-[#0f766e] px-5 py-2 text-xs uppercase tracking-[0.2em] text-white disabled:cursor-not-allowed disabled:opacity-60"
        >
          {savePending ? "Saving…" : "Save template"}
        </button>
        {saveState.error ? <p className="text-sm text-red-600">{saveState.error}</p> : null}
        {saveState.ok ? <p className="text-sm text-[#0f766e]">Saved.</p> : null}
      </form>
    </div>
  );
}
