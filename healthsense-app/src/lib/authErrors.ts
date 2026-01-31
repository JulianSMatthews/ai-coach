export function extractErrorMessage(raw: unknown): string {
  if (raw instanceof Error) return raw.message;
  if (typeof raw === "string") return raw;
  if (raw && typeof raw === "object") {
    const anyRaw = raw as Record<string, unknown>;
    const direct = anyRaw.detail ?? anyRaw.error ?? anyRaw.message;
    if (typeof direct === "string") return direct;
  }
  return "";
}

export function normalizeErrorMessage(raw: unknown): string {
  const base = extractErrorMessage(raw).trim();
  if (!base) return "";
  if (base.startsWith("{") || base.startsWith("[")) {
    try {
      const parsed = JSON.parse(base);
      if (typeof parsed === "string") return parsed;
      if (parsed && typeof parsed === "object") {
        const detail = (parsed as Record<string, unknown>).detail ?? (parsed as Record<string, unknown>).error ?? (parsed as Record<string, unknown>).message;
        if (typeof detail === "string") return detail;
      }
    } catch {
      return base;
    }
  }
  return base;
}

export function friendlyAuthError(raw: unknown): string {
  const message = normalizeErrorMessage(raw);
  const lower = message.toLowerCase();
  if (!message) return "Something went wrong. Please try again.";
  if (lower.includes("api_base_url")) return "We’re having trouble connecting. Please try again.";
  if (lower.includes("fetch failed") || lower.includes("timeout")) {
    return "We couldn’t reach the server. Please try again.";
  }
  if (lower.includes("phone required")) return "Enter your phone number to continue.";
  if (lower.includes("user not found")) return "We couldn’t find an account for that phone number.";
  if (lower.includes("invalid credentials")) {
    return "That password didn’t match. Try again, or leave it blank if this is your first login.";
  }
  if (lower.includes("channel must be")) return "Choose WhatsApp or SMS.";
  if (lower.includes("failed to send otp")) {
    return "We couldn’t send a code. Try again or choose SMS.";
  }
  if (lower.includes("phone, otp_id, code, and password required")) {
    return "Enter the 6-digit code and a new password.";
  }
  if (lower.includes("phone, otp_id, and code required") || lower.includes("otp_id must")) {
    return "Enter the 6-digit code we sent.";
  }
  if (lower.includes("otp not found")) return "That code is no longer valid. Request a new one.";
  if (lower.includes("otp already used")) return "That code was already used. Request a new one.";
  if (lower.includes("otp expired")) return "That code has expired. Request a new one.";
  if (lower.includes("invalid otp")) {
    return "That code didn’t match. Use the latest code or tap “Send via SMS”.";
  }
  if (lower.includes("userId is required") || lower.includes("missing user id")) {
    return "We couldn’t identify your account. Please sign in again.";
  }
  if (lower.includes("email is required")) return "Please enter your email to continue.";
  if (lower.includes("invalid email")) return "That email doesn’t look right. Please check it.";
  if (lower.includes("password must be at least")) return "Password must be at least 8 characters.";
  if (lower.includes("session required")) return "Your session expired. Please sign in again.";
  if (lower.includes("internal server error")) return "Something went wrong. Please try again.";
  return message;
}
