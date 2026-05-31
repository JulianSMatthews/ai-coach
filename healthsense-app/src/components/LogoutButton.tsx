"use client";

import type React from "react";

type LogoutButtonProps = {
  className?: string;
  label?: string;
  style?: React.CSSProperties;
};

export default function LogoutButton({ className = "", label = "Logout", style }: LogoutButtonProps) {
  const handleLogout = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    try {
      await fetch("/api/auth/logout", { method: "POST" });
    } finally {
      try {
        window.localStorage.removeItem("hs_session_local");
        window.localStorage.removeItem("hs_user_id_local");
      } catch {}
      window.location.href = "/login";
    }
  };

  return (
    <form onSubmit={handleLogout}>
      <button
        className={`rounded-full border border-[var(--border)] bg-[var(--surface)] px-3 py-1 text-sm text-[var(--text-primary)] ${className}`}
        style={style}
      >
        {label}
      </button>
    </form>
  );
}
