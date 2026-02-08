"use client";

import { useEffect, useState } from "react";
import { friendlyAuthError } from "@/lib/authErrors";

export default function LoginPage() {
  const [phone, setPhone] = useState("");
  const [password, setPassword] = useState("");
  const [otpId, setOtpId] = useState<number | null>(null);
  const [code, setCode] = useState("");
  const [status, setStatus] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [rememberMe, setRememberMe] = useState(true);
  const [passwordRequired, setPasswordRequired] = useState(false);
  const [setupRequired, setSetupRequired] = useState(false);
  const [verificationComplete, setVerificationComplete] = useState(false);
  const [setupUserId, setSetupUserId] = useState<string | null>(null);
  const [confirmPassword, setConfirmPassword] = useState("");

  const normalizeUserId = (value: unknown) => {
    const num = typeof value === "number" ? value : Number(value);
    if (!Number.isFinite(num) || num <= 0) return null;
    return String(Math.trunc(num));
  };

  useEffect(() => {
    if (typeof window === "undefined") return;
    try {
      const savedOtpId = window.sessionStorage.getItem("hs_admin_login_otp_id");
      const savedPhone = window.sessionStorage.getItem("hs_admin_login_phone");
      const savedSetupUserId = window.sessionStorage.getItem("hs_admin_setup_user_id");
      if (savedOtpId && savedPhone) {
        setOtpId(Number(savedOtpId));
        setPhone(savedPhone);
      }
      if (savedSetupUserId) {
        setSetupUserId(savedSetupUserId);
      }
    } catch {}
  }, []);

  const requestOtp = async (event: React.FormEvent | null, channel: "auto" | "whatsapp" | "sms" = "auto") => {
    if (event) event.preventDefault();
    setLoading(true);
    setStatus(null);
    setPasswordRequired(false);
    try {
      const res = await fetch("/api/auth/login/request", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ phone, password: password || undefined, channel }),
      });
      if (!res.ok) {
        const text = await res.text().catch(() => "");
        if (res.status === 401) {
          setPasswordRequired(true);
          setStatus(password ? "That password didn’t match. Try again." : "Password required for this account.");
          return;
        }
        setStatus(friendlyAuthError(text || "Failed to request code."));
        return;
      }
      const data = await res.json();
      setOtpId(Number(data.otp_id));
      setSetupRequired(Boolean(data.setup_required));
      const channelUsed = data.channel || channel;
      setStatus(channelUsed === "sms" ? "We sent a login code by SMS." : "We sent a login code to your WhatsApp.");
      if (typeof window !== "undefined") {
        try {
          window.sessionStorage.setItem("hs_admin_login_otp_id", String(data.otp_id));
          window.sessionStorage.setItem("hs_admin_login_phone", phone);
        } catch {}
      }
    } catch (error) {
      setStatus(friendlyAuthError(error));
    } finally {
      setLoading(false);
    }
  };

  const verifyOtp = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!otpId) return;
    setLoading(true);
    setStatus(null);
    try {
      const res = await fetch("/api/auth/login/verify", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ phone, otp_id: otpId, code, remember_me: rememberMe }),
      });
      if (!res.ok) {
        const text = await res.text().catch(() => "");
        setStatus(friendlyAuthError(text || "Failed to verify code."));
        return;
      }
      const data = await res.json();
      const userId = normalizeUserId(data.user_id ?? data.user?.id) || "1";
      const token = data.session_token;
      const needsSetup = Boolean(data.setup_required);
      if (token && typeof document !== "undefined") {
        const maxAge = rememberMe ? 60 * 60 * 24 * 30 : 60 * 60 * 24 * 7;
        document.cookie = `hs_session=${token}; path=/; max-age=${maxAge}`;
        document.cookie = `hs_user_id=${userId}; path=/; max-age=${maxAge}`;
        try {
          window.localStorage.setItem("hs_session_local", token);
          window.localStorage.setItem("hs_user_id_local", String(userId));
        } catch {}
      }
      if (typeof window !== "undefined") {
        try {
          window.sessionStorage.removeItem("hs_admin_login_otp_id");
          window.sessionStorage.removeItem("hs_admin_login_phone");
        } catch {}
      }
      if (needsSetup) {
        setSetupRequired(true);
        setSetupUserId(String(userId));
        setStatus("Login verified. Please set a password below to secure your account.");
        setVerificationComplete(true);
        if (typeof window !== "undefined") {
          try {
            window.sessionStorage.setItem("hs_admin_setup_user_id", String(userId));
          } catch {}
        }
      } else {
        window.location.href = "/admin";
      }
    } catch (error) {
      setStatus(friendlyAuthError(error));
    } finally {
      setLoading(false);
    }
  };

  const savePassword = async (event: React.FormEvent) => {
    event.preventDefault();
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
      let userId = normalizeUserId(setupUserId);
      if (typeof window !== "undefined") {
        try {
          userId = userId || normalizeUserId(window.sessionStorage.getItem("hs_admin_setup_user_id"));
        } catch {}
        try {
          userId = userId || normalizeUserId(window.localStorage.getItem("hs_user_id_local"));
        } catch {}
        if (!userId) {
          const match = document.cookie.match(/(?:^|; )hs_user_id=([^;]+)/);
          userId = match ? normalizeUserId(match[1]) : null;
        }
      }
      if (!userId) {
        const res = await fetch("/api/auth/me");
        if (res.ok) {
          const profile = await res.json();
          const fetchedId = normalizeUserId(profile?.user?.id);
          if (fetchedId) {
            userId = fetchedId;
            if (typeof window !== "undefined") {
              try {
                window.sessionStorage.setItem("hs_admin_setup_user_id", userId);
              } catch {}
            }
          }
        }
      }
      if (!userId) {
        throw new Error("userId is required");
      }
      const save = await fetch(`/api/users/${userId}/preferences`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password }),
      });
      if (!save.ok) {
        const text = await save.text().catch(() => "");
        throw new Error(text || "Failed to set password.");
      }
      window.location.href = "/admin";
    } catch (error) {
      setStatus(friendlyAuthError(error));
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="min-h-screen bg-[radial-gradient(circle_at_top,_#e9fff9,_#f7f4ee_55%,_#f4efe6)] px-6 py-10 text-[#1e1b16]">
      <div className="mx-auto flex w-full max-w-md flex-col gap-6 rounded-3xl border border-[#e7e1d6] bg-white p-8 shadow-[0_30px_80px_-60px_rgba(30,27,22,0.5)]">
        <div>
          <div className="flex items-center gap-3">
            <img src="/healthsense-logo.svg" alt="HealthSense" className="h-10 w-auto" />
            <span className="text-xs uppercase tracking-[0.3em] text-[#6b6257]">Admin</span>
          </div>
          <h1 className="mt-4 text-3xl">Sign in</h1>
          <p className="mt-2 text-sm text-[#6b6257]">Enter your phone number. We’ll send a code via WhatsApp or SMS.</p>
        </div>

        {!otpId && !verificationComplete ? (
          <form onSubmit={(e) => requestOtp(e, "auto")} className="space-y-4" autoComplete="off">
            <div>
              <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Phone number</label>
              <input
                className="mt-2 w-full rounded-xl border border-[#efe7db] bg-white px-3 py-2 text-sm"
                autoComplete="tel"
                inputMode="tel"
                value={phone}
                onChange={(e) => setPhone(e.target.value)}
                placeholder="+44 7700 900000"
              />
            </div>
            <div>
              <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Password</label>
              <input
                className="mt-2 w-full rounded-xl border border-[#efe7db] bg-white px-3 py-2 text-sm"
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="Leave blank if first time"
              />
              <p className="mt-2 text-xs text-[#6b6257]">
                {passwordRequired
                  ? "Password required for this account."
                  : "If you already set a password, enter it here."}
              </p>
            </div>
            <button
              className="w-full rounded-full border border-[var(--accent)] bg-[var(--accent)] px-5 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-60"
              type="submit"
              disabled={loading}
            >
              {loading ? "Sending…" : "Send login code"}
            </button>
            <label className="flex items-center gap-2 text-sm text-[#6b6257]">
              <input type="checkbox" checked={rememberMe} onChange={(e) => setRememberMe(e.target.checked)} />
              Remember me for 30 days
            </label>
          </form>
        ) : null}

        {otpId && !verificationComplete ? (
          <form onSubmit={verifyOtp} className="space-y-4" autoComplete="off">
            <div>
              <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">WhatsApp code</label>
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
            <button
              className="w-full rounded-full border border-[var(--accent)] bg-[var(--accent)] px-5 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-60"
              type="submit"
              disabled={loading}
            >
              {loading ? "Verifying…" : "Verify & continue"}
            </button>
            <button
              type="button"
              className="w-full rounded-full border border-[#efe7db] px-5 py-2 text-sm"
              onClick={() => requestOtp(null, "whatsapp")}
              disabled={loading}
            >
              {loading ? "Sending…" : "Resend via WhatsApp"}
            </button>
            <button
              type="button"
              className="w-full rounded-full border border-[#efe7db] px-5 py-2 text-sm"
              onClick={() => requestOtp(null, "sms")}
              disabled={loading}
            >
              {loading ? "Sending…" : "Send via SMS"}
            </button>
            <button
              type="button"
              className="w-full rounded-full border border-[#efe7db] px-5 py-2 text-sm"
              onClick={() => {
                setOtpId(null);
                setCode("");
                setVerificationComplete(false);
                setSetupRequired(false);
                setSetupUserId(null);
                setPassword("");
                setConfirmPassword("");
                if (typeof window !== "undefined") {
                  try {
                    window.sessionStorage.removeItem("hs_admin_login_otp_id");
                    window.sessionStorage.removeItem("hs_admin_login_phone");
                    window.sessionStorage.removeItem("hs_admin_setup_user_id");
                  } catch {}
                }
              }}
            >
              Use a different number
            </button>
          </form>
        ) : null}

        {setupRequired && verificationComplete ? (
          <form onSubmit={savePassword} className="space-y-4">
            <div>
              <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Set password</label>
              <input
                className="mt-2 w-full rounded-xl border border-[#efe7db] bg-white px-3 py-2 text-sm"
                type="password"
                autoComplete="new-password"
                minLength={8}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="Minimum 8 characters"
              />
              <p className="mt-2 text-xs text-[#6b6257]">Minimum 8 characters.</p>
              <input
                className="mt-2 w-full rounded-xl border border-[#efe7db] bg-white px-3 py-2 text-sm"
                type="password"
                autoComplete="new-password"
                minLength={8}
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                placeholder="Confirm password"
              />
            </div>
            <button
              type="submit"
              className="w-full rounded-full border border-[var(--accent)] bg-[var(--accent)] px-5 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-60"
              disabled={loading}
            >
              {loading ? "Saving…" : "Save password & continue"}
            </button>
          </form>
        ) : null}

        {status ? <p className="text-sm text-[#6b6257]">{status}</p> : null}
      </div>
    </main>
  );
}
