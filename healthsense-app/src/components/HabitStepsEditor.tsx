"use client";

import { useMemo, useState } from "react";

type HabitStep = {
  id?: number;
  text?: string;
  status?: string;
  week_no?: number | null;
};

type HabitStepsEditorProps = {
  userId: string | number;
  krId: number;
  initialSteps?: HabitStep[];
};

function normalizeSteps(steps: HabitStep[]) {
  return (steps || [])
    .map((step) => (step?.text || "").trim())
    .filter(Boolean);
}

export default function HabitStepsEditor({ userId, krId, initialSteps = [] }: HabitStepsEditorProps) {
  const [steps, setSteps] = useState<string[]>(normalizeSteps(initialSteps));
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  const initialText = useMemo(() => steps.join("\n"), [steps]);
  const [draft, setDraft] = useState(initialText);

  const onEditToggle = () => {
    setError(null);
    setSuccess(false);
    setDraft(steps.join("\n"));
    setEditing((prev) => !prev);
  };

  const onSave = async () => {
    setSaving(true);
    setError(null);
    setSuccess(false);
    const cleaned = draft
      .split("\n")
      .map((line) => line.trim())
      .filter(Boolean);
    try {
      const res = await fetch(`/api/krs/${krId}/habit-steps`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ userId, steps: cleaned }),
      });
      if (!res.ok) {
        const text = await res.text().catch(() => "");
        throw new Error(text || "Failed to update habit steps");
      }
      const data = await res.json().catch(() => ({}));
      const nextSteps = normalizeSteps(data?.steps || []);
      setSteps(nextSteps);
      setEditing(false);
      setSuccess(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  };

  if (editing) {
    return (
      <div className="mt-2 space-y-2">
        <p className="text-[11px] uppercase tracking-[0.26em] text-[#8b8074]">Habit steps</p>
        <textarea
          className="w-full rounded-2xl border border-[#eadcc6] bg-white p-3 text-xs text-[#1e1b16]"
          rows={4}
          placeholder="Add one habit step per line."
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
        />
        {error ? <p className="text-xs text-[#b42318]">{error}</p> : null}
        <div className="flex flex-wrap gap-2">
          <button
            className="rounded-full border border-[#efe7db] px-3 py-1 text-[11px] uppercase tracking-[0.2em]"
            type="button"
            onClick={onEditToggle}
            disabled={saving}
          >
            Cancel
          </button>
          <button
            className="rounded-full border border-[#0f766e] bg-[#0f766e] px-3 py-1 text-[11px] uppercase tracking-[0.2em] text-white"
            type="button"
            onClick={onSave}
            disabled={saving}
          >
            {saving ? "Saving…" : "Save"}
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="mt-2 space-y-2">
      <div className="flex items-center justify-between gap-2">
        <p className="text-[11px] uppercase tracking-[0.26em] text-[#8b8074]">Habit steps</p>
        <button
          className="rounded-full border border-[#efe7db] px-2 py-1 text-[10px] uppercase tracking-[0.2em]"
          type="button"
          onClick={onEditToggle}
        >
          Edit
        </button>
      </div>
      {steps.length ? (
        <ul className="space-y-1 text-xs text-[#3c332b]">
          {steps.map((step, idx) => (
            <li key={`${krId}-${idx}`} className="flex gap-2">
              <span className="mt-1 h-1.5 w-1.5 rounded-full bg-[#0ba5ec]" />
              <span>{step}</span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-xs text-[#6b6257]">No habit steps yet.</p>
      )}
      {success ? <p className="text-[11px] text-[#027a48]">Saved.</p> : null}
    </div>
  );
}
