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
      if (current === "system" || current === "auto") {
        applyThemePreference(current, false);
      }
    };
    const interval = window.setInterval(() => {
      const current = readStoredThemePreference() || fallback;
      if (current === "auto") {
        applyThemePreference("auto", false);
      }
    }, 60_000);
    if (typeof media.addEventListener === "function") {
      media.addEventListener("change", handleChange);
      return () => {
        window.clearInterval(interval);
        media.removeEventListener("change", handleChange);
      };
    }
    media.addListener(handleChange);
    return () => {
      window.clearInterval(interval);
      media.removeListener(handleChange);
    };
  }, [defaultTheme]);

  return null;
}
