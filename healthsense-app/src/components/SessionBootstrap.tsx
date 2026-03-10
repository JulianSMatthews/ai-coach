"use client";

import { useEffect } from "react";

export default function SessionBootstrap() {
  useEffect(() => {
    try {
      const hasSessionCookie = document.cookie.includes("hs_session=");
      const hasUserCookie = document.cookie.includes("hs_user_id=");
      const inLeadFlow = (() => {
        try {
          const url = new URL(window.location.href);
          const leadToken = (url.searchParams.get("lead") || "").trim().toLowerCase();
          return leadToken === "1" || leadToken === "true" || leadToken === "yes" || leadToken === "on";
        } catch {
          return false;
        }
      })();
      const token = window.localStorage.getItem("hs_session_local");
      if (!hasSessionCookie && !hasUserCookie && !inLeadFlow && token) {
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
