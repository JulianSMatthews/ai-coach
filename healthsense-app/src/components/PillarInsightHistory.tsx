"use client";

import { useCallback, useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";

type PillarInsightHistoryProps = {
  userId: string;
  pillarKey: string;
  pillarLabel: string;
  currentQuote: string;
  currentDate?: string | null;
};

type SavedInsight = {
  id: number;
  quote_date: string;
  quote: string;
};

type InsightPage = {
  insights: SavedInsight[];
  loaded: boolean;
  hasMore: boolean;
  nextBefore: string | null;
};

const EMPTY_PAGE: InsightPage = { insights: [], loaded: false, hasMore: true, nextBefore: null };

function validIsoDay(value: unknown): value is string {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const date = new Date(`${value}T00:00:00Z`);
  return Number.isFinite(date.getTime()) && date.toISOString().slice(0, 10) === value;
}

function insightDateLabel(day: string, currentDate?: string | null) {
  const label = new Intl.DateTimeFormat("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  }).format(new Date(`${day}T00:00:00Z`));
  return day === currentDate ? `Today · ${label}` : label;
}

function InsightText({ quote }: { quote: string }) {
  const lines = quote.split(/\n+/).map((line) => line.trim()).filter(Boolean);
  const author = lines.length >= 3 ? lines[lines.length - 1] : "";
  const body = author ? lines.slice(0, -1) : lines;
  return (
    <div className="space-y-3 text-[1.18rem] leading-8 text-current opacity-80">
      {body.map((line, index) => <p key={index}>{line}</p>)}
      {author ? (
        <p className="pt-1 text-right text-[0.9rem] font-semibold uppercase tracking-[0.12em] opacity-70">
          {author}
        </p>
      ) : null}
    </div>
  );
}

function InsightHistoryPanel({ userId, pillarKey, pillarLabel, currentQuote, currentDate }: PillarInsightHistoryProps) {
  const wrapperRef = useRef<HTMLDivElement | null>(null);
  const scrollerRef = useRef<HTMLDivElement | null>(null);
  const contentRef = useRef<HTMLDivElement | null>(null);
  const pageRef = useRef<InsightPage>(EMPTY_PAGE);
  const requestRef = useRef<AbortController | null>(null);
  const generationRef = useRef(0);
  const loadingRef = useRef(false);
  const failedRef = useRef(false);
  const pendingDownScrollRef = useRef(false);
  const gestureRef = useRef<{
    pointerId: number;
    axis: "horizontal" | "vertical" | null;
    startX: number;
    startY: number;
    lastY: number;
  } | null>(null);
  const [activated, setActivated] = useState(false);
  const [page, setPage] = useState<InsightPage>(EMPTY_PAGE);
  const [loading, setLoading] = useState(false);
  const [failed, setFailed] = useState(false);
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

  const loadPage = useCallback(async () => {
    const previous = pageRef.current;
    if (loadingRef.current || (previous.loaded && !previous.hasMore)) return;
    const before = previous.loaded ? previous.nextBefore : null;
    if (previous.loaded && !before) return;
    const generation = generationRef.current;
    const controller = new AbortController();
    requestRef.current = controller;
    loadingRef.current = true;
    failedRef.current = false;
    setLoading(true);
    setFailed(false);
    try {
      const params = new URLSearchParams({ userId, pillarKey, limit: "10" });
      if (before) params.set("before", before);
      const response = await fetch(`/api/pillar-tracker/insights?${params.toString()}`, {
        method: "GET",
        cache: "no-store",
        signal: controller.signal,
      });
      if (!response.ok) throw new Error("Insight history unavailable");
      const payload = await response.json();
      if (controller.signal.aborted || generation !== generationRef.current) return;
      if (
        (payload.pillar_key && payload.pillar_key !== pillarKey) ||
        (payload.user_id != null && String(payload.user_id) !== userId) ||
        !Array.isArray(payload.insights)
      ) throw new Error("Invalid insight history");
      const incoming: SavedInsight[] = payload.insights.filter((row: SavedInsight) =>
        row && Number.isInteger(row.id) && validIsoDay(row.quote_date) && typeof row.quote === "string" && row.quote.trim(),
      );
      const byDay = new Map(previous.insights.map((row) => [row.quote_date, row]));
      incoming.forEach((row) => byDay.set(row.quote_date, row));
      const insights = Array.from(byDay.values()).sort((left, right) => right.quote_date.localeCompare(left.quote_date));
      const nextBefore = validIsoDay(payload.next_before) && (!before || payload.next_before < before)
        ? payload.next_before : null;
      const next = {
        insights,
        loaded: true,
        hasMore: payload.has_more === true && nextBefore !== null,
        nextBefore,
      };
      pageRef.current = next;
      setPage(next);
    } catch {
      if (controller.signal.aborted || generation !== generationRef.current) return;
      failedRef.current = true;
      pendingDownScrollRef.current = false;
      setFailed(true);
    } finally {
      if (generation === generationRef.current && requestRef.current === controller) {
        loadingRef.current = false;
        requestRef.current = null;
        setLoading(false);
      }
    }
  }, [pillarKey, userId]);

  // Cards enter the horizontal carousel one at a time; avoid fetching unseen pillars.
  useEffect(() => {
    const node = wrapperRef.current;
    if (!node) return;
    if (typeof IntersectionObserver === "undefined") {
      setActivated(true);
      return;
    }
    const observer = new IntersectionObserver((entries) => {
      if (!entries.some((entry) => entry.isIntersecting)) return;
      setActivated(true);
      observer.disconnect();
    }, { threshold: 0.01 });
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    pendingDownScrollRef.current = false;
  }, [currentDate, currentQuote]);

  useEffect(() => {
    generationRef.current += 1;
    requestRef.current?.abort();
    loadingRef.current = false;
    failedRef.current = false;
    pageRef.current = EMPTY_PAGE;
    setPage(EMPTY_PAGE);
    setLoading(false);
    setFailed(false);
    if (scrollerRef.current) scrollerRef.current.scrollTop = 0;
    if (activated) void loadPage();
    return () => {
      generationRef.current += 1;
      requestRef.current?.abort();
      loadingRef.current = false;
    };
  }, [activated, currentDate, currentQuote, loadPage]);

  useEffect(() => {
    const frame = window.requestAnimationFrame(() => {
      if (pendingDownScrollRef.current && !loading) {
        pendingDownScrollRef.current = false;
        scroll(80);
      }
      updateDirections();
    });
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(updateDirections);
    if (scrollerRef.current) observer?.observe(scrollerRef.current);
    if (contentRef.current) observer?.observe(contentRef.current);
    window.addEventListener("resize", updateDirections);
    return () => {
      window.cancelAnimationFrame(frame);
      observer?.disconnect();
      window.removeEventListener("resize", updateDirections);
    };
  }, [currentQuote, failed, loading, page, scroll, updateDirections]);

  const loadNearBottom = useCallback((node: HTMLDivElement) => {
    if (!activated) {
      setActivated(true);
      return;
    }
    if (node.clientHeight <= 0 || failedRef.current || !pageRef.current.loaded || !pageRef.current.hasMore) return;
    if (node.scrollHeight - node.clientHeight - node.scrollTop <= 120) void loadPage();
  }, [activated, loadPage]);

  const beginGesture = useCallback((event: ReactPointerEvent<HTMLDivElement>) => {
    if (event.pointerType === "mouse" || !event.isPrimary) return;
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
    loadNearBottom(event.currentTarget);
  }, [loadNearBottom]);

  const endGesture = useCallback((event: ReactPointerEvent<HTMLDivElement>) => {
    const gesture = gestureRef.current;
    if (!gesture || gesture.pointerId !== event.pointerId) return;
    gestureRef.current = null;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
  }, []);

  const downAvailable = directions.down || !page.loaded || page.hasMore;
  const scrollDown = () => {
    const node = scrollerRef.current;
    if (!node) return;
    if (!activated) {
      pendingDownScrollRef.current = true;
      setActivated(true);
      return;
    }
    const atBottom = node.scrollTop + node.clientHeight >= node.scrollHeight - 2;
    if (atBottom && (!pageRef.current.loaded || pageRef.current.hasMore)) {
      pendingDownScrollRef.current = true;
      void loadPage();
    } else {
      scroll(80);
      loadNearBottom(node);
    }
  };

  return (
    <div ref={wrapperRef} className="relative min-h-[11.75rem] w-full flex-1 sm:min-h-[13rem]">
      <div
        ref={scrollerRef}
        className="absolute inset-0 overflow-x-hidden overflow-y-auto overscroll-y-contain pr-8 [scrollbar-color:var(--border-strong)_transparent] [scrollbar-gutter:stable] [scrollbar-width:thin] [&::-webkit-scrollbar-thumb]:rounded-full [&::-webkit-scrollbar-thumb]:bg-[var(--border-strong)] [&::-webkit-scrollbar-track]:bg-transparent [&::-webkit-scrollbar]:w-1.5"
        style={{
          WebkitOverflowScrolling: "touch",
          touchAction: "pan-x",
          maskImage: directions.down ? "linear-gradient(to bottom, black calc(100% - 20px), transparent)" : undefined,
        }}
        role="region"
        aria-label={`${pillarLabel} insights. Scroll down for earlier insights and up for newer insights.`}
        aria-busy={loading}
        tabIndex={0}
        onPointerDown={beginGesture}
        onPointerMove={moveGesture}
        onPointerUp={endGesture}
        onPointerCancel={endGesture}
        onLostPointerCapture={endGesture}
        onScroll={(event) => {
          updateDirections();
          loadNearBottom(event.currentTarget);
        }}
        onKeyDown={(event) => {
          if (["ArrowDown", "PageDown", "End"].includes(event.key)) loadNearBottom(event.currentTarget);
        }}
      >
        <div ref={contentRef}>
          {page.insights.length ? page.insights.map((insight, index) => (
            <section key={`${insight.quote_date}-${insight.id}`} className={index ? "mt-6 border-t border-[var(--border)] pt-5" : ""}>
              <p className="mb-3 text-[0.72rem] font-semibold uppercase tracking-[0.12em] text-current opacity-65">
                <time dateTime={insight.quote_date}>{insightDateLabel(insight.quote_date, currentDate)}</time>
              </p>
              <InsightText quote={insight.quote} />
            </section>
          )) : (
            <section>
              <p className="mb-3 text-[0.72rem] font-semibold uppercase tracking-[0.12em] text-current opacity-65">Latest insight</p>
              <InsightText quote={currentQuote} />
            </section>
          )}
          {loading ? <p className="mt-5 text-sm text-current opacity-70" role="status">Loading previous insights…</p> : null}
          {failed ? (
            <div className="mt-5 text-sm text-current">
              <p className="opacity-70" role="status">Previous insights are unavailable.</p>
              <button
                type="button"
                onClick={() => void loadPage()}
                className="mt-2 min-h-10 rounded-full border border-[var(--border)] bg-[var(--surface)] px-3 py-2 font-semibold text-[var(--text-primary)]"
              >
                Try again
              </button>
            </div>
          ) : null}
          {page.loaded && !page.hasMore && page.insights.length <= 1 ? (
            <p className="mt-5 text-sm text-current opacity-60">No earlier insights yet.</p>
          ) : null}
        </div>
      </div>
      {directions.up || downAvailable ? (
        <div className="absolute right-2 top-1/2 z-10 flex -translate-y-1/2 flex-col overflow-hidden rounded-full border border-[var(--border)] bg-[var(--surface)] shadow-sm">
          <button
            type="button"
            disabled={!directions.up}
            onClick={() => scroll(-80)}
            className="flex h-7 w-7 items-center justify-center text-sm leading-none text-[var(--text-primary)] disabled:opacity-25"
            aria-label={`Scroll ${pillarLabel} insights up towards the latest insight`}
          >
            ↑
          </button>
          <button
            type="button"
            disabled={!downAvailable || (loading && !directions.down)}
            onClick={scrollDown}
            className="flex h-7 w-7 items-center justify-center border-t border-[var(--border)] text-sm leading-none text-[var(--text-primary)] disabled:opacity-25"
            aria-label={`Scroll ${pillarLabel} insights down for earlier insights`}
          >
            ↓
          </button>
        </div>
      ) : null}
    </div>
  );
}

export default function PillarInsightHistory(props: PillarInsightHistoryProps) {
  // Remount scoped state and abort outstanding requests when the member or pillar changes.
  return <InsightHistoryPanel key={`${props.userId}:${props.pillarKey}`} {...props} />;
}
