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
