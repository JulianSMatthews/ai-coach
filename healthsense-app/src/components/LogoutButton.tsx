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
    <form onSubmit={handleLogout} className="w-full md:w-auto">
      <button
        type="submit"
        className={`inline-flex min-h-11 w-full items-center justify-center rounded-full border border-[var(--action-primary-border)] bg-[var(--action-primary-bg)] px-5 py-3 text-center text-sm font-semibold text-[var(--action-primary-text)] transition active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-60 md:w-auto md:px-4 md:py-2 ${className}`}
        style={style}
      >
        {label}
      </button>
    </form>
  );
}
