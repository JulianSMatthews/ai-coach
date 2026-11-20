"use client";

import { useCallback, useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";

type PillarInsightProps = {
  pillarLabel: string;
  currentQuote: string;
};

export default function PillarInsight({ pillarLabel, currentQuote }: PillarInsightProps) {
  const scrollerRef = useRef<HTMLDivElement | null>(null);
  const contentRef = useRef<HTMLDivElement | null>(null);
  const gestureRef = useRef<{
    pointerId: number;
    axis: "horizontal" | "vertical" | null;
    startX: number;
    startY: number;
    lastY: number;
  } | null>(null);
  const [directions, setDirections] = useState({ up: false, down: false });

  const updateDirections = useCallback(() => {
    const node = scrollerRef.current;
    if (!node) return;
    const next = {
      up: node.scrollTop > 2,
      down: node.scrollTop + node.clientHeight < node.scrollHeight - 2,
    };
    setDirections((previous) => previous.up === next.up && previous.down === next.down ? previous : next);
  }, []);

  const scroll = useCallback((amount: number) => {
    const reducedMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    scrollerRef.current?.scrollBy({ top: amount, behavior: reducedMotion ? "auto" : "smooth" });
  }, []);

  useEffect(() => {
    if (scrollerRef.current) scrollerRef.current.scrollTop = 0;
    gestureRef.current = null;
    const frame = window.requestAnimationFrame(updateDirections);
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(updateDirections);
    if (scrollerRef.current) observer?.observe(scrollerRef.current);
    if (contentRef.current) observer?.observe(contentRef.current);
    window.addEventListener("resize", updateDirections);
    return () => {
      window.cancelAnimationFrame(frame);
      observer?.disconnect();
      window.removeEventListener("resize", updateDirections);
    };
  }, [currentQuote, updateDirections]);

  const cancelGesture = useCallback((event: ReactPointerEvent<HTMLDivElement>) => {
    const gesture = gestureRef.current;
    if (!gesture || gesture.pointerId !== event.pointerId) return;
    gestureRef.current = null;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
  }, []);

  const beginGesture = useCallback((event: ReactPointerEvent<HTMLDivElement>) => {
    const previous = gestureRef.current;
    gestureRef.current = null;
    if (previous && event.currentTarget.hasPointerCapture(previous.pointerId)) event.currentTarget.releasePointerCapture(previous.pointerId);
    if (event.pointerType === "mouse" || !event.isPrimary || previous) return;
    gestureRef.current = {
      pointerId: event.pointerId,
      axis: null,
      startX: event.clientX,
      startY: event.clientY,
      lastY: event.clientY,
    };
  }, []);

  const moveGesture = useCallback((event: ReactPointerEvent<HTMLDivElement>) => {
    const gesture = gestureRef.current;
    if (!gesture || gesture.pointerId !== event.pointerId) return;
    const totalX = event.clientX - gesture.startX;
    const totalY = event.clientY - gesture.startY;
    if (!gesture.axis && Math.max(Math.abs(totalX), Math.abs(totalY)) >= 6) {
      gesture.axis = Math.abs(totalX) > Math.abs(totalY) ? "horizontal" : "vertical";
      if (gesture.axis === "vertical") event.currentTarget.setPointerCapture(event.pointerId);
    }
    if (gesture.axis !== "vertical") return;
    event.preventDefault();
    event.currentTarget.scrollTop -= event.clientY - gesture.lastY;
    gesture.lastY = event.clientY;
  }, []);

  const lines = currentQuote.split(/\n+/).map((line) => line.trim()).filter(Boolean);
  const author = lines.length >= 3 ? lines[lines.length - 1] : "";
  const body = author ? lines.slice(0, -1) : lines;

  return (
    <div className="relative min-h-[11.75rem] w-full flex-1 sm:min-h-[13rem]">
      <div
        ref={scrollerRef}
        className="absolute inset-0 overflow-x-hidden overflow-y-auto overscroll-y-contain pr-8 [scrollbar-color:var(--border-strong)_transparent] [scrollbar-gutter:stable] [scrollbar-width:thin] [&::-webkit-scrollbar-thumb]:rounded-full [&::-webkit-scrollbar-thumb]:bg-[var(--border-strong)] [&::-webkit-scrollbar-track]:bg-transparent [&::-webkit-scrollbar]:w-1.5"
        style={{
          WebkitOverflowScrolling: "touch",
          touchAction: "pan-x",
          maskImage: directions.down ? "linear-gradient(to bottom, black calc(100% - 20px), transparent)" : undefined,
        }}
        role="region"
        aria-label={`${pillarLabel} insight. Scroll to read more.`}
        tabIndex={0}
        onPointerDown={beginGesture}
        onPointerMove={moveGesture}
        onPointerUp={cancelGesture}
        onPointerCancel={cancelGesture}
        onLostPointerCapture={cancelGesture}
        onScroll={updateDirections}
        onKeyDown={(event) => {
          if (["ArrowDown", "PageDown"].includes(event.key)) {
            event.preventDefault();
            scroll(event.key === "PageDown" ? Math.max(80, event.currentTarget.clientHeight * 0.8) : 80);
          } else if (["ArrowUp", "PageUp"].includes(event.key)) {
            event.preventDefault();
            scroll(event.key === "PageUp" ? -Math.max(80, event.currentTarget.clientHeight * 0.8) : -80);
          }
        }}
      >
        <div ref={contentRef} className="space-y-3 text-[1.18rem] leading-8 text-current opacity-80">
          {(body.length ? body : [currentQuote]).map((line, index) => <p key={index}>{line}</p>)}
          {author ? (
            <p className="pt-1 text-right text-[0.9rem] font-semibold uppercase tracking-[0.12em] opacity-70">
              {author}
            </p>
          ) : null}
        </div>
      </div>
      {directions.up || directions.down ? (
        <div className="absolute right-2 top-1/2 z-10 flex -translate-y-1/2 flex-col overflow-hidden rounded-full border border-[var(--border)] bg-[var(--surface)] shadow-sm">
          <button
            type="button"
            disabled={!directions.up}
            onClick={() => scroll(-80)}
            className="flex h-7 w-7 items-center justify-center text-sm leading-none text-[var(--text-primary)] disabled:opacity-25"
            aria-label={`Scroll ${pillarLabel} insight up`}
          >
            ↑
          </button>
          <button
            type="button"
            disabled={!directions.down}
            onClick={() => scroll(80)}
            className="flex h-7 w-7 items-center justify-center border-t border-[var(--border)] text-sm leading-none text-[var(--text-primary)] disabled:opacity-25"
            aria-label={`Scroll ${pillarLabel} insight down`}
          >
            ↓
          </button>
        </div>
      ) : null}
    </div>
  );
}
