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
  if (lower.includes("fetch failed") || lower.includes("timeout") || lower.includes("proxy request failed")) {
    return "We couldn’t reach the server. Please try again.";
  }
  if (lower.includes("upstream returned invalid response")) {
    return "We’re having trouble connecting. Please try again.";
  }
  if (lower.includes("email or phone required")) return "Enter your phone number to continue.";
  if (lower.includes("phone required")) return "Enter your phone number to continue.";
  if (lower.includes("user not found")) return "We couldn’t find an account for that mobile number.";
  if (lower.includes("email address required")) {
    return "Email sign-in is unavailable right now. Use your mobile number instead.";
  }
  if (lower.includes("mobile number required")) {
    return "This account does not have a mobile number on file. Contact support.";
  }
  if (lower.includes("invalid credentials")) {
    return "That password didn’t match. Try again, or leave it blank if this is your first login.";
  }
  if (lower.includes("channel must be")) return "Choose WhatsApp or SMS.";
  if (lower.includes("failed to send otp")) {
    if (
      lower.includes("auth email is not configured") ||
      lower.includes("auth_smtp") ||
      lower.includes("auth_ms_graph") ||
      lower.includes("auth_email_transport") ||
      lower.includes("microsoft graph email is not configured")
    ) {
      return "We couldn’t send a code because email delivery is not configured.";
    }
    if (
      lower.includes("smtp.office365.com") ||
      lower.includes("authentication unsuccessful") ||
      lower.includes("client not authenticated") ||
      lower.includes("535 5.7.139") ||
      lower.includes("535 5.7.3") ||
      lower.includes("microsoft graph") ||
      lower.includes("graph.microsoft.com") ||
      lower.includes("login.microsoftonline.com") ||
      lower.includes("aadsts") ||
      lower.includes("mail.send") ||
      lower.includes("erroraccessdenied") ||
      lower.includes("access to odata is disabled") ||
      lower.includes("invalid_client")
    ) {
      return "We couldn’t send a code because the Microsoft 365 email delivery setup is rejecting the request.";
    }
    if (lower.includes("twilio_sms_from")) {
      return "We couldn’t send a code because SMS fallback is not configured.";
    }
    if (lower.includes("twilio_from")) {
      return "We couldn’t send a code because WhatsApp sender setup is invalid.";
    }
    if (lower.includes("63016")) {
      return "We couldn’t send a code on WhatsApp (24h session closed) and SMS fallback failed.";
    }
    return "We couldn’t send a code. Please try again.";
  }
  if (lower.includes("failed to request otp")) {
    return "We couldn’t send a code. Please try again.";
  }
  if (lower.includes("email or phone, otp_id, code, and password required")) {
    return "Enter the 6-digit code and a new password.";
  }
  if (lower.includes("phone, otp_id, code, and password required")) {
    return "Enter the 6-digit code and a new password.";
  }
  if (lower.includes("email or phone, otp_id, and code required") || lower.includes("otp_id must")) {
    return "Enter the 6-digit code we sent.";
  }
  if (lower.includes("phone, otp_id, and code required") || lower.includes("otp_id must")) {
    return "Enter the 6-digit code we sent.";
  }
  if (lower.includes("otp not found")) return "That code is no longer valid. Request a new one.";
  if (lower.includes("otp already used")) return "That code was already used. Request a new one.";
  if (lower.includes("otp expired")) return "That code has expired. Request a new one.";
  if (lower.includes("invalid otp")) {
    return "That code didn’t match. Use the latest code or request a new one.";
  }
  if (lower.includes("userId is required") || lower.includes("missing user id")) {
    return "We couldn’t identify your account. Please sign in again.";
  }
  if (lower.includes("email is required")) return "Please enter your phone number to continue.";
  if (lower.includes("invalid email")) return "Email sign-in is unavailable right now. Use your mobile number instead.";
  if (lower.includes("password must be at least")) return "Password must be at least 8 characters.";
  if (lower.includes("session required")) return "Your session expired. Please sign in again.";
  if (lower.includes("internal server error")) return "Something went wrong. Please try again.";
  return message;
}
