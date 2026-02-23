"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

type AutoRefreshOnPendingProps = {
  enabled: boolean;
  intervalMs?: number;
};

export default function AutoRefreshOnPending({ enabled, intervalMs = 8000 }: AutoRefreshOnPendingProps) {
  const router = useRouter();

  useEffect(() => {
    if (!enabled) return;
    const timer = window.setInterval(() => {
      router.refresh();
    }, Math.max(2000, intervalMs));
    return () => window.clearInterval(timer);
  }, [enabled, intervalMs, router]);

  return null;
}
