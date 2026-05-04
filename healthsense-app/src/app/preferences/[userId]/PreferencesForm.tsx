"use client";

import { useState } from "react";
import { applyThemePreference, normalizeThemePreference } from "@/lib/theme";

type PreferencesFormProps = {
  userId: string;
  initialEmail?: string;
  initialTheme?: string;
};

export default function PreferencesForm({
  userId,
  initialEmail = "",
  initialTheme = "dark",
}: PreferencesFormProps) {
  const [email, setEmail] = useState(initialEmail || "");
  const [theme, setTheme] = useState(() => {
    const normalized = normalizeThemePreference(initialTheme);
    return normalized === "light" ? "light" : "dark";
  });
  const [changePassword, setChangePassword] = useState(false);
  const [password, setPassword] = useState("");
  const [passwordConfirm, setPasswordConfirm] = useState("");
  const [status, setStatus] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const onSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSaving(true);
    setStatus(null);
    try {
      if (changePassword) {
        if (password.length < 8) {
          throw new Error("Password must be at least 8 characters.");
        }
        if (password !== passwordConfirm) {
          throw new Error("Passwords do not match.");
        }
      }
      const payload: Record<string, unknown> = {
        userId,
        email: email.trim(),
        theme,
        preferred_channel: "app",
      };
      if (changePassword) {
        payload.password = password;
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
      if (changePassword) {
        setPassword("");
        setPasswordConfirm("");
        setChangePassword(false);
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
      <section className="rounded-2xl border border-[#efe7db] bg-[#fdfaf4] p-4">
        <h3 className="text-base font-semibold text-[#1e1b16]">Preferences</h3>
        <div className="mt-4 grid gap-4">
          <div className="rounded-2xl border border-[#efe7db] bg-white p-4">
            <label className="text-[11px] uppercase tracking-[0.18em] text-[#6b6257]">Theme</label>
            <select
              className="mt-2 w-full rounded-xl border border-[#efe7db] bg-white px-3 py-2 text-[13px]"
              value={theme}
              onChange={(e) => setTheme(e.target.value === "light" ? "light" : "dark")}
            >
              <option value="dark">Dark</option>
              <option value="light">Light</option>
            </select>
          </div>
        </div>
      </section>

      <section className="rounded-2xl border border-[#efe7db] bg-[#fdfaf4] p-4">
        <h3 className="text-base font-semibold text-[#1e1b16]">Account</h3>
        <div className="mt-4 grid gap-4">
          <div className="rounded-2xl border border-[#efe7db] bg-white p-4">
            <label className="text-[11px] uppercase tracking-[0.18em] text-[#6b6257]">Email</label>
            <input
              className="mt-2 w-full rounded-xl border border-[#efe7db] bg-white px-3 py-2 text-[13px]"
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
            <p className="mt-2 text-[11px] text-[#6b6257]">Optional, used for account recovery and important updates.</p>
          </div>
          <div className="rounded-2xl border border-[#efe7db] bg-white p-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <label className="text-[11px] uppercase tracking-[0.18em] text-[#6b6257]">Password</label>
              <label className="flex items-center gap-2 text-[11px] text-[#6b6257]">
                <input
                  type="checkbox"
                  className="h-4 w-4 rounded border-[#efe7db]"
                  checked={changePassword}
                  onChange={(e) => {
                    const next = e.target.checked;
                    setChangePassword(next);
                    if (!next) {
                      setPassword("");
                      setPasswordConfirm("");
                    }
                  }}
                />
                Change password
              </label>
            </div>
            <input
              className="mt-2 w-full rounded-xl border border-[#efe7db] bg-white px-3 py-2 text-[13px] disabled:opacity-60"
              type="password"
              name="new_password"
              autoComplete="new-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Set a password for login"
              disabled={!changePassword}
            />
            <input
              className="mt-3 w-full rounded-xl border border-[#efe7db] bg-white px-3 py-2 text-[13px] disabled:opacity-60"
              type="password"
              name="confirm_new_password"
              autoComplete="new-password"
              value={passwordConfirm}
              onChange={(e) => setPasswordConfirm(e.target.value)}
              placeholder="Confirm password"
              disabled={!changePassword}
            />
            <p className="mt-2 text-[11px] text-[#6b6257]">Minimum 8 characters.</p>
          </div>
        </div>
      </section>

      <div className="flex flex-wrap items-center gap-3">
        <button
          type="submit"
          className="rounded-full border border-[var(--accent)] bg-[var(--accent)] px-5 py-2 text-[13px] font-semibold text-white disabled:cursor-not-allowed disabled:opacity-60"
          disabled={saving}
        >
          {saving ? "Saving…" : "Save changes"}
        </button>
        {status ? <p className="text-[13px] text-[#6b6257]">{status}</p> : null}
      </div>
    </form>
  );
}
