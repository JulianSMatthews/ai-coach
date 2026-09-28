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
