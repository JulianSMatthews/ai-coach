const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const ts = require('typescript');
const events = [];
const context = { exports: {}, window: { dispatchEvent: event => events.push(event) }, CustomEvent: class { constructor(type, options) { this.type = type; this.detail = options.detail; } } };
const code = ts.transpileModule(fs.readFileSync('src/lib/pillarTrackerSummary.ts', 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText;
vm.runInNewContext(code, context);
const { resolvePillarTrackerOverallScore: score, dispatchPillarTrackerOverallScore: dispatch } = context.exports;
test('missing scores remain absent and actual zero remains a score', () => {
  assert.equal(score(null), null);
  assert.equal(score({ overall_score: null, pillars: [{ score: null }] }), null);
  assert.equal(score({ pillars: [{ score: null }, { score: 80 }] }), 80);
  assert.equal(score({ overall_score: 0 }), 0);
});
test('an empty week clears the previous overall score', () => {
  dispatch({ overall_score: 80 });
  dispatch({ overall_score: null });
  assert.equal(events.at(-1).detail.overallScore, null);
});
const { resolveMondayCueScores } = context.exports;
const mondaySummary = () => ({
  today: '2026-09-28', overall_score: null,
  pillars: [{ pillar_key: 'reflection', score: null, tracker_score: null, today_complete: false,
    checkin_options: [{ date: '2026-09-21', is_last_week: true }] }],
});
test('Monday cue card receives the same 82 score as the last-week detail', async () => {
  const input = mondaySummary();
  const result = await resolveMondayCueScores(input, async (pillar, anchor) => {
    assert.equal(pillar, 'reflection'); assert.equal(anchor, '2026-09-21');
    return { pillar: { tracker_score: 82, is_current_week: false } };
  });
  assert.equal(result.pillars[0].tracker_score, 82);
  assert.equal(result.overall_score, 82);
  assert.equal(result.pillars[0].today_complete, false);
  assert.equal(input.pillars[0].tracker_score, null);
});
test('today check-in switches only its pillar to the current score', async () => {
  const input = mondaySummary();
  input.pillars.push({ ...input.pillars[0], pillar_key: 'nutrition', tracker_score: 40, score: 40, today_complete: true });
  let calls = 0;
  const result = await resolveMondayCueScores(input, async (pillar) => {
    calls++; assert.equal(pillar, 'reflection');
    return { pillar: { tracker_score: 82, is_current_week: false } };
  });
  assert.equal(calls, 1);
  assert.equal(result.pillars[1].tracker_score, 40);
  assert.equal(result.overall_score, 61);
});
test('Tuesday and failed history loads leave summary untouched', async () => {
  const monday = mondaySummary();
  assert.equal(await resolveMondayCueScores(monday, async () => { throw new Error('offline'); }), monday);
  const tuesday = { ...monday, today: '2026-09-29' };
  assert.equal(await resolveMondayCueScores(tuesday, async () => { assert.fail('must not fetch'); }), tuesday);
});
test('historical zero is valid; accidental current-week response is ignored', async () => {
  const input = mondaySummary();
  const result = await resolveMondayCueScores(input, async () => ({ pillar: { tracker_score: 0, is_current_week: false } }));
  assert.equal(result.pillars[0].tracker_score, 0);
  assert.equal(await resolveMondayCueScores(input, async () => ({ pillar: { tracker_score: 90, is_current_week: true } })), input);
});
const { resolveTrackerDetailDisplayScore: detailScore } = context.exports;
test('Today on Monday shows the same previous-week score as its cue card', async () => {
  const summary = await resolveMondayCueScores(mondaySummary(), async () => ({ pillar: { tracker_score: 82, is_current_week: false } }));
  const detail = { pillar: { pillar_key: 'reflection', tracker_score: null, current_date: '2026-09-28', is_current_week: true }, days: [{ date: '2026-09-28', complete: false }] };
  assert.equal(detailScore(detail, summary), 82);
  detail.pillar.tracker_score = 60;
  detail.days[0].complete = true;
  assert.equal(detailScore(detail, summary), 60);
});
test('historical and Tuesday detail scores keep their own week', () => {
  const summary = mondaySummary(); summary.pillars[0].tracker_score = 82;
  assert.equal(detailScore({ pillar: { pillar_key: 'reflection', tracker_score: 74, is_current_week: false } }, summary), 74);
  assert.equal(detailScore({ pillar: { pillar_key: 'reflection', tracker_score: null, current_date: '2026-09-29', is_current_week: true } }, summary), null);
});
const { resolveTrackerDayStatus: dayStatus } = context.exports;
test('achieved Nutrition daily targets override an outdated orange status', () => {
  for (const concept_key of ['protein_intake', 'fruit_veg', 'hydration', 'processed_food']) {
    assert.equal(dayStatus({ concept_key, target_period: 'day' }, { target_met: true, daily_status: 'warning' }), 'success');
    assert.equal(dayStatus({ concept_key, target_period: 'day' }, { target_met: false, target_reached: true, daily_status: 'warning' }), 'warning');
  }
});
test('weekly progress does not override daily success or colour missing days', () => {
  assert.equal(dayStatus({ target_period: 'week' }, { target_reached: true, target_met: false, daily_status: 'warning' }), 'success');
  assert.equal(dayStatus({ target_period: 'week' }, { target_reached: false, target_met: true, daily_status: 'danger' }), 'danger');
  assert.equal(dayStatus({ target_period: 'day' }, { target_met: null, daily_status: null }), null);
});
const { formatTrackerWeekRange: weekRange, trackerWeekNavigation: navigation } = context.exports;
test('week dates use ordinals and handle month and year boundaries', () => {
  assert.equal(weekRange('2026-09-21', '2026-09-27'), '21st - 27th September 26');
  assert.equal(weekRange('2026-09-28', '2026-10-04'), '28th September - 4th October 26');
  assert.equal(weekRange('2026-12-28', '2027-01-03'), '28th December 26 - 3rd January 27');
  assert.equal(weekRange('2026-05-11', '2026-05-13'), '11th - 13th May 26');
  assert.equal(weekRange(null, null), '');
});
test('history can move backwards and forwards but stops at last week', () => {
  assert.equal(navigation('2026-09-21', '2026-09-28').previous, '2026-09-14');
  assert.equal(navigation('2026-09-21', '2026-09-28').next, null);
  assert.equal(navigation('2026-09-14', '2026-09-28').next, '2026-09-21');
  assert.equal(navigation('2026-10-19', '2026-10-28').next, null);
});
const { trackerSwipeWeek: swipeWeek } = context.exports;
test('performance swipes move through weeks and respect the newest boundary', () => {
  const weeks = navigation('2026-09-14', '2026-09-28');
  assert.equal(swipeWeek(80, 5, weeks), '2026-09-07');
  assert.equal(swipeWeek(-80, 5, weeks), '2026-09-21');
  assert.equal(swipeWeek(-80, 0, navigation('2026-09-21', '2026-09-28')), null);
});
test('taps and vertical scrolling do not change the performance week', () => {
  const weeks = navigation('2026-09-14', '2026-09-28');
  assert.equal(swipeWeek(10, 0, weeks), null);
  assert.equal(swipeWeek(50, 80, weeks), null);
  assert.equal(swipeWeek(-50, -60, weeks), null);
});
