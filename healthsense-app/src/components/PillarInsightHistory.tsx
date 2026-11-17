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
  const navigationVersionRef = useRef(0);
  const selectedIndexRef = useRef(0);
  const activatedRef = useRef(false);
  const loadingRef = useRef(false);
  const gestureRef = useRef<{
    pointerId: number;
    axis: "horizontal" | "vertical" | null;
    startX: number;
    startY: number;
    lastY: number;
    atTop: boolean;
    atBottom: boolean;
    quote: string;
    version: number;
    pageDirection: "older" | "newer" | null;
  } | null>(null);
  const [activated, setActivated] = useState(false);
  const [page, setPage] = useState<InsightPage>(EMPTY_PAGE);
  const [selectedIndex, setSelectedIndex] = useState(0);
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

  const selectInsight = useCallback((index: number) => {
    if (index < 0 || index >= pageRef.current.insights.length) return;
    navigationVersionRef.current += 1;
    gestureRef.current = null;
    selectedIndexRef.current = index;
    setSelectedIndex(index);
    setFailed(false);
    if (scrollerRef.current) scrollerRef.current.scrollTop = 0;
    updateDirections();
  }, [updateDirections]);

  const loadPage = useCallback(async (): Promise<InsightPage | null> => {
    const previous = pageRef.current;
    if (loadingRef.current || (previous.loaded && !previous.hasMore)) return null;
    const before = previous.loaded ? previous.nextBefore : null;
    if (previous.loaded && !before) return null;
    const generation = generationRef.current;
    const controller = new AbortController();
    requestRef.current = controller;
    loadingRef.current = true;
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
      if (controller.signal.aborted || generation !== generationRef.current) return null;
      if (
        (payload.pillar_key && payload.pillar_key !== pillarKey) ||
        (payload.user_id != null && String(payload.user_id) !== userId) ||
        !Array.isArray(payload.insights)
      ) throw new Error("Invalid insight history");
      const incoming: SavedInsight[] = payload.insights.filter((row: SavedInsight) =>
        row && Number.isInteger(row.id) && validIsoDay(row.quote_date) &&
        (!before || row.quote_date < before) && typeof row.quote === "string" && row.quote.trim(),
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
      return next;
    } catch {
      if (controller.signal.aborted || generation !== generationRef.current) return null;
      setFailed(true);
      return null;
    } finally {
      if (generation === generationRef.current && requestRef.current === controller) {
        loadingRef.current = false;
        requestRef.current = null;
        setLoading(false);
      }
    }
  }, [pillarKey, userId]);

  const showOlder = useCallback(async () => {
    const previous = pageRef.current;
    const fromIndex = selectedIndexRef.current;
    if (fromIndex + 1 < previous.insights.length) {
      selectInsight(fromIndex + 1);
      return;
    }
    if (loadingRef.current || (previous.loaded && !previous.hasMore)) return;
    const version = ++navigationVersionRef.current;
    const generation = generationRef.current;
    const fromId = previous.insights[fromIndex]?.id;
    activatedRef.current = true;
    setActivated(true);
    const next = await loadPage();
    if (!next || generation !== generationRef.current || version !== navigationVersionRef.current || selectedIndexRef.current !== fromIndex) return;
    if (previous.loaded) {
      if (next.insights[fromIndex]?.id === fromId && next.insights[fromIndex + 1]) selectInsight(fromIndex + 1);
    } else if (next.insights[0]?.quote.trim() === currentQuote.trim() && next.insights[1]) {
      selectInsight(1);
    }
  }, [currentQuote, loadPage, selectInsight]);

  const showNewer = useCallback(() => {
    // Any move back cancels an older-page selection still waiting for the network.
    navigationVersionRef.current += 1;
    if (selectedIndexRef.current > 0) selectInsight(selectedIndexRef.current - 1);
  }, [selectInsight]);

  // Only fetch a pillar once its card becomes visible in the horizontal carousel.
  useEffect(() => {
    const node = wrapperRef.current;
    if (!node) return;
    if (typeof IntersectionObserver === "undefined") {
      activatedRef.current = true;
      setActivated(true);
      return;
    }
    const observer = new IntersectionObserver((entries) => {
      if (!entries.some((entry) => entry.isIntersecting)) return;
      activatedRef.current = true;
      setActivated(true);
      observer.disconnect();
    }, { threshold: 0.01 });
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    generationRef.current += 1;
    navigationVersionRef.current += 1;
    requestRef.current?.abort();
    loadingRef.current = false;
    gestureRef.current = null;
    pageRef.current = EMPTY_PAGE;
    selectedIndexRef.current = 0;
    setPage(EMPTY_PAGE);
    setSelectedIndex(0);
    setLoading(false);
    setFailed(false);
    if (scrollerRef.current) scrollerRef.current.scrollTop = 0;
    if (activatedRef.current) void loadPage();
    return () => {
      generationRef.current += 1;
      navigationVersionRef.current += 1;
      requestRef.current?.abort();
      loadingRef.current = false;
    };
  }, [currentDate, currentQuote, loadPage]);

  useEffect(() => {
    if (activated && !pageRef.current.loaded) void loadPage();
  }, [activated, loadPage]);

  useEffect(() => {
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
  }, [currentQuote, page, selectedIndex, scroll, updateDirections]);

  const readDown = useCallback((repeat = false, amount = 80) => {
    const node = scrollerRef.current;
    if (!node) return;
    if (node.scrollTop + node.clientHeight < node.scrollHeight - 2) scroll(amount);
    else if (!repeat) void showOlder();
  }, [scroll, showOlder]);

  const readUp = useCallback((repeat = false, amount = 80) => {
    const node = scrollerRef.current;
    if (!node) return;
    navigationVersionRef.current += 1;
    if (node.scrollTop > 2) scroll(-amount);
    else if (!repeat) showNewer();
  }, [scroll, showNewer]);

  const cancelGesture = useCallback((event: ReactPointerEvent<HTMLDivElement>) => {
    const gesture = gestureRef.current;
    if (!gesture || gesture.pointerId !== event.pointerId) return;
    gestureRef.current = null;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
  }, []);

  const beginGesture = useCallback((event: ReactPointerEvent<HTMLDivElement>) => {
    // Starting another interaction cancels a pending asynchronous move to an older insight.
    navigationVersionRef.current += 1;
    const previous = gestureRef.current;
    gestureRef.current = null;
    if (previous && event.currentTarget.hasPointerCapture(previous.pointerId)) event.currentTarget.releasePointerCapture(previous.pointerId);
    if (event.pointerType === "mouse" || !event.isPrimary || previous) return;
    const node = event.currentTarget;
    gestureRef.current = {
      pointerId: event.pointerId,
      axis: null,
      startX: event.clientX,
      startY: event.clientY,
      lastY: event.clientY,
      atTop: node.scrollTop <= 2,
      atBottom: node.scrollTop + node.clientHeight >= node.scrollHeight - 2,
      quote: pageRef.current.insights[selectedIndexRef.current]?.quote || currentQuote,
      version: navigationVersionRef.current,
      pageDirection: null,
    };
  }, [currentQuote]);

  const moveGesture = useCallback((event: ReactPointerEvent<HTMLDivElement>) => {
    const gesture = gestureRef.current;
    if (!gesture || gesture.pointerId !== event.pointerId) return;
    const totalX = event.clientX - gesture.startX;
    const totalY = event.clientY - gesture.startY;
    if (!gesture.axis && Math.max(Math.abs(totalX), Math.abs(totalY)) >= 6) {
      gesture.axis = Math.abs(totalX) > Math.abs(totalY) ? "horizontal" : "vertical";
      if (gesture.axis === "vertical") {
        gesture.pageDirection = totalY < 0 && gesture.atBottom ? "older" : totalY > 0 && gesture.atTop ? "newer" : null;
        event.currentTarget.setPointerCapture(event.pointerId);
      }
    }
    if (gesture.axis !== "vertical") return;
    event.preventDefault();
    event.currentTarget.scrollTop -= event.clientY - gesture.lastY;
    gesture.lastY = event.clientY;
  }, []);

  const endGesture = useCallback((event: ReactPointerEvent<HTMLDivElement>) => {
    const gesture = gestureRef.current;
    if (!gesture || gesture.pointerId !== event.pointerId) return;
    gestureRef.current = null;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
    if (gesture.version !== navigationVersionRef.current || gesture.quote !== (pageRef.current.insights[selectedIndexRef.current]?.quote || currentQuote)) return;
    const totalX = event.clientX - gesture.startX;
    const totalY = event.clientY - gesture.startY;
    if (gesture.axis !== "vertical" || Math.abs(totalY) < 55 || Math.abs(totalY) < Math.abs(totalX) * 1.25) return;
    if (gesture.pageDirection === "older" && totalY < 0) void showOlder();
    else if (gesture.pageDirection === "newer" && totalY > 0) showNewer();
  }, [currentQuote, showNewer, showOlder]);

  const selected = page.insights[selectedIndex] || null;
  const upAvailable = directions.up || selectedIndex > 0;
  const olderLoaded = selectedIndex + 1 < page.insights.length;
  const downAvailable = directions.down || olderLoaded || !page.loaded || page.hasMore;

  return (
    <div ref={wrapperRef} className="relative flex min-h-[13.5rem] w-full flex-1 flex-col sm:min-h-[14.75rem]">
      <p className="mb-3 shrink-0 pr-8 text-[0.72rem] font-semibold uppercase tracking-[0.12em] text-current opacity-65" aria-live="polite" aria-atomic="true">
        {selected ? <time dateTime={selected.quote_date}>{insightDateLabel(selected.quote_date, currentDate)}</time> : "Latest insight"}
      </p>
      <div className="relative min-h-0 flex-1">
        <div
          ref={scrollerRef}
          className="absolute inset-0 overflow-x-hidden overflow-y-auto overscroll-y-contain pr-8 [scrollbar-color:var(--border-strong)_transparent] [scrollbar-gutter:stable] [scrollbar-width:thin] [&::-webkit-scrollbar-thumb]:rounded-full [&::-webkit-scrollbar-thumb]:bg-[var(--border-strong)] [&::-webkit-scrollbar-track]:bg-transparent [&::-webkit-scrollbar]:w-1.5"
          style={{
            WebkitOverflowScrolling: "touch",
            touchAction: "pan-x",
            maskImage: directions.down ? "linear-gradient(to bottom, black calc(100% - 20px), transparent)" : undefined,
          }}
          role="region"
          aria-label={`${pillarLabel} insight. Scroll to read. At the end, swipe up or use the down arrow for an earlier insight.`}
          aria-busy={loading}
          tabIndex={0}
          onPointerDown={beginGesture}
          onPointerMove={moveGesture}
          onPointerUp={endGesture}
          onPointerCancel={cancelGesture}
          onLostPointerCapture={cancelGesture}
          onScroll={updateDirections}
          onWheel={(event) => {
            if (event.deltaY < 0) navigationVersionRef.current += 1;
          }}
          onKeyDown={(event) => {
            if (["ArrowDown", "PageDown"].includes(event.key)) {
              event.preventDefault();
              readDown(event.repeat, event.key === "PageDown" ? Math.max(80, event.currentTarget.clientHeight * 0.8) : 80);
            } else if (["ArrowUp", "PageUp"].includes(event.key)) {
              event.preventDefault();
              readUp(event.repeat, event.key === "PageUp" ? Math.max(80, event.currentTarget.clientHeight * 0.8) : 80);
            }
          }}
        >
          <div ref={contentRef}>
            <InsightText quote={selected?.quote || currentQuote} />
          </div>
        </div>
        {upAvailable || downAvailable ? (
          <div className="absolute right-2 top-1/2 z-10 flex -translate-y-1/2 flex-col overflow-hidden rounded-full border border-[var(--border)] bg-[var(--surface)] shadow-sm">
            <button
              type="button"
              disabled={!upAvailable}
              onClick={() => readUp()}
              className="flex h-7 w-7 items-center justify-center text-sm leading-none text-[var(--text-primary)] disabled:opacity-25"
              aria-label={`Scroll ${pillarLabel} insights up towards the latest insight`}
            >
              ↑
            </button>
            <button
              type="button"
              disabled={!downAvailable || (loading && !directions.down && !olderLoaded)}
              onClick={() => readDown()}
              className="flex h-7 w-7 items-center justify-center border-t border-[var(--border)] text-sm leading-none text-[var(--text-primary)] disabled:opacity-25"
              aria-label={`Scroll ${pillarLabel} insights down for earlier insights`}
            >
              ↓
            </button>
          </div>
        ) : null}
      </div>
      {loading ? <p className="mt-2 shrink-0 text-xs text-current opacity-70" role="status">Loading previous insights…</p> : null}
      {failed ? (
        <p className="mt-2 shrink-0 text-xs text-current" role="status">
          <span className="opacity-70">Previous insights are unavailable. </span>
          <button type="button" onClick={() => void (pageRef.current.loaded ? showOlder() : loadPage())} className="font-semibold underline underline-offset-2">Try again</button>
        </p>
      ) : null}
    </div>
  );
}

export default function PillarInsightHistory(props: PillarInsightHistoryProps) {
  // Remount scoped state and abort outstanding requests when the member or pillar changes.
  return <InsightHistoryPanel key={`${props.userId}:${props.pillarKey}`} {...props} />;
}
