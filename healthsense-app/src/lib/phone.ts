export function normalizePhoneForAuth(value: string): string {
  const trimmed = String(value || "").trim();
  if (!trimmed) return "";
  const digits = trimmed.replace(/[^\d]/g, "");
  if (digits.startsWith("07") && digits.length === 11) {
    return `+44${digits.slice(1)}`;
  }
  if (digits.startsWith("447") && digits.length === 12) {
    return `+${digits}`;
  }
  if (trimmed.startsWith("+")) {
    return `+${digits}`;
  }
  return trimmed;
}

export function looksLikePhone(value: string): boolean {
  const normalized = normalizePhoneForAuth(value);
  const digits = normalized.replace(/[^\d]/g, "");
  return normalized.startsWith("+") && digits.length >= 8;
}
