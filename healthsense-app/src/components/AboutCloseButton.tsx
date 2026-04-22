"use client";

type AboutCloseButtonProps = {
  className?: string;
};

function safeReturnPath(value: string): string {
  return value && value.startsWith("/") && !value.startsWith("//") && !value.startsWith("/api") ? value : "";
}

function fallbackAppPath(): string {
  try {
    const cookieUserId = document.cookie
      .split("; ")
      .find((item) => item.startsWith("hs_user_id="))
      ?.split("=")[1];
    const userId = cookieUserId || window.localStorage.getItem("hs_user_id_local") || "";
    return userId ? `/assessment/${encodeURIComponent(userId)}/chat` : "/login";
  } catch {
    return "/login";
  }
}

export default function AboutCloseButton({ className = "" }: AboutCloseButtonProps) {
  const close = () => {
    const params = new URLSearchParams(window.location.search);
    const returnTo = safeReturnPath(String(params.get("returnTo") || "").trim());
    if (returnTo) {
      window.location.assign(returnTo);
      return;
    }
    if (window.history.length > 1) {
      window.history.back();
      return;
    }
    window.location.assign(fallbackAppPath());
  };

  return (
    <button
      type="button"
      onClick={close}
      className={`rounded-full border border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-[11px] font-semibold text-[var(--text-secondary)] shadow-[0_10px_24px_-18px_var(--shadow-strong)] ${className}`.trim()}
    >
      close
    </button>
  );
}
