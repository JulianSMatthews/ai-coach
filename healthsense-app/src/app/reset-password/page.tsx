"use client";

import { useEffect, useState } from "react";
import { friendlyAuthError } from "@/lib/authErrors";
import HealthSenseMark from "@/components/HealthSenseMark";
import LegalFooter from "@/components/LegalFooter";

function looksLikePhone(value: string) {
  const trimmed = value.trim();
  const digits = trimmed.replace(/[^\d]/g, "");
  return trimmed.startsWith("+") && digits.length >= 8;
}

export default function ResetPasswordPage() {
  const [phone, setPhone] = useState("");
  const [otpId, setOtpId] = useState<number | null>(null);
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [status, setStatus] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [rememberMe, setRememberMe] = useState(true);

  const clearStoredResetState = () => {
    if (typeof window === "undefined") return;
    try {
      window.sessionStorage.removeItem("hs_reset_otp_id");
      window.sessionStorage.removeItem("hs_reset_phone");
    } catch {}
  };

  const resetOtpState = () => {
    setOtpId(null);
    setCode("");
    setPassword("");
    setConfirmPassword("");
    clearStoredResetState();
  };

  useEffect(() => {
    if (typeof window === "undefined") return;
    try {
      const savedOtpId = window.sessionStorage.getItem("hs_reset_otp_id");
      const savedPhone = window.sessionStorage.getItem("hs_reset_phone");
      if (savedPhone) setPhone(savedPhone);
      if (savedOtpId && savedPhone) {
        setOtpId(Number(savedOtpId));
      }
    } catch {}
  }, []);

  const requestReset = async (event: React.FormEvent | null, channel: "auto" | "whatsapp" | "sms" = "auto") => {
    if (event) event.preventDefault();
    if (!phone.trim()) {
      setStatus("Please enter your phone number to continue.");
      return;
    }
    if (!looksLikePhone(phone)) {
      setStatus("Enter a valid mobile number, ideally with country code.");
      return;
    }
    setLoading(true);
    setStatus(null);
    try {
      const res = await fetch("/api/auth/password/reset/request", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ phone, channel }),
      });
      if (!res.ok) {
        const fallback = `Failed to request code (HTTP ${res.status}).`;
        const contentType = (res.headers.get("content-type") || "").toLowerCase();
        if (contentType.includes("application/json")) {
          const payload = (await res.json().catch(() => null)) as
            | { error?: string; detail?: string; message?: string }
            | null;
          throw new Error(payload?.error || payload?.detail || payload?.message || fallback);
        }
        const text = await res.text().catch(() => "");
        throw new Error((text || "").trim() || fallback);
      }
      const data = await res.json();
      setOtpId(Number(data.otp_id));
      const channelUsed = data.channel || channel;
      setStatus(channelUsed === "sms" ? "We sent a reset code by SMS." : "We sent a reset code to your WhatsApp.");
      if (typeof window !== "undefined") {
        try {
          window.sessionStorage.setItem("hs_reset_otp_id", String(data.otp_id));
          window.sessionStorage.setItem("hs_reset_phone", phone);
        } catch {}
      }
    } catch (error) {
      setStatus(friendlyAuthError(error));
    } finally {
      setLoading(false);
    }
  };

  const verifyReset = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!otpId) return;
    if (!password || password.length < 8) {
      setStatus("Password must be at least 8 characters.");
      return;
    }
    if (password !== confirmPassword) {
      setStatus("Passwords do not match.");
      return;
    }
    setLoading(true);
    setStatus(null);
    try {
      const res = await fetch("/api/auth/password/reset/verify", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ phone, otp_id: otpId, code, password, remember_me: rememberMe }),
      });
      if (!res.ok) {
        const fallback = `Failed to reset password (HTTP ${res.status}).`;
        const contentType = (res.headers.get("content-type") || "").toLowerCase();
        if (contentType.includes("application/json")) {
          const payload = (await res.json().catch(() => null)) as
            | { error?: string; detail?: string; message?: string }
            | null;
          throw new Error(payload?.error || payload?.detail || payload?.message || fallback);
        }
        const text = await res.text().catch(() => "");
        throw new Error((text || "").trim() || fallback);
      }
      const data = await res.json();
      const userId = data.user_id || "1";
      const token = data.session_token;
      if (token && typeof document !== "undefined") {
        const rememberDays = Number(data.remember_days || 7);
        const maxAge = rememberDays * 24 * 60 * 60;
        document.cookie = `hs_session=${token}; path=/; max-age=${maxAge}`;
        document.cookie = `hs_user_id=${userId}; path=/; max-age=${maxAge}`;
        try {
          window.localStorage.setItem("hs_session_local", token);
          window.localStorage.setItem("hs_user_id_local", String(userId));
        } catch {}
      }
      clearStoredResetState();
      window.location.href = `/assessment/${userId}/chat`;
    } catch (error) {
      setStatus(friendlyAuthError(error));
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="min-h-screen bg-white px-6 py-10 text-[#1e1b16]">
      <div className="mx-auto flex w-full max-w-md flex-col gap-6 rounded-3xl border border-[#e7e1d6] bg-white p-8 shadow-[0_30px_80px_-60px_rgba(30,27,22,0.5)]">
        <div>
          <div className="flex items-center">
            <HealthSenseMark className="h-10 w-7" />
          </div>
          <h1 className="mt-4 text-3xl">Reset password</h1>
          <p className="mt-2 text-sm text-[#6b6257]">
            Enter your mobile number. We&apos;ll send a reset code by WhatsApp or SMS.
          </p>
        </div>

        {!otpId ? (
          <form onSubmit={(e) => requestReset(e, "auto")} className="space-y-4" autoComplete="off">
            <div>
              <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Mobile number</label>
              <input
                className="mt-2 w-full rounded-xl border border-[#efe7db] bg-white px-3 py-2 text-sm"
                type="text"
                autoComplete="tel"
                inputMode="tel"
                value={phone}
                onChange={(e) => setPhone(e.target.value)}
                placeholder="+44 7700 900000"
              />
            </div>
            <button
              className="w-full rounded-full border border-[var(--accent)] bg-[var(--accent)] px-5 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-60"
              type="submit"
              disabled={loading}
            >
              {loading ? "Sending…" : "Send reset code"}
            </button>
            <button
              type="button"
              className="w-full rounded-full border border-[#efe7db] px-5 py-2 text-sm"
              onClick={() => requestReset(null, "sms")}
              disabled={loading}
            >
              {loading ? "Sending…" : "Send via SMS"}
            </button>
          </form>
        ) : (
          <form onSubmit={verifyReset} className="space-y-4" autoComplete="off">
            <div>
              <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Reset code</label>
              <input
                className="mt-2 w-full rounded-xl border border-[#efe7db] bg-white px-3 py-2 text-sm tracking-[0.3em]"
                inputMode="numeric"
                pattern="[0-9]*"
                autoComplete="one-time-code"
                value={code}
                onChange={(e) => setCode(e.target.value)}
                placeholder="123456"
              />
            </div>
            <p className="text-sm text-[#6b6257]">Use the code sent to your mobile number.</p>
            <div>
              <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">New password</label>
              <input
                className="mt-2 w-full rounded-xl border border-[#efe7db] bg-white px-3 py-2 text-sm"
                type="password"
                autoComplete="new-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="At least 8 characters"
              />
            </div>
            <div>
              <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Confirm password</label>
              <input
                className="mt-2 w-full rounded-xl border border-[#efe7db] bg-white px-3 py-2 text-sm"
                type="password"
                autoComplete="new-password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                placeholder="Re-enter password"
              />
            </div>
            <button
              className="w-full rounded-full border border-[var(--accent)] bg-[var(--accent)] px-5 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-60"
              type="submit"
              disabled={loading}
            >
              {loading ? "Saving…" : "Save new password"}
            </button>
            <label className="flex items-center gap-2 text-sm text-[#6b6257]">
              <input
                type="checkbox"
                checked={rememberMe}
                onChange={(e) => setRememberMe(e.target.checked)}
              />
              Keep me signed in
            </label>
            <button
              type="button"
              className="w-full rounded-full border border-[#efe7db] px-5 py-2 text-sm"
              onClick={() => requestReset(null, "whatsapp")}
              disabled={loading}
            >
              {loading ? "Sending…" : "Resend via WhatsApp"}
            </button>
            <button
              type="button"
              className="w-full rounded-full border border-[#efe7db] px-5 py-2 text-sm"
              onClick={() => requestReset(null, "sms")}
              disabled={loading}
            >
              {loading ? "Sending…" : "Send via SMS"}
            </button>
            <button
              type="button"
              className="w-full rounded-full border border-[#efe7db] px-5 py-2 text-sm"
              onClick={resetOtpState}
            >
              Use a different number
            </button>
          </form>
        )}

        {status ? <p className="text-sm text-[#6b6257]">{status}</p> : null}
        <a className="text-center text-sm text-[var(--accent)] underline" href="/login">
          Back to sign in
        </a>
      </div>
      <LegalFooter className="mx-auto mt-6 max-w-md text-[#6b6257]" />
    </main>
  );
}
