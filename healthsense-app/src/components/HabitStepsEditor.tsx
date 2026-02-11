"use client";

import { useMemo, useState } from "react";

type HabitStep = {
  id?: number;
  text?: string;
  status?: string;
  week_no?: number | null;
};
type HabitStepItem = {
  id?: number;
  text: string;
  status: "active" | "done";
  week_no: number | null;
};

type HabitStepsEditorProps = {
  userId: string | number;
  krId: number;
  initialSteps?: HabitStep[];
};

function normalizeStatus(value?: string): "active" | "done" {
  const v = (value || "").toLowerCase();
  if (v === "done" || v === "complete" || v === "completed") return "done";
  return "active";
}

function normalizeSteps(steps: HabitStep[]): HabitStepItem[] {
  return (steps || [])
    .map((step) => ({
      id: step?.id,
      text: (step?.text || "").trim(),
      status: normalizeStatus(step?.status),
      week_no: step?.week_no ?? null,
    }))
    .filter((step) => step.text);
}

function stepsToDraft(steps: HabitStepItem[]) {
  return steps.map((step) => step.text).join("\n");
}

function toPayloadSteps(steps: HabitStepItem[]) {
  return steps.map((step, idx) => ({
    text: step.text,
    status: step.status,
    week_no: step.week_no,
    sort_order: idx,
  }));
}

export default function HabitStepsEditor({ userId, krId, initialSteps = [] }: HabitStepsEditorProps) {
  const [steps, setSteps] = useState<HabitStepItem[]>(() => normalizeSteps(initialSteps));
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  const [draft, setDraft] = useState<string>(() => stepsToDraft(normalizeSteps(initialSteps)));
  const doneCount = useMemo(() => steps.filter((step) => step.status === "done").length, [steps]);
  const xp = doneCount * 10;

  const onEditToggle = () => {
    setError(null);
    setSuccess(false);
    setDraft(stepsToDraft(steps));
    setEditing((prev) => !prev);
  };

  const persist = async (nextSteps: HabitStepItem[], closeEditor: boolean) => {
    setSaving(true);
    setError(null);
    setSuccess(false);
    try {
      const res = await fetch(`/api/krs/${krId}/habit-steps`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ userId, steps: toPayloadSteps(nextSteps) }),
      });
      if (!res.ok) {
        const text = await res.text().catch(() => "");
        throw new Error(text || "Failed to update habit steps");
      }
      const data = await res.json().catch(() => ({}));
      const savedSteps = normalizeSteps(data?.steps || []);
      setSteps(savedSteps);
      if (closeEditor) setEditing(false);
      setSuccess(true);
      return true;
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      return false;
    } finally {
      setSaving(false);
    }
  };

  const onSave = async () => {
    const cleaned = draft
      .split("\n")
      .map((line) => line.trim())
      .filter(Boolean);
    const byText = new Map<string, HabitStepItem>();
    steps.forEach((step) => {
      if (!byText.has(step.text)) byText.set(step.text, step);
    });
    const nextSteps = cleaned.map((text) => {
      const existing = byText.get(text);
      return {
        id: existing?.id,
        text,
        status: existing?.status || "active",
        week_no: existing?.week_no ?? null,
      } as HabitStepItem;
    });
    await persist(nextSteps, true);
  };

  const onToggleDone = async (index: number) => {
    if (saving) return;
    const current = steps[index];
    if (!current) return;
    const previous = steps;
    const updated: HabitStepItem[] = steps.map((step, idx): HabitStepItem =>
      idx === index ? { ...step, status: step.status === "done" ? "active" : "done" } : step,
    );
    setSteps(updated);
    const ok = await persist(updated, false);
    if (!ok) setSteps(previous);
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
            className="rounded-full border border-[var(--accent)] bg-[var(--accent)] px-3 py-1 text-[11px] uppercase tracking-[0.2em] text-white"
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
      <p className="text-[11px] text-[#6b6257]">
        {doneCount}/{steps.length} complete{steps.length ? ` • ${xp} XP` : ""}
      </p>
      {steps.length ? (
        <ul className="space-y-1 text-xs text-[#3c332b]">
          {steps.map((step, idx) => (
            <li key={`${krId}-${idx}`} className="flex gap-2">
              <button
                type="button"
                className={`mt-[1px] flex h-4 w-4 shrink-0 items-center justify-center rounded border ${
                  step.status === "done"
                    ? "border-[#027a48] bg-[#ecfdf3] text-[#027a48]"
                    : "border-[#d0d5dd] bg-white text-transparent"
                }`}
                aria-label={step.status === "done" ? "Mark habit as active" : "Mark habit as done"}
                onClick={() => void onToggleDone(idx)}
                disabled={saving}
              >
                ✓
              </button>
              <span className={step.status === "done" ? "text-[#667085] line-through" : ""}>{step.text}</span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-xs text-[#6b6257]">No habit steps yet.</p>
      )}
      {saving ? <p className="text-[11px] text-[#6b6257]">Saving…</p> : null}
      {success ? <p className="text-[11px] text-[#027a48]">Saved.</p> : null}
      {error ? <p className="text-xs text-[#b42318]">{error}</p> : null}
    </div>
  );
}
