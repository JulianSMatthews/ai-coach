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

export default function LoginPage() {
  const [phone, setPhone] = useState("");
  const [password, setPassword] = useState("");
  const [otpId, setOtpId] = useState<number | null>(null);
  const [code, setCode] = useState("");
  const [status, setStatus] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [setupRequired, setSetupRequired] = useState(false);
  const [rememberMe, setRememberMe] = useState(true);
  const [restoringSession, setRestoringSession] = useState(false);

  const clearStoredLoginState = () => {
    if (typeof window === "undefined") return;
    try {
      window.sessionStorage.removeItem("hs_login_otp_id");
      window.sessionStorage.removeItem("hs_login_phone");
      window.sessionStorage.removeItem("hs_login_setup");
    } catch {}
  };

  const resetOtpState = () => {
    setOtpId(null);
    setCode("");
    setSetupRequired(false);
    clearStoredLoginState();
  };

  useEffect(() => {
    if (typeof window === "undefined") return;
    try {
      const savedOtpId = window.sessionStorage.getItem("hs_login_otp_id");
      const savedPhone = window.sessionStorage.getItem("hs_login_phone");
      const savedSetup = window.sessionStorage.getItem("hs_login_setup");
      if (savedPhone) setPhone(savedPhone);
      if (savedOtpId && savedPhone) {
        setOtpId(Number(savedOtpId));
        setSetupRequired(savedSetup === "true");
      }
    } catch {}
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") return;
    let cancelled = false;

    const requestedNext = String(new URLSearchParams(window.location.search).get("next") || "").trim();
    const safeNext =
      requestedNext && requestedNext.startsWith("/") && !requestedNext.startsWith("//") && !requestedNext.startsWith("/api")
        ? requestedNext
        : "";

    const redirectToApp = (userId?: string | number | null) => {
      const resolvedUserId =
        String(
          userId ||
            document.cookie
              .split("; ")
              .find((item) => item.startsWith("hs_user_id="))
              ?.split("=")[1] ||
            window.localStorage.getItem("hs_user_id_local") ||
            process.env.NEXT_PUBLIC_DEFAULT_USER_ID ||
            "1",
        ).trim() || "1";
      window.location.replace(safeNext || `/assessment/${resolvedUserId}/chat`);
    };

    const hasSessionCookie = document.cookie.includes("hs_session=");
    if (hasSessionCookie) {
      redirectToApp();
      return;
    }

    const token = window.localStorage.getItem("hs_session_local");
    if (!token) return;

    const restoreSession = async () => {
      setRestoringSession(true);
      setStatus("Restoring your session…");
      try {
        const res = await fetch("/api/auth/refresh", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ token }),
        });
        if (!res.ok) {
          throw new Error("invalid session");
        }
        const data = (await res.json().catch(() => null)) as { user_id?: string | number } | null;
        if (!cancelled) {
          redirectToApp(data?.user_id);
        }
      } catch {
        try {
          window.localStorage.removeItem("hs_session_local");
          window.localStorage.removeItem("hs_user_id_local");
        } catch {}
        if (!cancelled) {
          setStatus(null);
        }
      } finally {
        if (!cancelled) {
          setRestoringSession(false);
        }
      }
    };

    void restoreSession();

    return () => {
      cancelled = true;
    };
  }, []);

  const requestOtp = async (event: React.FormEvent | null, channel: "auto" | "whatsapp" | "sms" = "auto") => {
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
      const res = await fetch("/api/auth/login/request", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ phone, password: password || undefined, channel }),
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
        const fallback = `Failed to verify code (HTTP ${res.status}).`;
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
        const maxAge = rememberMe ? 60 * 60 * 24 * 30 : 60 * 60 * 24 * 7;
        document.cookie = `hs_session=${token}; path=/; max-age=${maxAge}`;
        document.cookie = `hs_user_id=${userId}; path=/; max-age=${maxAge}`;
        try {
          window.localStorage.setItem("hs_session_local", token);
          window.localStorage.setItem("hs_user_id_local", String(userId));
        } catch {}
      }
      clearStoredLoginState();
      let requestedNext = "";
      if (typeof window !== "undefined") {
        requestedNext = String(new URLSearchParams(window.location.search).get("next") || "").trim();
      }
      const safeNext =
        requestedNext && requestedNext.startsWith("/") && !requestedNext.startsWith("//") && !requestedNext.startsWith("/api")
          ? requestedNext
          : "";
      if (data.setup_required) {
        window.location.href = safeNext
          ? `/setup-security?next=${encodeURIComponent(safeNext)}`
          : "/setup-security";
      } else {
        window.location.href = safeNext || `/assessment/${userId}/chat`;
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
          <div className="flex items-center">
            <HealthSenseMark className="h-10 w-7" />
          </div>
          <h1 className="mt-4 text-3xl">Sign in</h1>
          <p className="mt-2 text-sm text-[#6b6257]">
            Enter your mobile number. We&apos;ll send a code via WhatsApp or SMS.
          </p>
        </div>

        {!otpId ? (
          <form onSubmit={(e) => requestOtp(e, "auto")} className="space-y-4" autoComplete="off">
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
              disabled={loading || restoringSession}
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
              <label className="text-xs uppercase tracking-[0.2em] text-[#6b6257]">Login code</label>
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
            {setupRequired ? (
              <p className="text-sm text-[#6b6257]">First time login — you’ll be prompted to set your security after this step.</p>
            ) : null}
            <button
              className="w-full rounded-full border border-[var(--accent)] bg-[var(--accent)] px-5 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-60"
              type="submit"
              disabled={loading || restoringSession}
            >
              {loading ? "Verifying…" : "Verify & continue"}
            </button>
            <button
              type="button"
              className="w-full rounded-full border border-[#efe7db] px-5 py-2 text-sm"
              onClick={() => requestOtp(null, "whatsapp")}
              disabled={loading || restoringSession}
            >
              {loading ? "Sending…" : "Resend via WhatsApp"}
            </button>
            <button
              type="button"
              className="w-full rounded-full border border-[#efe7db] px-5 py-2 text-sm"
              onClick={() => requestOtp(null, "sms")}
              disabled={loading || restoringSession}
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
      </div>
      <LegalFooter className="mx-auto mt-6 max-w-md text-[#6b6257]" />
    </main>
  );
}
