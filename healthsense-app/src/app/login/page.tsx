"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { friendlyAuthError } from "@/lib/authErrors";

export default function LoginPage() {
  const router = useRouter();
  const [phone, setPhone] = useState("");
  const [password, setPassword] = useState("");
  const [otpId, setOtpId] = useState<number | null>(null);
  const [code, setCode] = useState("");
  const [status, setStatus] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [setupRequired, setSetupRequired] = useState(false);
  const [rememberMe, setRememberMe] = useState(true);

  useEffect(() => {
    if (typeof window === "undefined") return;
    try {
      const savedOtpId = window.sessionStorage.getItem("hs_login_otp_id");
      const savedPhone = window.sessionStorage.getItem("hs_login_phone");
      const savedSetup = window.sessionStorage.getItem("hs_login_setup");
      if (savedOtpId && savedPhone) {
        setOtpId(Number(savedOtpId));
        setPhone(savedPhone);
        setSetupRequired(savedSetup === "true");
      }
    } catch {}
  }, []);

  const requestOtp = async (event: React.FormEvent | null, channel: "auto" | "whatsapp" | "sms" = "auto") => {
    if (event) event.preventDefault();
    setLoading(true);
    setStatus(null);
    try {
      const res = await fetch("/api/auth/login/request", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ phone, password: password || undefined, channel }),
      });
      if (!res.ok) {
        const text = await res.text().catch(() => "");
        throw new Error(text || "Failed to request code.");
      }
      const data = await res.json();
      setOtpId(Number(data.otp_id));
      setSetupRequired(Boolean(data.setup_required));
      const channelUsed = data.channel || channel;
      setStatus(channelUsed === "sms" ? "We sent a login code by SMS." : "We sent a login code to your WhatsApp.");
      if (typeof window !== "undefined") {
        try {
          window.sessionStorage.setItem("hs_login_otp_id", String(data.otp_id));
          window.sessionStorage.setItem("hs_login_phone", phone);
          window.sessionStorage.setItem("hs_login_setup", String(Boolean(data.setup_required)));
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
        throw new Error(text || "Failed to verify code.");
      }
      const data = await res.json();
      const userId = data.user_id || "1";
      const token = data.session_token;
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
          window.sessionStorage.removeItem("hs_login_otp_id");
          window.sessionStorage.removeItem("hs_login_phone");
          window.sessionStorage.removeItem("hs_login_setup");
        } catch {}
      }
      if (data.setup_required) {
        window.location.href = "/setup-security";
      } else {
        window.location.href = `/progress/${userId}`;
      }
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
          <img src="/healthsense-logo.svg" alt="HealthSense" className="h-8 w-auto" />
          <h1 className="mt-4 text-3xl">Sign in</h1>
          <p className="mt-2 text-sm text-[#6b6257]">Enter your phone number. We’ll send a code via WhatsApp or SMS.</p>
        </div>

        {!otpId ? (
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
              <div className="mt-2 text-right">
                <a className="text-xs text-[var(--accent)] underline" href="/reset-password">
                  Forgot password?
                </a>
              </div>
            </div>
            <button
              className="w-full rounded-full border border-[var(--accent)] bg-[var(--accent)] px-5 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-60"
              type="submit"
              disabled={loading}
            >
              {loading ? "Sending…" : "Send login code"}
            </button>
            <label className="flex items-center gap-2 text-sm text-[#6b6257]">
              <input
                type="checkbox"
                checked={rememberMe}
                onChange={(e) => setRememberMe(e.target.checked)}
              />
              Remember me for 30 days
            </label>
          </form>
        ) : (
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
            {setupRequired ? (
              <p className="text-sm text-[#6b6257]">First time login — you’ll be prompted to set your security after this step.</p>
            ) : null}
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
                setSetupRequired(false);
                if (typeof window !== "undefined") {
                  try {
                    window.sessionStorage.removeItem("hs_login_otp_id");
                    window.sessionStorage.removeItem("hs_login_phone");
                    window.sessionStorage.removeItem("hs_login_setup");
                  } catch {}
                }
              }}
            >
              Use a different number
            </button>
          </form>
        )}

        {status ? <p className="text-sm text-[#6b6257]">{status}</p> : null}
      </div>
    </main>
  );
}
