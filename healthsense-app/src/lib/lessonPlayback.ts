// Count played intervals, not the playhead: seeking to the end isn't watching.
export function mergePlayedRanges(existing: Array<[number, number]>, played: TimeRanges): Array<[number, number]> {
  const ranges = [...existing];
  for (let i = 0; i < played.length; i++) ranges.push([played.start(i), played.end(i)]);
  ranges.sort((a, b) => a[0] - b[0]);
  const merged: Array<[number, number]> = [];
  for (const [start, end] of ranges) {
    const previous = merged.at(-1);
    if (previous && start <= previous[1]) previous[1] = Math.max(previous[1], end);
    else merged.push([start, end]);
  }
  return merged;
}
export function playbackProgress(ranges: Array<[number, number]>, duration: number) {
  if (!Number.isFinite(duration) || duration <= 0) return null;
  const seconds = ranges.reduce((total, [start, end]) => total + Math.max(0, Math.min(duration, end) - Math.max(0, start)), 0);
  if (seconds <= 0) return null;
  return { watch_pct: Math.min(100, Math.round(seconds / duration * 1000) / 10), watched_seconds: Math.floor(seconds) };
}
