"use client";

import { useEffect } from "react";

export default function SessionBootstrap() {
  useEffect(() => {
    try {
      const hasCookie = document.cookie.includes("hs_session=");
      const token = window.localStorage.getItem("hs_session_local");
      if (!hasCookie && token) {
        fetch("/api/auth/refresh", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ token }),
        }).catch(() => null);
      }
    } catch {}
  }, []);

  return null;
}
