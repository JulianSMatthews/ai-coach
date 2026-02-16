"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { friendlyAuthError } from "@/lib/authErrors";

type MeResponse = {
  user?: { id?: number; display_name?: string; phone?: string; email?: string };
};

export default function SetupSecurityPage() {
  const router = useRouter();
  const [user, setUser] = useState<MeResponse["user"] | null>(null);
  const [userId, setUserId] = useState<number | null>(null);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [preferredChannel, setPreferredChannel] = useState("whatsapp");
  const [marketingOptIn, setMarketingOptIn] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    fetch("/api/auth/me")
      .then((res) => (res.ok ? res.json() : Promise.reject()))
      .then((data: MeResponse) => {
        const me = data.user || null;
        setUser(me);
        if (me?.id) setUserId(me.id);
        if (me?.email) setEmail(me.email);
      })
      .catch(() => {
        const cookieMatch = typeof document !== "undefined" ? document.cookie.match(/hs_user_id=([^;]+)/) : null;
        if (cookieMatch && cookieMatch[1]) {
          const parsed = Number.parseInt(cookieMatch[1], 10);
          if (!Number.isNaN(parsed)) {
            setUserId(parsed);
            return;
          }
        }
        setStatus("Please log in again.");
      });
  }, []);

  const onSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSaving(true);
    setStatus(null);
    try {
      if (!email.trim()) {
        throw new Error("email is required");
      }
      if (password.length < 8) {
        throw new Error("Password must be at least 8 characters.");
      }
      if (password !== confirm) {
        throw new Error("Passwords do not match.");
      }
      const resolvedUserId = user?.id || userId;
      if (!resolvedUserId) {
        throw new Error("userId is required");
      }
      const res = await fetch("/api/preferences", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          userId: resolvedUserId,
          email,
          password,
          preferred_channel: preferredChannel,
          marketing_opt_in: marketingOptIn ? "1" : "0",
        }),
      });
      if (!res.ok) {
        const text = await res.text().catch(() => "");
        throw new Error(text || "Failed to save password.");
      }
      router.replace(`/progress/${resolvedUserId}`);
    } catch (error) {
      setStatus(friendlyAuthError(error));
    } finally {
      setSaving(false);
    }
  };

  return (
    <main className="min-h-screen bg-white px-6 py-10 text-[#1e1b16]">
      <div className="mx-auto flex w-full max-w-md flex-col gap-6 rounded-3xl border border-[#e7e1d6] bg-white p-8 shadow-[0_30px_80px_-60px_rgba(30,27,22,0.5)]">
        <div>
          <p className="text-xs uppercase tracking-[0.3em] text-[#6b6257]">First time setup</p>
          <h1 className="mt-2 text-3xl">Secure your account</h1>
          <p className="mt-2 text-sm text-[#6b6257]">
            Set a password for {user?.display_name || "your account"}.
          </p>
        </div>
        <form onSubmit={onSubmit} className="space-y-4" autoComplete="off">
          <div>
            <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Email</label>
            <input
              className="mt-2 w-full rounded-xl border border-[#efe7db] bg-white px-3 py-2 text-sm"
              type="email"
              name="contact_email"
              autoComplete="section-security email"
              inputMode="email"
              autoCapitalize="none"
              autoCorrect="off"
              spellCheck={false}
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@example.com"
              required
            />
            <p className="mt-2 text-xs text-[#6b6257]">Required for account recovery and important updates.</p>
          </div>
          <div>
            <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Password</label>
            <input
              className="mt-2 w-full rounded-xl border border-[#efe7db] bg-white px-3 py-2 text-sm"
              type="password"
              name="new_password"
              autoComplete="new-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
            <p className="mt-2 text-xs text-[#6b6257]">Minimum 8 characters.</p>
          </div>
          <div>
            <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Confirm password</label>
            <input
              className="mt-2 w-full rounded-xl border border-[#efe7db] bg-white px-3 py-2 text-sm"
              type="password"
              name="confirm_new_password"
              autoComplete="new-password"
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
            />
          </div>
          <div>
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
          <div className="rounded-xl border border-[#efe7db] bg-[#fffaf0] p-3">
            <label className="flex items-center gap-2 text-sm text-[#3c332b]">
              <input
                type="checkbox"
                checked={marketingOptIn}
                onChange={(e) => setMarketingOptIn(e.target.checked)}
              />
              I’d like product updates and tips (optional)
            </label>
            <p className="mt-2 text-xs text-[#6b6257]">You can unsubscribe anytime by replying STOP.</p>
          </div>
          <button
            className="w-full rounded-full border border-[var(--accent)] bg-[var(--accent)] px-5 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-60"
            type="submit"
            disabled={saving}
          >
            {saving ? "Saving…" : "Save & continue"}
          </button>
        </form>
        {status ? <p className="text-sm text-[#6b6257]">{status}</p> : null}
      </div>
    </main>
  );
}
