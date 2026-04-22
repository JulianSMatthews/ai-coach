"use client";

import { useEffect, useState } from "react";
import type { FormEvent } from "react";

export default function DeleteAccountForm() {
  const [userId, setUserId] = useState("");
  const [email, setEmail] = useState("");
  const [reason, setReason] = useState("");
  const [confirm, setConfirm] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    try {
      const cookieUserId = document.cookie
        .split("; ")
        .find((item) => item.startsWith("hs_user_id="))
        ?.split("=")[1];
      setUserId(cookieUserId || window.localStorage.getItem("hs_user_id_local") || "");
    } catch {}
  }, []);

  const onSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setStatus(null);
    if (!confirm) {
      setStatus("Confirm that you want HealthSense to start account deletion.");
      return;
    }
    setSubmitting(true);
    try {
      const res = await fetch("/api/account-deletion/request", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          userId: userId || undefined,
          email: email || undefined,
          reason: reason || undefined,
        }),
      });
      const payload = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(payload?.error || "Deletion request failed.");
      }
      setStatus("Deletion request received. HealthSense support will verify the request and follow up.");
      setReason("");
      setConfirm(false);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : String(error));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <form onSubmit={onSubmit} className="space-y-3 text-[15px] leading-6">
      <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface-muted)] p-3">
        <label className="text-[10px] uppercase tracking-[0.2em] text-[var(--text-secondary)]">User ID</label>
        <input
          className="mt-2 w-full rounded-xl border px-3 py-2 text-[15px]"
          value={userId}
          onChange={(event) => setUserId(event.target.value)}
          inputMode="numeric"
          placeholder="Sign in first if this is blank"
        />
        <p className="mt-2 text-[12px] text-[var(--text-secondary)]">
          For security, deletion requests must come from a signed-in account.
        </p>
      </div>

      <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface-muted)] p-3">
        <label className="text-[10px] uppercase tracking-[0.2em] text-[var(--text-secondary)]">Contact email</label>
        <input
          className="mt-2 w-full rounded-xl border px-3 py-2 text-[15px]"
          type="email"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          placeholder="you@example.com"
        />
      </div>

      <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface-muted)] p-3">
        <label className="text-[10px] uppercase tracking-[0.2em] text-[var(--text-secondary)]">Optional note</label>
        <textarea
          className="mt-2 w-full rounded-xl border px-3 py-2 text-[15px]"
          rows={3}
          value={reason}
          onChange={(event) => setReason(event.target.value)}
          placeholder="Anything support should know before verifying deletion..."
        />
      </div>

      <label className="flex items-start gap-3 rounded-2xl border border-[var(--border)] bg-[var(--surface-muted)] p-3 text-[15px] leading-6">
        <input
          type="checkbox"
          className="mt-1 h-4 w-4"
          checked={confirm}
          onChange={(event) => setConfirm(event.target.checked)}
        />
        <span>
          I understand this starts deletion of my HealthSense account and related coaching, health trend, assessment,
          and message records after identity verification.
        </span>
      </label>

      <div className="flex flex-wrap items-center gap-3">
        <button
          type="submit"
          disabled={submitting}
          className="rounded-full border border-[var(--accent)] bg-[var(--accent)] px-5 py-2 text-[15px] font-semibold text-white disabled:cursor-not-allowed disabled:opacity-60"
        >
          {submitting ? "Sending..." : "Request deletion"}
        </button>
        <a className="text-[15px] text-[var(--accent)] underline" href="/login">
          Sign in
        </a>
      </div>

      {status ? (
        <p className="rounded-2xl border border-[var(--border)] bg-[var(--surface-muted)] px-4 py-3 text-[15px] leading-6">
          {status}
        </p>
      ) : null}
    </form>
  );
}
