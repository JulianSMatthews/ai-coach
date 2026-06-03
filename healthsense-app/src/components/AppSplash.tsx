"use client";

import { useEffect, useState } from "react";
import HealthSenseMark from "@/components/HealthSenseMark";

export default function AppSplash() {
  const [visible, setVisible] = useState(true);
  const [leaving, setLeaving] = useState(false);

  useEffect(() => {
    const leaveTimer = window.setTimeout(() => setLeaving(true), 3150);
    const removeTimer = window.setTimeout(() => setVisible(false), 3650);

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
      <div className="splash-logo">
        <HealthSenseMark className="h-24 w-16 sm:h-28 sm:w-20" />
      </div>
      <div className="splash-words" aria-hidden="true">
        <span className="splash-word splash-word-find">Find</span>
        <span className="splash-word splash-word-your">your</span>
        <span className="splash-word splash-word-own">own</span>
        <span className="splash-word splash-word-way">way</span>
      </div>
      <span className="sr-only">Find your own way.</span>
      <style jsx>{`
        .splash-logo {
          position: absolute;
          left: 50%;
          top: 50%;
          display: flex;
          align-items: center;
          justify-content: center;
          animation: splash-logo-flight 1.65s cubic-bezier(0.2, 0.8, 0.2, 1) forwards;
        }

        .splash-words {
          position: absolute;
          inset: 0;
          color: #c54817;
          font-size: clamp(3.8rem, 15vw, 7.5rem);
          font-weight: 700;
          line-height: 0.9;
        }

        .splash-word {
          position: absolute;
          left: 50%;
          top: 50%;
          opacity: 0;
          transform: translate3d(var(--from-x), var(--from-y), 0) scale(0.96);
          animation: splash-word-arrive 1.05s cubic-bezier(0.18, 0.86, 0.22, 1) forwards;
          animation-delay: 1.45s;
        }

        .splash-word-find {
          --from-x: -72vw;
          --from-y: -56dvh;
          --to-x: -50%;
          --to-y: calc(-50% - 4.2rem);
        }

        .splash-word-your {
          --from-x: 48vw;
          --from-y: 56dvh;
          --to-x: calc(-50% + 0.3rem);
          --to-y: calc(-50% - 0.1rem);
          animation-delay: 1.58s;
        }

        .splash-word-own {
          --from-x: -68vw;
          --from-y: 54dvh;
          --to-x: calc(-50% - 0.1rem);
          --to-y: calc(-50% + 4rem);
          animation-delay: 1.71s;
        }

        .splash-word-way {
          --from-x: 52vw;
          --from-y: -54dvh;
          --to-x: calc(-50% + 0.2rem);
          --to-y: calc(-50% + 8.1rem);
          animation-delay: 1.84s;
        }

        @keyframes splash-logo-flight {
          0% {
            opacity: 0;
            transform: translate3d(44vw, 44dvh, 0) scale(0.46);
          }
          20% {
            opacity: 1;
          }
          76% {
            opacity: 1;
            transform: translate3d(-50%, -50%, 0) scale(1);
          }
          100% {
            opacity: 0;
            transform: translate3d(-50%, -50%, 0) scale(0.92);
          }
        }

        @keyframes splash-word-arrive {
          0% {
            opacity: 0;
            transform: translate3d(var(--from-x), var(--from-y), 0) scale(0.96);
          }
          22% {
            opacity: 1;
          }
          100% {
            opacity: 1;
            transform: translate3d(var(--to-x), var(--to-y), 0) scale(1);
          }
        }
      `}</style>
    </div>
  );
}
