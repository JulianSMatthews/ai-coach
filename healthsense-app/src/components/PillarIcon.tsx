// Reuse the six pillar glyphs already shown in app setup and on the website.
const PILLAR_PATHS: Record<string, readonly string[]> = {
  reflection: [
    "M4 12s3.1-5.5 8-5.5S20 12 20 12s-3.1 5.5-8 5.5S4 12 4 12Z",
    "M12 14.5a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5Z",
  ],
  purpose: [
    "M12 21s7-5.3 7-11a7 7 0 0 0-14 0c0 5.7 7 11 7 11Z",
    "M12 13a3 3 0 1 0 0-6 3 3 0 0 0 0 6Z",
    "M12 10h2",
  ],
  resilience: [
    "M6 13.5c1.9-2 4.2-2 6 0s4.1 2 6 0",
    "M6 17c1.9-2 4.2-2 6 0s4.1 2 6 0",
    "M12 4.5a5 5 0 0 0-5 5c0 1.4.6 2.6 1.5 3.5",
    "M12 4.5a5 5 0 0 1 5 5c0 1.4-.6 2.6-1.5 3.5",
  ],
  recovery: [
    "M19 15.2A7.2 7.2 0 0 1 8.8 5a7.8 7.8 0 1 0 10.2 10.2Z",
    "M16.5 4.8h3",
    "M18 3.3v3",
    "M7.5 16.5c1.4 1 3.1 1.5 5 1.2",
  ],
  nutrition: [
    "M6 4.5v15",
    "M9 4.5v5a3 3 0 0 1-3 3",
    "M15.5 4.5c2.2.7 3.5 2.8 3.5 5.2 0 2.6-1.5 4.8-3.5 5.3v4.5",
    "M15.5 4.5v10.5",
  ],
  training: [
    "M4 10v4",
    "M7 8v8",
    "M17 8v8",
    "M20 10v4",
    "M7 12h10",
  ],
};

export default function PillarIcon({ pillarKey, className = "h-6 w-6" }: { pillarKey: string; className?: string }) {
  const paths = PILLAR_PATHS[pillarKey.trim().toLowerCase()];
  if (!paths) return null;

  return (
    <svg
      viewBox="0 0 24 24"
      className={className}
      aria-hidden="true"
      focusable="false"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      {paths.map((path) => <path key={path} d={path} />)}
    </svg>
  );
}
