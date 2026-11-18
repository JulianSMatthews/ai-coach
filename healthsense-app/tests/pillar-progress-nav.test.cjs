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
