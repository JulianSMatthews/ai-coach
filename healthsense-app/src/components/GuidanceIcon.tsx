export default function GuidanceIcon({ kind }: { kind: "step" | "reflection" }) {
  return (
    <svg
      viewBox="0 0 24 24"
      className="h-7 w-7 shrink-0"
      aria-hidden="true"
      focusable="false"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      {kind === "step" ? (
        <>
          <path d="M15.5 3C13.9 3 13 5 13 7.5c0 1.8.8 3 2.5 3s2.5-1.2 2.5-3C18 5 17.1 3 15.5 3Z" />
          <path d="M14 13h3v1.5a1.5 1.5 0 0 1-3 0Z" />
          <path d="M7.5 8C5.9 8 5 10 5 12.5c0 1.8.8 3 2.5 3s2.5-1.2 2.5-3C10 10 9.1 8 7.5 8Z" />
          <path d="M6 18h3v1.5a1.5 1.5 0 0 1-3 0Z" />
        </>
      ) : (
        <>
          <ellipse cx="12" cy="9" rx="9" ry="6" />
          <circle cx="6.5" cy="18" r="1.5" />
          <circle cx="3.5" cy="21" r="0.75" />
        </>
      )}
    </svg>
  );
}

