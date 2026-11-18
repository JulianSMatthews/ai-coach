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

test('opening progress from Learn switches to the visible check-in surface', () => {
  const source = ts.createSourceFile('panel.tsx', fs.readFileSync('src/app/assessment/[userId]/chat/LatestAssessmentPanel.tsx', 'utf8'), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  let callback;
  function visit(node) {
    if (ts.isVariableDeclaration(node) && node.name.getText(source) === 'openObjectivesModal') callback = node.initializer.arguments[0].getText(source);
    ts.forEachChild(node, visit);
  }
  visit(source);
  assert.ok(callback);
  const state = { activeDock: 'learn', summaryVisible: false, modalOpen: false, editingGoals: true, progressVersion: 0 };
  const events = [];
  const context = {
    setStreakSectionOpen() {}, setSelectedPillarKey() {}, setBiometricsModalOpen() {}, setSelectedObjectivesSection() {}, setBiometricsActionError() {}, logUserAppEvent() {},
    setActiveDockKey(value) { state.activeDock = value; },
    setSummaryPanelVisible(value) { state.summaryVisible = value; },
    setObjectivesModalOpen(value) { state.modalOpen = value; },
    setEditingObjectives(value) { state.editingGoals = value; },
    setProgressOpenVersion(update) { state.progressVersion = update(state.progressVersion); },
    window: { dispatchEvent(event) { events.push(event); } },
    CustomEvent: class { constructor(type, options) { this.type = type; this.detail = options.detail; } },
  };
  const open = vm.runInNewContext(ts.transpileModule(`(${callback})`, { compilerOptions: { target: ts.ScriptTarget.ES2017 } }).outputText, context);
  open();
  assert.deepEqual(state, { activeDock: 'checkin', summaryVisible: true, modalOpen: true, editingGoals: false, progressVersion: 1 });
  assert.equal(events[0].type, 'healthsense-home-surface');
  assert.equal(events[0].detail.surface, 'blank');
  assert.equal(events[0].detail.source, 'summary');
});
