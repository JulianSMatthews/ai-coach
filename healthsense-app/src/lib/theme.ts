export const THEME_STORAGE_KEY = "healthsense.theme";
export const THEME_COOKIE_KEY = "healthsense_theme";

export type ThemePreference = "light" | "dark" | "system" | "auto";
export type ResolvedTheme = "light" | "dark";

export function normalizeThemePreference(value: unknown): ThemePreference {
  const token = String(value || "").trim().toLowerCase();
  if (token === "light" || token === "dark" || token === "system" || token === "auto") {
    return token;
  }
  return "light";
}

export function resolveAutoTheme(now = new Date()): ResolvedTheme {
  const hour = now.getHours();
  return hour >= 19 || hour < 7 ? "dark" : "light";
}

export function resolveTheme(preference: ThemePreference): ResolvedTheme {
  if (preference === "light" || preference === "dark") {
    return preference;
  }
  if (preference === "auto") {
    return resolveAutoTheme();
  }
  if (typeof window !== "undefined" && window.matchMedia("(prefers-color-scheme: dark)").matches) {
    return "dark";
  }
  return "light";
}

function readThemeCookie(): ThemePreference | null {
  if (typeof document === "undefined") return null;
  const match = document.cookie.match(new RegExp(`(?:^|; )${THEME_COOKIE_KEY}=([^;]+)`));
  if (!match?.[1]) return null;
  return normalizeThemePreference(decodeURIComponent(match[1]));
}

function writeThemeCookie(preference: ThemePreference) {
  if (typeof document === "undefined") return;
  document.cookie = `${THEME_COOKIE_KEY}=${encodeURIComponent(preference)}; path=/; max-age=31536000; samesite=lax`;
}

export function applyThemePreference(preferenceInput: unknown, persist = true): ThemePreference {
  const preference = normalizeThemePreference(preferenceInput);
  if (typeof document === "undefined") {
    return preference;
  }
  const resolved = resolveTheme(preference);
  const root = document.documentElement;
  root.dataset.themePreference = preference;
  root.dataset.theme = resolved;
  root.style.colorScheme = resolved;
  if (persist && typeof window !== "undefined") {
    window.localStorage.setItem(THEME_STORAGE_KEY, preference);
    writeThemeCookie(preference);
  }
  if (typeof window !== "undefined") {
    window.dispatchEvent(
      new CustomEvent("healthsense-theme-changed", {
        detail: { preference, resolved },
      }),
    );
  }
  return preference;
}

export function readStoredThemePreference(): ThemePreference | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(THEME_STORAGE_KEY);
    if (raw) return normalizeThemePreference(raw);
  } catch {
    return readThemeCookie();
  }
  return readThemeCookie();
}

export function themeBootstrapScript(): string {
  return `
    (function () {
      try {
        var KEY = ${JSON.stringify(THEME_STORAGE_KEY)};
        var COOKIE_KEY = ${JSON.stringify(THEME_COOKIE_KEY)};
        var raw = window.localStorage.getItem(KEY);
        if (!raw) {
          var cookieMatch = document.cookie.match(new RegExp("(?:^|; )" + COOKIE_KEY + "=([^;]+)"));
          raw = cookieMatch && cookieMatch[1] ? decodeURIComponent(cookieMatch[1]) : "light";
        }
        var preference = raw === "light" || raw === "dark" || raw === "system" || raw === "auto" ? raw : "light";
        var hour = new Date().getHours();
        var resolved = preference === "auto"
          ? (hour >= 19 || hour < 7 ? "dark" : "light")
          : preference === "system"
            ? (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light")
            : preference;
        var root = document.documentElement;
        root.setAttribute("data-theme-preference", preference);
        root.setAttribute("data-theme", resolved);
        root.style.colorScheme = resolved;
      } catch (error) {}
    })();
  `;
}
