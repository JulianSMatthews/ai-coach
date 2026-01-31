"use client";

import { useEffect } from "react";

const STORAGE_KEY = "healthsense.textScale";

type TextScaleProps = {
  defaultScale?: number;
};

export default function TextScale({ defaultScale }: TextScaleProps) {
  useEffect(() => {
    let scale = defaultScale;
    if (scale === undefined) {
      const stored = typeof window !== "undefined" ? window.localStorage.getItem(STORAGE_KEY) : null;
      if (stored) {
        const parsed = Number.parseFloat(stored);
        if (!Number.isNaN(parsed)) {
          scale = parsed;
        }
      }
    }
    const finalScale = scale && scale > 0 ? scale : 1;
    if (typeof window !== "undefined") {
      window.localStorage.setItem(STORAGE_KEY, String(finalScale));
      document.documentElement.style.setProperty("--text-scale", String(finalScale));
    }
  }, [defaultScale]);

  return null;
}
