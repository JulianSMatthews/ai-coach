"use client";

import { useEffect, useState } from "react";

type CarouselDotsProps = {
  containerId: string;
  count: number;
};

export default function CarouselDots({ containerId, count }: CarouselDotsProps) {
  const [activeIndex, setActiveIndex] = useState(0);

  useEffect(() => {
    const container = document.getElementById(containerId);
    if (!container) return;
    const items = Array.from(container.querySelectorAll<HTMLElement>("[data-carousel-item]"));
    if (!items.length) return;

    const update = () => {
      const center = container.scrollLeft + container.clientWidth / 2;
      let bestIdx = 0;
      let bestDist = Number.POSITIVE_INFINITY;
      items.forEach((el, idx) => {
        const elCenter = el.offsetLeft + el.clientWidth / 2;
        const dist = Math.abs(elCenter - center);
        if (dist < bestDist) {
          bestDist = dist;
          bestIdx = idx;
        }
      });
      setActiveIndex(bestIdx);
    };

    let raf = 0;
    const onScroll = () => {
      if (raf) return;
      raf = window.requestAnimationFrame(() => {
        raf = 0;
        update();
      });
    };

    update();
    container.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", update);

    return () => {
      container.removeEventListener("scroll", onScroll);
      window.removeEventListener("resize", update);
      if (raf) {
        window.cancelAnimationFrame(raf);
      }
    };
  }, [containerId, count]);

  if (count <= 1) return null;

  return (
    <div className="mt-3 flex items-center justify-center gap-2">
      {Array.from({ length: count }).map((_, idx) => (
        <span
          key={`dot-${idx}`}
          className="h-2 w-2 rounded-full"
          style={{ background: idx === activeIndex ? "var(--accent)" : "#e7e1d6" }}
        />
      ))}
    </div>
  );
}
