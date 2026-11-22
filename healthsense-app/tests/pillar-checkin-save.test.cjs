// Exercise the real save handler with deferred network responses and controlled timers.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');

const source = ts.createSourceFile('panel.tsx', fs.readFileSync(path.join(__dirname,
  '../src/app/assessment/[userId]/chat/LatestAssessmentPanel.tsx'), 'utf8'),
ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
let saveExpression;
function visit(node) {
  if (ts.isVariableDeclaration(node) && node.name.getText(source) === 'saveTracker') {
    saveExpression = node.initializer.getText(source);
  }
  ts.forEachChild(node, visit);
}
visit(source);
assert.ok(saveExpression, 'The check-in save handler must exist');
const compiled = ts.transpileModule(`(${saveExpression})`, {
  compilerOptions: { target: ts.ScriptTarget.ES2017 },
}).outputText;
const constants = {};
for (const statement of source.statements) {
  if (!ts.isVariableStatement(statement)) continue;
  for (const declaration of statement.declarationList.declarations) {
    if (declaration.initializer && ts.isNumericLiteral(declaration.initializer)) {
      constants[declaration.name.getText(source)] = Number(declaration.initializer.text);
    }
  }
}

function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

function harness(fetchResponse = async () => Response.json({}), overrides = {}) {
  const originalDraft = { meaning_fulfilment: 3, values_alignment: 2, contribution_connection: 1 };
  const state = {
    saving: false, error: 'Earlier error', draft: { ...originalDraft }, closed: false,
    activeDock: 'checkin', summaryVisible: false, returnPillar: null,
  };
  const calls = [], refreshes = [], polls = [], events = [], scrolls = [], timers = new Map();
  const summary = deferred();
  let nextTimer = 0;
  const schedule = (callback, delay) => {
    const id = ++nextTimer;
    timers.set(id, { callback, delay });
    return id;
  };
  const clear = id => timers.delete(id);
  const cache = new Map([['purpose:default', {}], ['purpose:2026-11-21', {}], ['training:default', {}]]);
  const context = {
    ...constants, Error, AbortController,
    detail: { pillar: { pillar_key: 'purpose', today: '2026-11-21' } },
    canSave: true, canEditActiveWeek: true, userId: '42', activeDate: '2026-11-20',
    concepts: Object.keys(originalDraft).map(concept_key => ({ concept_key })),
    draft: state.draft, guidedTrackingActive: false, trackerReturnSurface: null,
    trackerDetailCacheRef: { current: cache },
    setSaving(value) { state.saving = value; },
    setSaveError(value) { state.error = value; },
    setActiveDockKey(value) { state.activeDock = value; },
    setSummaryPanelVisible(value) { state.summaryVisible = value; },
    setReturnToPillarKey(value) { state.returnPillar = value; },
    closeTracker() { state.closed = true; state.draft = {}; },
    normalizeError(text, fallback) {
      try { return JSON.parse(text).error || fallback; } catch { return text || fallback; }
    },
    async fetch(url, options) { calls.push({ url, options }); return fetchResponse(url, options); },
    refreshSummary(options) { refreshes.push(options); return summary.promise; },
    scrollToPillarCueCard(pillar) { scrolls.push(pillar); },
    refreshSummaryFromWorkerCache(...args) { polls.push(args); },
    setTimeout: schedule, clearTimeout: clear,
    window: { setTimeout: schedule, clearTimeout: clear, dispatchEvent(event) { events.push(event); } },
    CustomEvent: class { constructor(type, options = {}) { this.type = type; this.detail = options.detail; } },
    ...overrides,
  };
  const save = vm.runInNewContext(compiled, context);
  return {
    state, originalDraft, calls, refreshes, polls, events, scrolls, timers, cache, summary, save,
    timeout() {
      assert.equal(timers.size, 1, 'A pending save must have one timeout');
      const [id, timer] = timers.entries().next().value;
      assert.equal(timer.delay, 30000);
      timers.delete(id);
      timer.callback();
    },
  };
}

test('saving completes while the cached summary remains pending without starting coaching refresh', async () => {
  const h = harness();
  const completion = h.save();
  assert.equal(h.state.saving, true);
  await completion;
  assert.equal(h.state.saving, false);
  assert.equal(h.state.error, null);
  assert.equal(h.state.closed, true);
  assert.equal(h.state.summaryVisible, true);
  assert.equal(h.state.returnPillar, 'purpose');
  assert.equal(h.timers.size, 0, 'Successful requests clear the timeout');
  assert.equal(h.calls.length, 1);
  const request = h.calls[0];
  assert.equal(request.url, '/api/pillar-tracker/purpose');
  assert.equal(request.options.method, 'POST');
  assert.ok(request.options.signal instanceof AbortSignal);
  assert.deepEqual(JSON.parse(request.options.body), {
    userId: '42', score_date: '2026-11-20',
    entries: Object.entries(h.originalDraft).map(([concept_key, value]) => ({ concept_key, value })),
    skipQuoteGeneration: true,
  });
  assert.equal(h.refreshes.length, 1);
  assert.equal(h.refreshes[0], undefined, 'The home refresh always reads cached results');
  assert.deepEqual(h.polls, [], 'Saving must not poll for newly generated coaching');
  assert.deepEqual([...h.cache.keys()], ['training:default']);
  assert.equal(h.events.filter(event => event.type === 'healthsense-tracker-updated').length, 1);
  assert.deepEqual(h.scrolls, [], 'The save does not wait for summary completion');
  h.summary.resolve({});
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(h.scrolls, ['purpose']);
});

test('failed saves leave answers available and stop the saving state for a retry', async () => {
  const h = harness(async () => Response.json({ error: 'The server could not save this check-in.' }, { status: 503 }));
  await h.save();
  assert.equal(h.state.saving, false);
  assert.equal(h.state.error, 'The server could not save this check-in.');
  assert.equal(h.state.closed, false);
  assert.deepEqual(h.state.draft, h.originalDraft);
  assert.equal(h.timers.size, 0);
  assert.equal(h.refreshes.length, 0);
  assert.equal(h.events.length, 0);
  assert.equal(h.cache.size, 3, 'A failed save does not discard cached tracker details');
});

test('a stalled save times out without discarding answers or leaving the button stuck', async () => {
  const h = harness((_url, options) => new Promise((_resolve, reject) => {
    options.signal.addEventListener('abort', () => {
      const error = new Error('Request aborted'); error.name = 'AbortError'; reject(error);
    });
  }));
  const completion = h.save();
  assert.equal(h.state.saving, true);
  h.timeout();
  await completion;
  assert.equal(h.calls[0].options.signal.aborted, true);
  assert.equal(h.state.saving, false);
  assert.equal(h.state.error, 'Saving took too long. Your answers are still here. Please try again.');
  assert.equal(h.state.closed, false);
  assert.deepEqual(h.state.draft, h.originalDraft);
  assert.equal(h.timers.size, 0);
  assert.equal(h.refreshes.length, 0);
  assert.equal(h.events.length, 0);
});

test('an interrupted response body is not mistaken for a completed save', async () => {
  const h = harness(async () => ({
    ok: true,
    async text() { throw new Error('The connection was interrupted. Please try again.'); },
  }));
  await h.save();
  assert.equal(h.state.saving, false);
  assert.equal(h.state.error, 'The connection was interrupted. Please try again.');
  assert.equal(h.state.closed, false);
  assert.deepEqual(h.state.draft, h.originalDraft);
  assert.equal(h.timers.size, 0);
  assert.equal(h.refreshes.length, 0);
  assert.equal(h.events.length, 0);
});

test('incomplete and read-only check-ins do not submit or start saving', async () => {
  for (const overrides of [{ canSave: false }, { canEditActiveWeek: false }, { detail: null }]) {
    const h = harness(undefined, overrides);
    await h.save();
    assert.equal(h.calls.length, 0);
    assert.equal(h.state.saving, false);
    assert.equal(h.state.closed, false);
    assert.equal(h.timers.size, 0);
    assert.deepEqual(h.state.draft, h.originalDraft);
  }
});

function variableExpression(tree, name) {
  let expression;
  function find(node) {
    if (ts.isVariableDeclaration(node) && node.name.getText(tree) === name) {
      expression = node.initializer;
    }
    ts.forEachChild(node, find);
  }
  find(tree);
  assert.ok(expression, `Missing ${name}`);
  if (ts.isCallExpression(expression)) expression = expression.arguments[0];
  return ts.transpileModule(`(${expression.getText(tree)})`, {
    compilerOptions: { target: ts.ScriptTarget.ES2017 },
  }).outputText;
}

test('loading the home cards reads cached summaries without requesting generated coaching', async () => {
  const home = ts.createSourceFile('home.tsx', fs.readFileSync(path.join(__dirname,
    '../src/app/CoachHomeTrackerPanel.tsx'), 'utf8'), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const calls = [], payload = { today: '2026-11-21', pillars: [] };
  let summary, error;
  const load = vm.runInNewContext(variableExpression(home, 'loadSummary'), {
    userId: '42', cancelled: false, URLSearchParams, Error,
    fetch: async (url, options) => { calls.push({ url, options }); return Response.json(payload); },
    setSummary(value) { summary = value; }, setError(value) { error = value; },
  });
  await load();
  assert.deepEqual(JSON.parse(JSON.stringify(summary)), payload);
  assert.equal(error, null);
  assert.equal(calls.length, 1);
  const request = calls[0];
  assert.equal(request.options.method, 'GET');
  assert.equal(new URL(request.url, 'https://app.test').searchParams.get('skipQuoteGeneration'), 'true');
  assert.equal(new URL(request.url, 'https://app.test').pathname, '/api/pillar-tracker/summary');
});

test('the main home refresh also reads cached summaries by default', async () => {
  const calls = [], payload = { today: '2026-11-21', pillars: [] }, applied = [], scores = [];
  const refresh = vm.runInNewContext(variableExpression(source, 'refreshSummary'), {
    userId: '42', summaryRequestRef: { current: 0 }, URLSearchParams, Error,
    fetch: async (url, options) => { calls.push({ url, options }); return Response.json(payload); },
    normalizeError: (_text, fallback) => fallback,
    resolveMondayCueScores: async value => value,
    setSummary(value) { applied.push(value); },
    dispatchPillarTrackerOverallScore(value) { scores.push(value); },
  });
  await refresh();
  assert.equal(calls.length, 1);
  assert.equal(calls[0].options.method, 'GET');
  const url = new URL(calls[0].url, 'https://app.test');
  assert.equal(url.pathname, '/api/pillar-tracker/summary');
  assert.equal(url.searchParams.get('skipQuoteGeneration'), 'true');
  assert.equal(applied.length, 1);
  assert.equal(scores.length, 1);
});
