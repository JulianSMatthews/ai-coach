const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const ts = require('typescript');
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');

const code = ts.transpileModule(fs.readFileSync('src/components/AppNav.tsx', 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2017, esModuleInterop: true },
}).outputText;
const exportsForNav = {};
vm.runInNewContext(code, {
  exports: exportsForNav,
  require(name) {
    if (name === 'next/navigation') return { useRouter: () => ({ refresh() {} }) };
    if (name === 'next/link') return { __esModule: true, default: ({ children, ...props }) => React.createElement('a', props, children) };
    if (name === '@/components/LogoutButton') return { __esModule: true, default: () => null };
    if (name === '@/components/ui') return { Badge: ({ label }) => React.createElement('span', null, label) };
    if (name === '@/lib/pillarTrackerSummary') return { PILLAR_TRACKER_OVERALL_SCORE_EVENT: 'score-updated' };
    return require(name);
  },
});

test('signed-in users can open progress in an empty week without a fabricated zero', () => {
  const html = renderToStaticMarkup(React.createElement(exportsForNav.default, { userId: '42', overallScore: null }));
  assert.match(html, /aria-label="Open pillar progress"/);
  const entry = html.match(/<button[^>]*aria-label="Open pillar progress"[\s\S]*?<\/button>/)?.[0];
  assert.ok(entry);
  assert.match(entry, />—<\/span>/);
  assert.doesNotMatch(entry, />0<\/span>/);
  assert.match(entry, /rgba\(133,128,120,0.4\)/);
});

test('a recorded zero remains visible as zero in the progress entry', () => {
  const html = renderToStaticMarkup(React.createElement(exportsForNav.default, { userId: '42', overallScore: 0 }));
  assert.match(html, /aria-label="Open pillar progress"/);
  assert.match(html, />0<\/span>/);
});

function progressEntryHarness() {
  const source = ts.createSourceFile('panel.tsx', fs.readFileSync('src/app/assessment/[userId]/chat/LatestAssessmentPanel.tsx', 'utf8'), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  let callback;
  function visit(node) {
    if (ts.isVariableDeclaration(node) && node.name.getText(source) === 'openObjectivesModal') callback = node.initializer.arguments[0].getText(source);
    ts.forEachChild(node, visit);
  }
  visit(source);
  assert.ok(callback);
  const state = { activeDock: 'learn', summaryVisible: false, modalOpen: false, editingGoals: true, progressVersion: 0, progressPillarKey: 'training' };
  const events = [];
  const logs = [];
  const context = {
    setStreakSectionOpen() {}, setSelectedPillarKey() {}, setBiometricsModalOpen() {}, setSelectedObjectivesSection() {}, setBiometricsActionError() {},
    logUserAppEvent(name, detail) { logs.push({ name, detail: JSON.parse(JSON.stringify(detail)) }); },
    setActiveDockKey(value) { state.activeDock = value; },
    setSummaryPanelVisible(value) { state.summaryVisible = value; },
    setObjectivesModalOpen(value) { state.modalOpen = value; },
    setEditingObjectives(value) { state.editingGoals = value; },
    setProgressPillarKey(value) { state.progressPillarKey = value; },
    setProgressOpenVersion(update) { state.progressVersion = update(state.progressVersion); },
    window: { dispatchEvent(event) { events.push(event); } },
    CustomEvent: class { constructor(type, options) { this.type = type; this.detail = options.detail; } },
  };
  const open = vm.runInNewContext(ts.transpileModule(`(${callback})`, { compilerOptions: { target: ts.ScriptTarget.ES2017 } }).outputText, context);
  return { state, events, logs, open, source };
}

function cueScoreButton(source, openObjectivesModal, pillarKey, label, score) {
  const buttons = [];
  function hasScoreRing(node) {
    if ((ts.isJsxSelfClosingElement(node) || ts.isJsxOpeningElement(node)) && node.tagName.getText(source) === 'WeeklyScoreRing') return true;
    return ts.forEachChild(node, hasScoreRing) || false;
  }
  function visit(node) {
    if (ts.isJsxElement(node) && node.openingElement.tagName.getText(source) === 'button' && hasScoreRing(node)) buttons.push(node);
    ts.forEachChild(node, visit);
  }
  visit(source);
  assert.equal(buttons.length, 1, 'Cue-card score ring must have its own native button');
  const buttonExports = {};
  vm.runInNewContext(ts.transpileModule(`exports.button = (${buttons[0].getText(source)});`, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2017 },
  }).outputText, {
    exports: buttonExports, require, openObjectivesModal, pillarKey, pillar: { label }, score,
    palette: { accent: '#0f8b8d' },
    WeeklyScoreRing: ({ value }) => React.createElement('span', null, value == null ? '—' : value),
  });
  return buttonExports.button;
}

test('opening progress from Learn switches to the visible check-in surface and clears a previous pillar entry', () => {
  const { state, events, logs, open } = progressEntryHarness();
  open();
  assert.deepEqual(state, { activeDock: 'checkin', summaryVisible: true, modalOpen: true, editingGoals: false, progressVersion: 1, progressPillarKey: null });
  assert.equal(events[0].type, 'healthsense-home-surface');
  assert.equal(events[0].detail.surface, 'blank');
  assert.equal(events[0].detail.source, 'summary');
  assert.deepEqual(logs, [{ name: 'pillar_progress_open', detail: { source: 'overall_score' } }]);
});

test('a pillar entry is normalized and each reopening resets progress before the global entry returns to overview', () => {
  const { state, logs, open } = progressEntryHarness();
  open(' PURPOSE ');
  assert.equal(state.progressPillarKey, 'purpose');
  assert.equal(state.progressVersion, 1);
  assert.deepEqual(logs[0], { name: 'pillar_progress_open', detail: { source: 'pillar_score', pillarKey: 'purpose' } });
  open('purpose');
  assert.equal(state.progressPillarKey, 'purpose');
  assert.equal(state.progressVersion, 2);
  open();
  assert.equal(state.progressPillarKey, null);
  assert.equal(state.progressVersion, 3);
  assert.deepEqual(logs[2], { name: 'pillar_progress_open', detail: { source: 'overall_score' } });
});

test('cue-card score circles are accessible buttons that open their corresponding pillar, including zero and unscored values', () => {
  for (const [pillarKey, label, score] of [['purpose', 'Purpose', 78], ['nutrition', 'Nutrition', 0], ['resilience', 'Resilience', null]]) {
    const { state, open, source } = progressEntryHarness();
    const button = cueScoreButton(source, open, pillarKey, label, score);
    assert.equal(button.type, 'button');
    assert.equal(button.props.type, 'button');
    assert.equal(Boolean(button.props.disabled), false);
    assert.equal(button.props['aria-label'], `Open ${label} progress, ${score == null ? 'not scored' : `${score} out of 100`}`);
    assert.match(renderToStaticMarkup(button), /<button/);
    button.props.onClick();
    assert.equal(state.progressPillarKey, pillarKey);
    assert.equal(state.modalOpen, true);
    assert.equal(state.editingGoals, false);
    assert.equal(state.progressVersion, 1);
  }
});

function homeDockHarness() {
  const source = ts.createSourceFile('panel.tsx', fs.readFileSync('src/app/assessment/[userId]/chat/LatestAssessmentPanel.tsx', 'utf8'), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const buttons = {};
  let openSurface;
  let onSurfaceChange;
  function visit(node) {
    if (ts.isVariableDeclaration(node)) {
      if (node.name.getText(source) === 'openDailyMenuSurface') openSurface = node.initializer.getText(source);
      if (node.name.getText(source) === 'onHomeSurfaceChange') onSurfaceChange = node.initializer.getText(source);
    }
    if (ts.isJsxElement(node) && node.openingElement.tagName.getText(source) === 'button') {
      for (const label of ['Checkin', 'Insight', 'Learn']) {
        if (node.children.some(child => ts.isJsxElement(child) && child.children.some(text => ts.isJsxText(text) && text.text.trim() === label))) {
          buttons[label] = node.getText(source);
        }
      }
    }
    ts.forEachChild(node, visit);
  }
  visit(source);
  const state = { activeDockKey: 'checkin', summaryVisible: true, selectedPillarKey: 'nutrition', objectivesModalOpen: true, streakSectionOpen: true };
  const events = [];
  const bridgeCalls = [];
  const context = {
    exports: {}, require,
    get activeDockKey() { return state.activeDockKey; },
    get selectedPillarKey() { return state.selectedPillarKey; },
    get objectivesModalOpen() { return state.objectivesModalOpen; },
    get streakSectionOpen() { return state.streakSectionOpen; },
    closeTracker() { state.selectedPillarKey = null; },
    closeObjectivesModal() { state.objectivesModalOpen = false; },
    setSelectedPillarKey(value) { state.selectedPillarKey = value; },
    setStreakSectionOpen(value) { state.streakSectionOpen = value; },
    setObjectivesModalOpen(value) { state.objectivesModalOpen = value; },
    setBiometricsModalOpen() {},
    setActiveDockKey(value) { state.activeDockKey = value; },
    setSummaryPanelVisible(value) { state.summaryVisible = value; },
    homeDockButtonClassName: 'dock', homeDockButtonStyleActive: {}, homeDockButtonStyleInactive: {},
    InsightIcon: () => null, BiometricsIcon: () => null,
    window: { healthsenseSetHomeSurface(surface) { bridgeCalls.push(surface); }, dispatchEvent(event) { events.push(event); }, scrollTo() {} },
    CustomEvent: class { constructor(type, options) { this.type = type; this.detail = options?.detail; } },
  };
  const evaluate = expression => vm.runInNewContext(`(function () { ${ts.transpileModule(`exports.value = (${expression});`, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2017 },
  }).outputText} return exports.value; })()`, context);
  context.openDailyMenuSurface = evaluate(openSurface);
  return { state, events, bridgeCalls, button: label => evaluate(buttons[label]), receiveSurface: surface => evaluate(onSurfaceChange)({ detail: { surface } }) };
}

test('Insight opens its own surface from the bottom dock and closes overlapping views', () => {
  const h = homeDockHarness();
  const button = h.button('Insight');
  assert.equal(button.type, 'button');
  assert.equal(button.props.type, 'button');
  assert.equal(button.props['aria-pressed'], false);
  button.props.onClick();
  assert.deepEqual(h.state, { activeDockKey: 'insight', summaryVisible: false, selectedPillarKey: null, objectivesModalOpen: false, streakSectionOpen: false });
  assert.deepEqual(h.bridgeCalls, ['coach-insight']);
  assert.equal(h.events[0].type, 'healthsense-home-surface');
  assert.equal(h.events[0].detail.surface, 'coach-insight');
  assert.equal(h.events[0].detail.source, 'summary');
  assert.equal(h.button('Insight').props['aria-pressed'], true);
});

test('Insight, Learn and Checkin remain distinct and update the selected dock button', () => {
  const h = homeDockHarness();
  h.receiveSurface('coach-insight');
  assert.equal(h.state.activeDockKey, 'insight');
  assert.equal(h.state.summaryVisible, false);
  h.button('Learn').props.onClick();
  assert.equal(h.state.activeDockKey, 'learn');
  assert.equal(h.bridgeCalls.at(-1), 'insight');
  assert.equal(h.button('Insight').props['aria-pressed'], false);
  h.receiveSurface('coach-insight');
  h.button('Checkin').props.onClick();
  assert.equal(h.state.activeDockKey, 'checkin');
  assert.equal(h.state.summaryVisible, true);
  assert.equal(h.events.at(-2).detail.surface, 'blank');
});

test('the home content receives Insight separately from the education surface', () => {
  const source = ts.createSourceFile('chat.tsx', fs.readFileSync('src/app/assessment/[userId]/chat/AssessmentChatBox.tsx', 'utf8'), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  let callback;
  function visit(node) {
    if (ts.isVariableDeclaration(node) && node.name.getText(source) === 'onSurfaceChange') callback = node.initializer.getText(source);
    ts.forEachChild(node, visit);
  }
  visit(source);
  const state = {};
  const receive = vm.runInNewContext(ts.transpileModule(`(${callback})`, { compilerOptions: { target: ts.ScriptTarget.ES2017 } }).outputText, {
    modernHomeOnly: true,
    setHomeSurface(value) { state.surface = value; },
    setHomeSurfaceEntryMode(value) { state.entryMode = value; },
    setJourneyCompleted(value) { state.complete = value; },
  });
  receive({ detail: { surface: 'coach-insight', source: 'summary' } });
  assert.deepEqual(state, { surface: 'coach-insight', entryMode: 'summary', complete: false });
  receive({ detail: { surface: 'insight', source: 'summary' } });
  assert.equal(state.surface, 'insight');
});
