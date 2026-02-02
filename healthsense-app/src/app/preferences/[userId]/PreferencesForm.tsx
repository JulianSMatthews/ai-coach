"use client";

import { useState } from "react";

type PreferencesFormProps = {
  userId: string;
  initialEmail?: string;
  initialNote?: string;
  initialVoice?: string;
  initialSchedule?: Record<string, string>;
  initialTextScale?: string;
  initialTrainingObjective?: string;
  initialPreferredChannel?: string;
  initialMarketingOptIn?: string;
};

const DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "sunday"];
const DEFAULT_TIMES: Record<string, string> = {
  sunday: "18:00",
  monday: "08:00",
  tuesday: "19:00",
  wednesday: "08:00",
  thursday: "19:00",
  friday: "08:00",
};

export default function PreferencesForm({
  userId,
  initialEmail = "",
  initialNote = "",
  initialVoice = "",
  initialSchedule = {},
  initialTextScale = "1.0",
  initialTrainingObjective = "",
  initialPreferredChannel = "whatsapp",
  initialMarketingOptIn = "",
}: PreferencesFormProps) {
  const [email, setEmail] = useState(initialEmail || "");
  const [note, setNote] = useState(initialNote);
  const [voice, setVoice] = useState(initialVoice || "");
  const [textScale, setTextScale] = useState(initialTextScale || "1.0");
  const [trainingObjective, setTrainingObjective] = useState(initialTrainingObjective || "");
  const [preferredChannel, setPreferredChannel] = useState(initialPreferredChannel || "whatsapp");
  const [marketingOptIn, setMarketingOptIn] = useState(initialMarketingOptIn === "1");
  const [changePassword, setChangePassword] = useState(false);
  const [password, setPassword] = useState("");
  const [passwordConfirm, setPasswordConfirm] = useState("");
  const [schedule, setSchedule] = useState<Record<string, string>>(() => {
    const next: Record<string, string> = {};
    DAYS.forEach((day) => {
      next[day] = initialSchedule[day] || DEFAULT_TIMES[day] || "";
    });
    return next;
  });
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
      if (!email.trim()) {
        throw new Error("Email is required.");
      }
      const payload: Record<string, unknown> = {
        userId,
        email,
        note,
        voice: voice || "",
        schedule,
        text_scale: textScale,
        training_objective: trainingObjective,
        preferred_channel: preferredChannel,
        marketing_opt_in: marketingOptIn ? "1" : "0",
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
        window.localStorage.setItem("healthsense.textScale", textScale || "1.0");
        document.documentElement.style.setProperty("--text-scale", textScale || "1.0");
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
    <form onSubmit={onSubmit} className="space-y-6">
      <div className="rounded-2xl border border-[#efe7db] bg-white p-4">
        <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Email</label>
        <input
          className="mt-2 w-full rounded-xl border border-[#efe7db] bg-white px-3 py-2 text-sm"
          type="email"
          autoComplete="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="you@example.com"
          required
        />
        <p className="mt-2 text-xs text-[#6b6257]">Required for account recovery and important updates.</p>
      </div>

      <div className="grid gap-4 lg:grid-cols-[1fr_1fr]">
        <div className="rounded-2xl border border-[#efe7db] bg-white p-4">
          <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Voice preference</label>
          <select
            className="mt-2 w-full rounded-xl border border-[#efe7db] bg-white px-3 py-2 text-sm"
            value={voice || ""}
            onChange={(e) => setVoice(e.target.value)}
          >
            <option value="">not set</option>
            <option value="male">male</option>
            <option value="female">female</option>
          </select>
          <p className="mt-2 text-xs text-[#6b6257]">Controls the voice for podcast-style outputs.</p>
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-[1fr_1fr]">
        <div className="rounded-2xl border border-[#efe7db] bg-white p-4">
          <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Preferred channel (general comms)</label>
          <select
            className="mt-2 w-full rounded-xl border border-[#efe7db] bg-white px-3 py-2 text-sm"
            value={preferredChannel}
            onChange={(e) => setPreferredChannel(e.target.value)}
          >
            <option value="whatsapp">WhatsApp</option>
            <option value="sms">SMS</option>
            <option value="email">Email</option>
          </select>
          <p className="mt-2 text-xs text-[#6b6257]">
            Transactional coaching messages still use WhatsApp by default.
          </p>
        </div>
        <div className="rounded-2xl border border-[#efe7db] bg-white p-4">
          <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Marketing updates</label>
          <label className="mt-3 flex items-center gap-2 text-sm text-[#3c332b]">
            <input
              type="checkbox"
              checked={marketingOptIn}
              onChange={(e) => setMarketingOptIn(e.target.checked)}
            />
            I’d like product updates and tips (optional)
          </label>
          <p className="mt-2 text-xs text-[#6b6257]">
            You can unsubscribe anytime by replying STOP.
          </p>
        </div>
      </div>

      <div className="rounded-2xl border border-[#efe7db] bg-white p-4">
        <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Coaching note</label>
        <textarea
          className="mt-2 w-full rounded-xl border border-[#efe7db] bg-white px-3 py-2 text-sm"
          rows={4}
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder="Add context for your coach…"
        />
      </div>

      <div className="rounded-2xl border border-[#efe7db] bg-white p-4">
        <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Training objective</label>
        <textarea
          className="mt-2 w-full rounded-xl border border-[#efe7db] bg-white px-3 py-2 text-sm"
          rows={3}
          value={trainingObjective}
          onChange={(e) => setTrainingObjective(e.target.value)}
          placeholder="Objective from your assessment…"
        />
        <p className="mt-2 text-xs text-[#6b6257]">This comes from your assessment and can be edited.</p>
      </div>

      <div className="rounded-2xl border border-[#efe7db] bg-white p-4">
        <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Text size</label>
        <select
          className="mt-2 w-full rounded-xl border border-[#efe7db] bg-white px-3 py-2 text-sm"
          value={textScale}
          onChange={(e) => setTextScale(e.target.value)}
        >
          <option value="1.0">default</option>
          <option value="1.1">large</option>
          <option value="1.2">extra large</option>
          <option value="1.3">huge</option>
        </select>
        <p className="mt-2 text-xs text-[#6b6257]">Adjusts the overall font size across the dashboard.</p>
      </div>

      <div className="rounded-2xl border border-[#efe7db] bg-white p-4">
        <div className="flex items-center justify-between gap-3">
          <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Password</label>
          <label className="flex items-center gap-2 text-xs text-[#6b6257]">
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
          className="mt-2 w-full rounded-xl border border-[#efe7db] bg-white px-3 py-2 text-sm disabled:opacity-60"
          type="password"
          autoComplete="new-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder="Set a password for login"
          disabled={!changePassword}
        />
        <input
          className="mt-3 w-full rounded-xl border border-[#efe7db] bg-white px-3 py-2 text-sm disabled:opacity-60"
          type="password"
          autoComplete="new-password"
          value={passwordConfirm}
          onChange={(e) => setPasswordConfirm(e.target.value)}
          placeholder="Confirm password"
          disabled={!changePassword}
        />
        <p className="mt-2 text-xs text-[#6b6257]">Minimum 8 characters.</p>
      </div>

      <div className="rounded-2xl border border-[#efe7db] bg-white p-4">
        <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Prompt times (24h)</label>
        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          {DAYS.map((day) => (
            <div key={day} className="flex items-center justify-between gap-3">
              <span className="text-sm text-[#3c332b]">{day}</span>
              <input
                type="time"
                className="w-28 rounded-lg border border-[#efe7db] px-2 py-1 text-sm"
                value={schedule[day] || ""}
                onChange={(e) => setSchedule((prev) => ({ ...prev, [day]: e.target.value }))}
              />
            </div>
          ))}
        </div>
      </div>

      <div className="flex items-center gap-3">
        <button
          type="submit"
          className="rounded-full border border-[var(--accent)] bg-[var(--accent)] px-5 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-60"
          disabled={saving}
        >
          {saving ? "Saving…" : "Save changes"}
        </button>
        {status ? <p className="text-sm text-[#6b6257]">{status}</p> : null}
      </div>
    </form>
  );
}
