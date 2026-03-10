"use client";

import { useState } from "react";

type CopyValueFieldProps = {
  value: string;
  buttonLabel?: string;
};

export default function CopyValueField({
  value,
  buttonLabel = "Copy URL",
}: CopyValueFieldProps) {
  const [copied, setCopied] = useState(false);

  async function onCopy() {
    const text = String(value || "").trim();
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1800);
    } catch {
      setCopied(false);
    }
  }

  return (
    <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
      <input
        type="text"
        value={value}
        readOnly
        className="w-full rounded-xl border border-[#efe7db] bg-white px-3 py-2 text-sm text-[#3c332b]"
      />
      <button
        type="button"
        onClick={onCopy}
        className="rounded-full border border-[var(--accent)] bg-[var(--accent)] px-4 py-2 text-xs uppercase tracking-[0.2em] text-white"
      >
        {copied ? "Copied" : buttonLabel}
      </button>
    </div>
  );
}
