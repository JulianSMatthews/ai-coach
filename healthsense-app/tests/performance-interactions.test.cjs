const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const ts = require('typescript');
const source = ts.createSourceFile('panel.tsx', fs.readFileSync('src/app/assessment/[userId]/chat/LatestAssessmentPanel.tsx', 'utf8'), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
const expressions = {};
function visit(node) {
  if (ts.isJsxAttribute(node) && /^on(Touch|Pointer|LostPointer)/.test(node.name.getText(source)) && node.initializer?.expression) {
    const body = node.initializer.expression.getText(source);
    if (body.includes('historySwipeRef')) expressions[node.name.getText(source)] = body;
  }
  if (ts.isVariableDeclaration(node) && node.name.getText(source) === 'canEditActiveWeek') expressions.canEdit = node.initializer.getText(source);
  ts.forEachChild(node, visit);
}
visit(source);
const utility = { exports: {} };
vm.runInNewContext(ts.transpileModule(fs.readFileSync('src/lib/pillarTrackerSummary.ts', 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText, utility);
function harness() {
  const calls = [];
  const env = { viewingLastWeek: true, loadingDetail: false, historySwipeRef: { current: null }, setHistorySwipeOffset: () => {}, historyWeeks: { previous: '2026-09-14', next: null }, trackerPillarKey: 'nutrition', trackerSwipeWeek: utility.exports.trackerSwipeWeek, loadTrackerDetail: (...args) => calls.push(args) };
  const handlers = Object.fromEntries(Object.entries(expressions).filter(([key]) => key !== 'canEdit').map(([key, value]) => [key, vm.runInNewContext(ts.transpileModule(`(${value})`, { compilerOptions: { target: ts.ScriptTarget.ES2020 } }).outputText, env)]));
  return { handlers, calls };
}
test('phone swipe requests previous week despite pointer cancellation', () => {
  const { handlers: h, calls } = harness();
  h.onTouchStart({ touches: [{ identifier: 1, clientX: 200, clientY: 20 }] });
  h.onPointerCancel({ pointerType: 'touch' });
  h.onLostPointerCapture({ pointerType: 'touch' });
  h.onPointerUp({ pointerType: 'touch' });
  h.onTouchEnd({ changedTouches: [{ identifier: 1, clientX: 100, clientY: 25 }] });
  assert.deepEqual(calls, [['nutrition', '2026-09-14']]);
});
test('vertical scrolling and cancelled touches do not request another week', () => {
  const { handlers: h, calls } = harness();
  h.onTouchStart({ touches: [{ identifier: 1, clientX: 200, clientY: 20 }] });
  h.onTouchEnd({ changedTouches: [{ identifier: 1, clientX: 170, clientY: 150 }] });
  h.onTouchStart({ touches: [{ identifier: 2, clientX: 200, clientY: 20 }] });
  h.onTouchCancel();
  h.onTouchEnd({ changedTouches: [{ identifier: 2, clientX: 100, clientY: 20 }] });
  assert.equal(calls.length, 0);
});
test('Performance blocks editing editable Sunday; Yesterday retains catch-up', () => {
  const detail = { pillar: { is_editable: true, is_current_week: false } };
  assert.equal(vm.runInNewContext(expressions.canEdit, { performanceMode: true, detail }), false);
  assert.equal(vm.runInNewContext(expressions.canEdit, { performanceMode: false, detail }), true);
});
