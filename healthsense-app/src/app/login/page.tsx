"use client";

import { useEffect, useRef, useState } from "react";
import { friendlyAuthError } from "@/lib/authErrors";
import { looksLikePhone, normalizePhoneForAuth } from "@/lib/phone";
import HealthSenseMark from "@/components/HealthSenseMark";

export default function LoginPage() {
  const [mode, setMode] = useState<"signin" | "create">("signin");
  const [firstName, setFirstName] = useState("");
  const [surname, setSurname] = useState("");
  const [phone, setPhone] = useState("");
  const [password, setPassword] = useState("");
  const [createPassword, setCreatePassword] = useState("");
  const [createConfirmPassword, setCreateConfirmPassword] = useState("");
  const [otpId, setOtpId] = useState<number | null>(null);
  const [code, setCode] = useState("");
  const [status, setStatus] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [setupRequired, setSetupRequired] = useState(false);
  const [rememberMe, setRememberMe] = useState(true);
  const [restoringSession, setRestoringSession] = useState(false);
  const [acceptedTerms, setAcceptedTerms] = useState(false);
  const codeInputRef = useRef<HTMLInputElement | null>(null);

  const clearStoredLoginState = () => {
    if (typeof window === "undefined") return;
    try {
      window.sessionStorage.removeItem("hs_login_otp_id");
      window.sessionStorage.removeItem("hs_login_phone");
      window.sessionStorage.removeItem("hs_login_setup");
      window.sessionStorage.removeItem("hs_login_mode");
      window.sessionStorage.removeItem("hs_login_first_name");
      window.sessionStorage.removeItem("hs_login_surname");
      window.sessionStorage.removeItem("hs_login_terms");
    } catch {}
  };

  const resetOtpState = () => {
    setOtpId(null);
    setCode("");
    setSetupRequired(false);
    setCreatePassword("");
    setCreateConfirmPassword("");
    clearStoredLoginState();
  };

  useEffect(() => {
    if (typeof window === "undefined") return;
    const resetSession = (() => {
      try {
        const url = new URL(window.location.href);
        const raw = (url.searchParams.get("resetSession") || "").trim().toLowerCase();
        return raw === "1" || raw === "true" || raw === "yes" || raw === "on";
      } catch {
        return false;
      }
    })();
    if (resetSession) {
      try {
        document.cookie = "hs_session=; path=/; max-age=0";
        document.cookie = "hs_user_id=; path=/; max-age=0";
        window.localStorage.removeItem("hs_session_local");
        window.localStorage.removeItem("hs_user_id_local");
      } catch {}
      clearStoredLoginState();
    }
    try {
      const savedOtpId = window.sessionStorage.getItem("hs_login_otp_id");
      const savedPhone = window.sessionStorage.getItem("hs_login_phone");
      const savedSetup = window.sessionStorage.getItem("hs_login_setup");
      const savedMode = window.sessionStorage.getItem("hs_login_mode");
      const savedFirstName = window.sessionStorage.getItem("hs_login_first_name");
      const savedSurname = window.sessionStorage.getItem("hs_login_surname");
      const savedTerms = window.sessionStorage.getItem("hs_login_terms");
      if (savedPhone) setPhone(savedPhone);
      if (savedFirstName) setFirstName(savedFirstName);
      if (savedSurname) setSurname(savedSurname);
      if (savedMode === "create") setMode("create");
      if (savedTerms === "true") setAcceptedTerms(true);
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
      window.location.replace(safeNext || "/");
    };

    const hasSessionCookie = document.cookie.includes("hs_session=");
    const resetSession = (() => {
      try {
        const raw = (new URLSearchParams(window.location.search).get("resetSession") || "").trim().toLowerCase();
        return raw === "1" || raw === "true" || raw === "yes" || raw === "on";
      } catch {
        return false;
      }
    })();
    if (hasSessionCookie && !resetSession) {
      redirectToApp();
      return;
    }

    const token = window.localStorage.getItem("hs_session_local");
    if (!token || resetSession) return;

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

  useEffect(() => {
    if (!otpId) return;
    const timeout = window.setTimeout(() => {
      codeInputRef.current?.focus();
    }, 120);
    return () => window.clearTimeout(timeout);
  }, [otpId]);

  const requestOtp = async (event: React.FormEvent | null, channel: "auto" | "whatsapp" | "sms" = "auto") => {
    if (event) event.preventDefault();
    const normalizedPhone = normalizePhoneForAuth(phone);
    if (!normalizedPhone) {
      setStatus("Please enter your phone number to continue.");
      return;
    }
    if (mode === "create" && (!firstName.trim() || !surname.trim())) {
      setStatus("Please enter your first name and surname to create your account.");
      return;
    }
    if (mode === "create" && !acceptedTerms) {
      setStatus("Please accept the Terms and Privacy Policy to create your account.");
      return;
    }
    if (!looksLikePhone(normalizedPhone)) {
      setStatus("Enter a valid mobile number, ideally with country code.");
      return;
    }
    if (normalizedPhone !== phone) {
      setPhone(normalizedPhone);
    }

    setLoading(true);
    setStatus(null);
    try {
      const endpoint = mode === "create" ? "/api/auth/register/request" : "/api/auth/login/request";
      const res = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          phone: normalizedPhone,
          password: mode === "signin" ? password || undefined : undefined,
          first_name: mode === "create" ? firstName : undefined,
          surname: mode === "create" ? surname : undefined,
          accepted_terms: mode === "create" ? acceptedTerms : undefined,
          channel,
        }),
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
      const codeLabel = mode === "create" ? "an account code" : "a login code";
      setStatus(channelUsed === "sms" ? `We sent ${codeLabel} by SMS.` : `We sent ${codeLabel} to your WhatsApp.`);
      if (typeof window !== "undefined") {
        try {
          window.sessionStorage.setItem("hs_login_otp_id", String(data.otp_id));
          window.sessionStorage.setItem("hs_login_phone", normalizedPhone);
          window.sessionStorage.setItem("hs_login_setup", String(Boolean(data.setup_required)));
          window.sessionStorage.setItem("hs_login_mode", mode);
          window.sessionStorage.setItem("hs_login_first_name", firstName);
          window.sessionStorage.setItem("hs_login_surname", surname);
          window.sessionStorage.setItem("hs_login_terms", String(acceptedTerms));
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
    const normalizedPhone = normalizePhoneForAuth(phone);
    if (mode === "create") {
      if (createPassword.length < 8) {
        setStatus("Password must be at least 8 characters.");
        return;
      }
      if (createPassword !== createConfirmPassword) {
        setStatus("Passwords do not match.");
        return;
      }
    }
    setLoading(true);
    setStatus(null);
    try {
      const endpoint = mode === "create" ? "/api/auth/register/verify" : "/api/auth/login/verify";
      const res = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ phone: normalizedPhone, otp_id: otpId, code, remember_me: rememberMe }),
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
      if (mode === "create") {
        const passwordRes = await fetch("/api/preferences", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            userId,
            password: createPassword,
            preferred_channel: "app",
          }),
        });
        if (!passwordRes.ok) {
          const text = await passwordRes.text().catch(() => "");
          throw new Error(text || "Failed to save password.");
        }
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
      if (data.setup_required && mode !== "create") {
        const setupNext = safeNext || "/";
        window.location.href = `/setup-security?next=${encodeURIComponent(setupNext)}`;
      } else {
        window.location.href = safeNext || "/";
      }
    } catch (error) {
      setStatus(friendlyAuthError(error));
    } finally {
      setLoading(false);
    }
  };

  const inputClass =
    "mt-2 h-13 w-full rounded-[14px] border border-[var(--border)] bg-[var(--input-background)] px-4 text-[17px] text-[var(--text-primary)] outline-none transition focus:border-[var(--text-primary)]";
  const labelClass = "text-[14px] font-semibold uppercase tracking-[0.12em] text-[var(--text-secondary)]";
  const primaryButtonClass =
    "min-h-13 w-full rounded-full border border-[var(--action-primary-border)] bg-[var(--action-primary-bg)] px-5 py-3 text-[17px] font-semibold text-[var(--action-primary-text)] transition active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-60";
  const secondaryButtonClass =
    "min-h-13 w-full rounded-full border border-[var(--border)] bg-[var(--surface)] px-5 py-3 text-[17px] font-semibold text-[var(--text-primary)] transition active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-60";

  return (
    <main className="flex min-h-[100dvh] items-center overflow-x-hidden bg-[var(--background)] px-4 py-[max(1.25rem,env(safe-area-inset-top))] text-[var(--foreground)] sm:px-6">
      <section className="mx-auto flex w-full max-w-md flex-col gap-6">
        <div className="space-y-3">
          <div className="flex items-center gap-3">
            <HealthSenseMark className="h-12 w-8 shrink-0" />
            <h1 className="text-[2.4rem] font-semibold leading-none text-[var(--text-primary)]">Sign in</h1>
          </div>
          <div>
            <p className="text-[18px] leading-7 text-[var(--text-secondary)]">
            Sign in with your mobile number, or create a free CoachSense account.
            </p>
          </div>
        </div>

        {!otpId ? (
          <form onSubmit={(e) => requestOtp(e, "auto")} className="space-y-5" autoComplete="off">
            <div className="grid grid-cols-2 gap-1 rounded-full border border-[var(--border)] bg-[var(--surface-muted)] p-1 text-[16px]">
              <button
                type="button"
                className={`min-h-12 rounded-full px-3 py-2 font-semibold transition ${
                  mode === "signin" ? "bg-[var(--surface)] text-[var(--text-primary)] shadow-sm" : "text-[var(--text-secondary)]"
                }`}
                onClick={() => {
                  setMode("signin");
                  resetOtpState();
                }}
              >
                Sign in
              </button>
              <button
                type="button"
                className={`min-h-12 rounded-full px-3 py-2 font-semibold transition ${
                  mode === "create" ? "bg-[var(--surface)] text-[var(--text-primary)] shadow-sm" : "text-[var(--text-secondary)]"
                }`}
                onClick={() => {
                  setMode("create");
                  resetOtpState();
                }}
              >
                Create account
              </button>
            </div>
            {mode === "create" ? (
              <div className="grid gap-4 sm:grid-cols-2">
                <div>
                  <label className={labelClass}>First name</label>
                  <input
                    className={inputClass}
                    type="text"
                    autoComplete="given-name"
                    value={firstName}
                    onChange={(e) => setFirstName(e.target.value)}
                    placeholder="Alex"
                  />
                </div>
                <div>
                  <label className={labelClass}>Surname</label>
                  <input
                    className={inputClass}
                    type="text"
                    autoComplete="family-name"
                    value={surname}
                    onChange={(e) => setSurname(e.target.value)}
                    placeholder="Smith"
                  />
                </div>
              </div>
            ) : null}
            <div>
              <label className={labelClass} htmlFor="mobile-number">Mobile number</label>
              <input
                id="mobile-number"
                name="tel"
                className={inputClass}
                type="tel"
                autoComplete="tel"
                inputMode="tel"
                enterKeyHint="next"
                autoCapitalize="none"
                autoCorrect="off"
                value={phone}
                onChange={(e) => setPhone(e.target.value)}
                placeholder="+44 7700 900000"
              />
            </div>
            {mode === "signin" ? (
            <div>
              <label className={labelClass}>Password</label>
              <input
                className={inputClass}
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="Leave blank if first time"
              />
              <div className="mt-2 text-right">
                <a className="text-[15px] font-semibold text-[var(--accent)] underline" href="/reset-password">
                  Forgot password?
                </a>
              </div>
            </div>
            ) : (
              <label className="flex items-start gap-3 text-[16px] leading-6 text-[var(--text-secondary)]">
                <input
                  className="mt-1 h-5 w-5 accent-[var(--action-primary-bg)]"
                  type="checkbox"
                  checked={acceptedTerms}
                  onChange={(e) => setAcceptedTerms(e.target.checked)}
                />
                <span>
                  I agree to the{" "}
                  <a className="font-semibold text-[var(--accent)] underline" href="/terms" target="_blank" rel="noreferrer">
                    Terms
                  </a>{" "}
                  and{" "}
                  <a className="font-semibold text-[var(--accent)] underline" href="/privacy" target="_blank" rel="noreferrer">
                    Privacy Policy
                  </a>
                  .
                </span>
              </label>
            )}
            <button
              className={primaryButtonClass}
              type="submit"
              disabled={loading || restoringSession}
            >
              {loading ? "Sending…" : mode === "create" ? "Create account" : "Send login code"}
            </button>
            <label className="flex items-center gap-3 text-[16px] text-[var(--text-secondary)]">
              <input
                className="h-5 w-5 accent-[var(--action-primary-bg)]"
                type="checkbox"
                checked={rememberMe}
                onChange={(e) => setRememberMe(e.target.checked)}
              />
              Remember me for 30 days
            </label>
          </form>
        ) : (
          <form onSubmit={verifyOtp} className="space-y-5" autoComplete="off">
            <div>
              <label className={labelClass}>
                {mode === "create" ? "Account code" : "Login code"}
              </label>
              <input
                ref={codeInputRef}
                id="auth-code"
                name="one-time-code"
                className={`${inputClass} text-center tracking-[0.3em]`}
                type="text"
                inputMode="numeric"
                pattern="[0-9]*"
                autoComplete="one-time-code"
                enterKeyHint="next"
                value={code}
                onChange={(e) => setCode(e.target.value)}
                placeholder="123456"
              />
            </div>
            <p className="text-[16px] leading-6 text-[var(--text-secondary)]">Use the code sent to your mobile number.</p>
            {mode === "create" ? (
              <div className="space-y-4">
                <div>
                  <label className={labelClass}>Create password</label>
                  <input
                    className={inputClass}
                    type="password"
                    autoComplete="new-password"
                    value={createPassword}
                    onChange={(e) => setCreatePassword(e.target.value)}
                    placeholder="Minimum 8 characters"
                  />
                </div>
                <div>
                  <label className={labelClass}>Confirm password</label>
                  <input
                    className={inputClass}
                    type="password"
                    autoComplete="new-password"
                    value={createConfirmPassword}
                    onChange={(e) => setCreateConfirmPassword(e.target.value)}
                    placeholder="Re-enter password"
                  />
                </div>
              </div>
            ) : null}
            {setupRequired && mode === "signin" ? (
              <p className="text-[16px] leading-6 text-[var(--text-secondary)]">First time login - you’ll be prompted to set your security after this step.</p>
            ) : null}
            <button
              className={primaryButtonClass}
              type="submit"
              disabled={loading || restoringSession}
            >
              {loading ? "Verifying…" : "Verify & continue"}
            </button>
            <button
              type="button"
              className={secondaryButtonClass}
              onClick={() => requestOtp(null, "whatsapp")}
              disabled={loading || restoringSession}
            >
              {loading ? "Sending…" : "Resend via WhatsApp"}
            </button>
            <button
              type="button"
              className={secondaryButtonClass}
              onClick={() => requestOtp(null, "sms")}
              disabled={loading || restoringSession}
            >
              {loading ? "Sending…" : "Send via SMS"}
            </button>
            <button
              type="button"
              className={secondaryButtonClass}
              onClick={resetOtpState}
            >
              Use a different number
            </button>
          </form>
        )}

        {status ? (
          <p className="rounded-[18px] border border-[var(--border)] bg-[var(--surface)] px-4 py-3 text-[16px] leading-6 text-[var(--text-secondary)]">
            {status}
          </p>
        ) : null}
      </section>
    </main>
  );
}
