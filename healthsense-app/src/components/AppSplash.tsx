"use client";

import { useEffect, useState } from "react";
import HealthSenseMark from "@/components/HealthSenseMark";

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
      className={`fixed inset-0 z-[1000] flex min-h-[100dvh] items-center justify-center overflow-hidden bg-white px-8 text-center transition-opacity duration-500 ${
        leaving ? "pointer-events-none opacity-0" : "opacity-100"
      }`}
      role="status"
      aria-live="polite"
    >
      <div className="absolute left-1/2 top-1/2 w-[180vw] -translate-x-1/2 -translate-y-1/2 -rotate-[22deg]">
        <div className="flex w-max animate-[splash-marquee_7s_linear_infinite] items-center gap-10 whitespace-nowrap text-[3.9rem] font-semibold leading-none text-[#c54817] sm:text-[6.2rem]">
          {Array.from({ length: 8 }).map((_, index) => (
            <span key={index}>Find your own way</span>
          ))}
        </div>
      </div>
      <div className="relative z-10 flex h-28 w-28 items-center justify-center rounded-full bg-white/90 shadow-[0_18px_48px_-34px_rgba(30,27,22,0.38)] sm:h-36 sm:w-36">
        <HealthSenseMark className="h-20 w-14 sm:h-24 sm:w-16" />
      </div>
      <style jsx>{`
        @keyframes splash-marquee {
          from {
            transform: translate3d(0, 0, 0);
          }
          to {
            transform: translate3d(-50%, 0, 0);
          }
        }
      `}</style>
    </div>
  );
}
