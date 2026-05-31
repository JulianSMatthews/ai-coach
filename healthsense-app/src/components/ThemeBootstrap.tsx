"use client";

import { useEffect } from "react";
import {
  applyThemePreference,
  normalizeThemePreference,
  readStoredThemePreference,
} from "@/lib/theme";

type ThemeBootstrapProps = {
  defaultTheme?: string;
};

export default function ThemeBootstrap({ defaultTheme }: ThemeBootstrapProps) {
  useEffect(() => {
    const stored = readStoredThemePreference();
    const fallback = normalizeThemePreference(defaultTheme);
    const preference = stored || fallback;
    applyThemePreference(preference, true);

    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const handleChange = () => {
      const current = readStoredThemePreference() || fallback;
      if (current === "system") {
        applyThemePreference("system", false);
      }
    };
    if (typeof media.addEventListener === "function") {
      media.addEventListener("change", handleChange);
      return () => media.removeEventListener("change", handleChange);
    }
    media.addListener(handleChange);
    return () => media.removeListener(handleChange);
  }, [defaultTheme]);

  return null;
}
