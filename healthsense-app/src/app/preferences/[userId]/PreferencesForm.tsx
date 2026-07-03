"use client";

import { useState } from "react";
import { applyThemePreference, normalizeThemePreference, readStoredThemePreference } from "@/lib/theme";
import { PILLARS } from "@/lib/pillars";

type PreferencesFormProps = {
  userId: string;
  initialEmail?: string;
  initialTheme?: string;
  initialPillarSelections?: Record<string, boolean>;
};

const PREFERENCE_PILLAR_ORDER = ["reflection", "purpose", "resilience", "recovery"];
const HIDDEN_PILLAR_ORDER = ["nutrition", "training"];
const PREFERENCE_PILLARS = PREFERENCE_PILLAR_ORDER.map((key) => PILLARS.find((pillar) => pillar.key === key)).filter(
  Boolean,
) as typeof PILLARS;

const PILLAR_PREF_KEYS: Record<string, string> = {
  reflection: "home_pillar_reflection",
  purpose: "home_pillar_purpose",
  resilience: "home_pillar_resilience",
  recovery: "home_pillar_recovery",
  nutrition: "home_pillar_nutrition",
  training: "home_pillar_training",
};

export default function PreferencesForm({
  userId,
  initialEmail = "",
  initialTheme = "dark",
  initialPillarSelections = {},
}: PreferencesFormProps) {
  const [email, setEmail] = useState(initialEmail || "");
  const [theme, setTheme] = useState(() => {
    const stored = readStoredThemePreference();
    const normalized = normalizeThemePreference(stored || initialTheme);
    return normalized;
  });
  const [pillarSelections, setPillarSelections] = useState<Record<string, boolean>>(() =>
    Object.fromEntries(PREFERENCE_PILLARS.map((pillar) => [pillar.key, Boolean(initialPillarSelections[pillar.key])])),
  );
  const [status, setStatus] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const onSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSaving(true);
    setStatus(null);
    try {
      const payload: Record<string, unknown> = {
        userId,
        email: email.trim(),
        theme,
        preferred_channel: "app",
      };
      for (const pillar of PREFERENCE_PILLARS) {
        const prefKey = PILLAR_PREF_KEYS[pillar.key];
        payload[prefKey] = pillarSelections[pillar.key] ? "1" : "0";
      }
      for (const pillarKey of HIDDEN_PILLAR_ORDER) {
        payload[PILLAR_PREF_KEYS[pillarKey]] = "0";
      }
      const res = await fetch("/api/preferences", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        const text = await res.text().catch(() => "");
        throw new Error(text || "Failed to update preferences");
      }
      setStatus("Saved");
      if (typeof window !== "undefined") {
        applyThemePreference(theme, true);
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setStatus(message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <form onSubmit={onSubmit} className="space-y-6" autoComplete="off">
      <section className="rounded-[28px] border border-[var(--border)] bg-[var(--surface-muted)] p-5">
        <h3 className="text-xl font-semibold text-[var(--text-primary)]">Preferences</h3>
        <div className="mt-4 grid gap-4">
          <div className="rounded-[24px] border border-[var(--border)] bg-[var(--surface)] p-4">
            <label className="text-sm font-semibold uppercase tracking-[0.18em] text-[var(--text-secondary)]">Theme</label>
            <select
              className="mt-2 w-full rounded-2xl border border-[var(--border)] bg-[var(--surface)] px-4 py-3 text-base"
              value={theme}
              onChange={(e) => setTheme(normalizeThemePreference(e.target.value))}
            >
              <option value="auto">Auto</option>
              <option value="dark">Dark</option>
              <option value="light">Light</option>
              <option value="system">System</option>
            </select>
          </div>
        </div>
      </section>

      <section className="rounded-[28px] border border-[var(--border)] bg-[var(--surface-muted)] p-5">
        <h3 className="text-xl font-semibold text-[var(--text-primary)]">Choose your pillars</h3>
        <div className="mt-5 grid gap-3">
          {PREFERENCE_PILLARS.map((pillar) => {
            const selected = Boolean(pillarSelections[pillar.key]);
            return (
              <button
                key={pillar.key}
                type="button"
                onClick={() =>
                  setPillarSelections((current) => ({
                    ...current,
                    [pillar.key]: !current[pillar.key],
                  }))
                }
                aria-pressed={selected}
                className="flex min-h-[5.75rem] w-full items-center gap-3 rounded-[28px] border border-[var(--border)] bg-[var(--surface)] px-4 py-4 text-left text-[var(--text-primary)] transition"
              >
                <span className="min-w-0 flex-1">
                  <span className="block text-lg font-semibold leading-6">{pillar.label}</span>
                  <span className="mt-1 block text-sm leading-6 text-[var(--text-secondary)]">
                    {pillar.note}
                  </span>
                </span>
                <span
                  className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-lg border ${
                    selected ? "border-[#111111] bg-white text-[#111111]" : "border-[var(--border)] bg-[var(--surface)]"
                  }`}
                  aria-hidden="true"
                >
                  {selected ? (
                    <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M5 12.5 10 17l9-10" />
                    </svg>
                  ) : null}
                </span>
              </button>
            );
          })}
        </div>
      </section>

      <section className="rounded-[28px] border border-[var(--border)] bg-[var(--surface-muted)] p-5">
        <h3 className="text-xl font-semibold text-[var(--text-primary)]">Account</h3>
        <div className="mt-4 grid gap-4">
          <div className="rounded-[24px] border border-[var(--border)] bg-[var(--surface)] p-4">
            <label className="text-sm font-semibold uppercase tracking-[0.18em] text-[var(--text-secondary)]">Email</label>
            <input
              className="mt-2 w-full rounded-2xl border border-[var(--border)] bg-[var(--surface)] px-4 py-3 text-base"
              type="email"
              name="contact_email"
              autoComplete="section-profile email"
              inputMode="email"
              autoCapitalize="none"
              autoCorrect="off"
              spellCheck={false}
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@example.com"
            />
            <p className="mt-2 text-sm leading-6 text-[var(--text-secondary)]">Optional, used for account recovery and important updates.</p>
          </div>
        </div>
      </section>

      <div className="flex flex-wrap items-center gap-3">
        <button
          type="submit"
          className="w-full rounded-full border border-[var(--action-primary-border)] bg-[var(--action-primary-bg)] px-5 py-4 text-base font-semibold text-[var(--action-primary-text)] disabled:cursor-not-allowed disabled:opacity-60"
          disabled={saving}
        >
          {saving ? "Saving…" : "Save changes"}
        </button>
        {status ? <p className="text-[13px] text-[var(--text-secondary)]">{status}</p> : null}
      </div>
    </form>
  );
}
