const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const ts = require('typescript');

const compiled = ts.transpileModule(fs.readFileSync('src/lib/pillarProgress.ts', 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2017 },
}).outputText;
const context = { exports: {}, fetch, Date };
vm.runInNewContext(compiled, context);
const { progressScoreLabel, progressStatusLabel, progressStatusColor, conceptProgressAriaLabel, sortProgressPillars, requestConceptGuidance } = context.exports;

test('absent and non-finite scores stay grey while recorded zero stays scored', () => {
  assert.equal(progressScoreLabel(null), '—');
  assert.equal(progressScoreLabel(undefined), '—');
  assert.equal(progressScoreLabel(NaN), '—');
  assert.equal(progressScoreLabel(0), '0');
  assert.equal(progressStatusLabel('red', null), 'Not scored');
  assert.equal(progressStatusLabel('grey', null), 'Not scored');
  assert.equal(progressStatusLabel('red', 0), 'Needs attention');
  assert.equal(progressStatusColor('red', null), progressStatusColor('grey', null));
  assert.notEqual(progressStatusColor('red', 0), progressStatusColor('grey', null));
});

test('backend traffic-light status is respected without reclassifying its numeric score', () => {
  assert.equal(progressStatusLabel('green', 40), 'On track');
  assert.equal(progressStatusLabel('amber', 90), 'Building');
  assert.equal(progressStatusLabel('grey', 0), 'Not scored');
});

test('circles announce concept, status and score and distinguish evidence-only circles', () => {
  assert.equal(conceptProgressAriaLabel({ label: 'Contribution', score: 0, status: 'red', scored_days_count: 1 }),
    'Contribution: Needs attention, 0 out of 100. Get guidance');
  assert.equal(conceptProgressAriaLabel({ label: 'Adaptability', score: null, status: 'grey', scored_days_count: 0 }),
    'Adaptability: Not scored. View check-ins');
});

test('pillars follow the visible app order without mutating the API response', () => {
  const input = ['training', 'purpose', 'nutrition', 'recovery', 'reflection', 'resilience'].map(pillar_key => ({ pillar_key }));
  assert.equal(sortProgressPillars(input).map(item => item.pillar_key).join(','), 'reflection,purpose,resilience,recovery,nutrition,training');
  assert.equal(input[0].pillar_key, 'training');
});

const selection = () => ({ userId: '42', pillarKey: 'purpose', conceptKey: 'contribution_connection', weekStart: '2026-11-16', through: '2026-11-18', signal: new AbortController().signal });
const guidance = (overrides = {}) => ({ source: 'ai', pillar_key: 'purpose', concept_key: 'contribution_connection', week_start: '2026-11-16', through: '2026-11-18', insight: 'You contributed on two answered days.', action: 'Choose one small act of kindness.', reflection: 'What made contributing feel possible?', ...overrides });

test('guidance request sends only the selected concept and preserves cancellation', async () => {
  const picked = selection();
  const result = await requestConceptGuidance(picked, async (url, options) => {
    assert.equal(url, '/api/pillar-progress/coaching');
    assert.equal(options.method, 'POST');
    assert.deepEqual(JSON.parse(options.body), { userId: '42', pillarKey: 'purpose', conceptKey: 'contribution_connection' });
    assert.equal(options.signal, picked.signal);
    assert.equal(options.cache, 'no-store');
    return Response.json(guidance());
  });
  assert.equal(result.concept_key, picked.conceptKey);
});

test('other concepts, weeks, non-AI and missing guidance are rejected without a fallback', async () => {
  for (const overrides of [
    { pillar_key: 'reflection' }, { concept_key: 'values_alignment' },
    { week_start: '2026-11-09' }, { through: '2026-11-17' },
    { source: 'fallback' }, { action: '' }, { reflection: null },
  ]) {
    await assert.rejects(requestConceptGuidance(selection(), async () => Response.json(guidance(overrides))), /check-ins may have changed/);
  }
});

test('AI service errors remain explicit errors', async () => {
  await assert.rejects(requestConceptGuidance(selection(), async () => Response.json({ error: 'AI guidance is unavailable right now.' }, { status: 503 })), /AI guidance is unavailable/);
});
