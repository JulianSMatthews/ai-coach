"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

type KRUpdateEditorProps = {
  userId: string | number;
  krId: number;
  initialDescription?: string | null;
  initialActual?: number | null;
  initialTarget?: number | null;
  metricLabel?: string | null;
  unit?: string | null;
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
  metricLabel,
  unit,
}: KRUpdateEditorProps) {
  const router = useRouter();
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [actual, setActual] = useState(numberToString(initialActual));
  const target = numberToString(initialTarget);
  const description = (initialDescription || "").trim();
  const unitHint = [metricLabel?.trim(), unit?.trim()].filter(Boolean).join(" · ");

  const onSave = async () => {
    setSaving(true);
    setError(null);
    setSuccess(null);
    try {
      const payload = {
        userId,
        actual_num: actual.trim() === "" ? null : Number(actual),
        note: "KR updated in app",
      };
      if (payload.actual_num !== null && !Number.isFinite(payload.actual_num)) {
        throw new Error("Current value must be numeric.");
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
      setActual(numberToString(data?.actual_num));
      setSuccess("Saved");
      setEditing(false);
      router.refresh();
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
      <p className="rounded-xl border border-[#efe7db] bg-white px-3 py-2 text-xs text-[#3c332b]">
        {description || "Key result"}
      </p>
      <p className="text-xs text-[#6b6257]">
        Enter your latest current value only.
        {unitHint ? ` Use ${unitHint}.` : " Use the same unit as your target."}
      </p>
      <div className="grid grid-cols-2 gap-2">
        <label className="space-y-1">
          <span className="text-[10px] uppercase tracking-[0.18em] text-[#8b8074]">Current value</span>
          <input
            className="w-full rounded-xl border border-[#efe7db] bg-white px-3 py-2 text-xs"
            value={actual}
            onChange={(event) => setActual(event.target.value)}
            placeholder="e.g. 3"
            inputMode="decimal"
          />
        </label>
        <label className="space-y-1">
          <span className="text-[10px] uppercase tracking-[0.18em] text-[#8b8074]">Target (fixed)</span>
          <input
            className="w-full rounded-xl border border-[#efe7db] bg-[#f8f3ec] px-3 py-2 text-xs text-[#6b6257]"
            value={target}
            readOnly
            disabled
          />
        </label>
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
