"use client";

import { useState } from "react";

type KRUpdateEditorProps = {
  userId: string | number;
  krId: number;
  initialDescription?: string | null;
  initialActual?: number | null;
  initialTarget?: number | null;
};

function numberToString(value?: number | null) {
  if (value === null || value === undefined) return "";
  if (Number.isInteger(value)) return String(value);
  return String(value);
}

export default function KRUpdateEditor({
  userId,
  krId,
  initialDescription,
  initialActual,
  initialTarget,
}: KRUpdateEditorProps) {
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [description, setDescription] = useState((initialDescription || "").trim());
  const [actual, setActual] = useState(numberToString(initialActual));
  const [target, setTarget] = useState(numberToString(initialTarget));

  const onSave = async () => {
    setSaving(true);
    setError(null);
    setSuccess(null);
    try {
      const payload = {
        userId,
        description: description.trim(),
        actual_num: actual.trim() === "" ? null : Number(actual),
        target_num: target.trim() === "" ? null : Number(target),
        note: "KR updated in app",
      };
      if (payload.actual_num !== null && !Number.isFinite(payload.actual_num)) {
        throw new Error("Current value must be numeric.");
      }
      if (payload.target_num !== null && !Number.isFinite(payload.target_num)) {
        throw new Error("Target value must be numeric.");
      }
      if (!payload.description) {
        throw new Error("Description is required.");
      }
      const res = await fetch(`/api/krs/${krId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        const text = await res.text().catch(() => "");
        throw new Error(text || "Failed to update KR");
      }
      const data = await res.json().catch(() => ({}));
      setDescription(String(data?.description || payload.description));
      setActual(numberToString(data?.actual_num));
      setTarget(numberToString(data?.target_num));
      setSuccess("Saved");
      setEditing(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  };

  if (!editing) {
    return (
      <div className="mt-3">
        <button
          type="button"
          className="rounded-full border border-[#efe7db] px-3 py-1 text-[11px] uppercase tracking-[0.2em]"
          onClick={() => {
            setError(null);
            setSuccess(null);
            setEditing(true);
          }}
        >
          Update KR
        </button>
        {success ? <p className="mt-1 text-[11px] text-[#027a48]">{success}</p> : null}
      </div>
    );
  }

  return (
    <div className="mt-3 space-y-2 rounded-xl border border-[#efe7db] bg-[#fffaf4] p-3">
      <p className="text-[11px] uppercase tracking-[0.2em] text-[#6b6257]">Update KR</p>
      <textarea
        className="w-full rounded-xl border border-[#efe7db] bg-white px-3 py-2 text-xs"
        rows={2}
        value={description}
        onChange={(event) => setDescription(event.target.value)}
        placeholder="KR description"
      />
      <div className="grid grid-cols-2 gap-2">
        <input
          className="rounded-xl border border-[#efe7db] bg-white px-3 py-2 text-xs"
          value={actual}
          onChange={(event) => setActual(event.target.value)}
          placeholder="Current value"
          inputMode="decimal"
        />
        <input
          className="rounded-xl border border-[#efe7db] bg-white px-3 py-2 text-xs"
          value={target}
          onChange={(event) => setTarget(event.target.value)}
          placeholder="Target value"
          inputMode="decimal"
        />
      </div>
      {error ? <p className="text-xs text-[#b42318]">{error}</p> : null}
      <div className="flex gap-2">
        <button
          type="button"
          className="rounded-full border border-[#efe7db] px-3 py-1 text-[11px] uppercase tracking-[0.2em]"
          onClick={() => setEditing(false)}
          disabled={saving}
        >
          Cancel
        </button>
        <button
          type="button"
          className="rounded-full border border-[var(--accent)] bg-[var(--accent)] px-3 py-1 text-[11px] uppercase tracking-[0.2em] text-white"
          onClick={onSave}
          disabled={saving}
        >
          {saving ? "Saving..." : "Save"}
        </button>
      </div>
    </div>
  );
}
