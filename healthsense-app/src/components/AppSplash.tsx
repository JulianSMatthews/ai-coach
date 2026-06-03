"use client";

import { useEffect, useState } from "react";

export default function AppSplash() {
  const [visible, setVisible] = useState(true);
  const [leaving, setLeaving] = useState(false);

  useEffect(() => {
    const leaveTimer = window.setTimeout(() => setLeaving(true), 1400);
    const removeTimer = window.setTimeout(() => setVisible(false), 1850);

    return () => {
      window.clearTimeout(leaveTimer);
      window.clearTimeout(removeTimer);
    };
  }, []);

  if (!visible) return null;

  return (
    <div
      className={`fixed inset-0 z-[1000] flex min-h-[100dvh] items-center justify-center bg-white px-8 text-center transition-opacity duration-500 ${
        leaving ? "pointer-events-none opacity-0" : "opacity-100"
      }`}
      role="status"
      aria-live="polite"
    >
      <p className="max-w-[14rem] text-[2.3rem] font-semibold leading-[1.02] tracking-normal text-[#c54817] sm:max-w-[18rem] sm:text-[3rem]">
        Find your own way to better health.
      </p>
    </div>
  );
}
