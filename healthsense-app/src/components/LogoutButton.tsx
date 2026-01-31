"use client";

type LogoutButtonProps = {
  className?: string;
  label?: string;
};

export default function LogoutButton({ className = "", label = "Log out" }: LogoutButtonProps) {
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
        className={`rounded-full border border-[#efe7db] bg-white px-3 py-1 text-xs uppercase tracking-[0.2em] text-[#6b6257] ${className}`}
      >
        {label}
      </button>
    </form>
  );
}
