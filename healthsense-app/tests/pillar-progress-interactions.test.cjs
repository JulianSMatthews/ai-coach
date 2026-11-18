// Exercise the real component with asynchronous requests and React hook state simulated.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const ts = require('typescript');

const compile = filename => ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2017 },
}).outputText;
const componentCode = compile('src/components/PillarProgressPanel.tsx');
const helperCode = compile('src/lib/pillarProgress.ts');

function sample() {
  const concept = (key, label, score, extra = {}) => ({
    concept_key: key, label, helper: `Question about ${label.toLowerCase()}?`, score,
    status: score == null ? 'grey' : score === 0 ? 'red' : 'green',
    answered_days_count: 1, scored_days_count: score == null ? 0 : 1,
    not_applicable_days_count: score == null ? 1 : 0, elapsed_days: 3,
    contribution_points: score == null ? null : score / 2,
    days: [{ date: '2026-11-18', label: 'Wed', value_label: score == null ? 'No challenges today' : 'Yes', score, not_applicable: score == null }], ...extra,
  });
  return {
    user_id: 42, week: { start: '2026-11-16', end: '2026-11-22', through: '2026-11-18', elapsed_days: 3 },
    score_explanation: 'Scores use your recorded check-ins.',
    pillars: [{ pillar_key: 'purpose', label: 'Purpose', score: 50, status: 'amber', completed_days_count: 1, elapsed_days: 3,
      score_explanation: 'An average of recorded answers.', concepts: [concept('values_alignment', 'Values', 100), concept('contribution_connection', 'Contribution', 0)] },
      { pillar_key: 'resilience', label: 'Resilience', score: null, status: 'grey', completed_days_count: 1, elapsed_days: 3,
        score_explanation: 'No scored answers.', concepts: [concept('adaptability', 'Adaptability', null)] }],
  };
}

function harness(coachRequest = async body => ({ source: 'ai', pillar_key: body.pillarKey, concept_key: body.conceptKey, week_start: '2026-11-16', through: '2026-11-18', insight: `Insight for ${body.conceptKey}`, action: 'One step.', reflection: 'A reflection?' })) {
  let slots = [], cursor = 0, effects = [], dirty = true, tree, unmounted = false;
  let props = { userId: '42', onBack() {}, onEditGoals() {} };
  const calls = [], frames = [], focused = [];
  const equal = (left, right) => left && right && left.length === right.length && left.every((value, index) => Object.is(value, right[index]));
  const react = {
    useState(initial) {
      const index = cursor++;
      if (!slots[index]) slots[index] = { value: typeof initial === 'function' ? initial() : initial };
      return [slots[index].value, next => {
        const value = typeof next === 'function' ? next(slots[index].value) : next;
        if (!Object.is(value, slots[index].value)) { slots[index].value = value; dirty = true; }
      }];
    },
    useRef(current) { const index = cursor++; return (slots[index] ||= { value: { current } }).value; },
    useMemo(fn, deps) { const index = cursor++; if (!slots[index] || !equal(slots[index].deps, deps)) slots[index] = { value: fn(), deps }; return slots[index].value; },
    useCallback(fn, deps) { return react.useMemo(() => fn, deps); },
    useEffect(fn, deps) {
      const index = cursor++;
      if (!slots[index] || !equal(slots[index].deps, deps)) {
        const cleanup = slots[index]?.cleanup;
        slots[index] = { deps, cleanup };
        effects.push(() => { cleanup?.(); slots[index].cleanup = fn(); });
      }
    },
  };
  const fetcher = async (url, options = {}) => {
    calls.push({ url, options });
    if (options.method === 'POST') {
      const result = await coachRequest(JSON.parse(options.body), options);
      return result instanceof Response ? result : Response.json(result);
    }
    const data = sample(); data.user_id = Number(new URL(url, 'https://app.test').searchParams.get('userId'));
    return Response.json(data);
  };
  const helperExports = {};
  vm.runInNewContext(helperCode, { exports: helperExports, fetch: fetcher, Date, Error });
  const exports = {};
  vm.runInNewContext(componentCode, {
    exports, AbortController, URLSearchParams, fetch: fetcher, Error,
    requestAnimationFrame: fn => frames.push(fn),
    require(name) { return name === 'react' ? react : name === '@/lib/pillarProgress' ? helperExports : require(name); },
  });
  const text = node => node == null || typeof node === 'boolean' ? '' : Array.isArray(node) ? node.map(text).join(' ') : typeof node === 'object' ? text(node.props?.children) : String(node);
  const all = (node, predicate) => !node || typeof node !== 'object' ? [] : Array.isArray(node) ? node.flatMap(child => all(child, predicate)) : [...(predicate(node) ? [node] : []), ...all(node.props?.children, predicate)];
  const expand = node => {
    if (!node || typeof node !== 'object') return node;
    if (Array.isArray(node)) return node.map(expand);
    if (typeof node.type === 'function') return expand(node.type(node.props));
    const element = { ...node, props: { ...node.props, children: expand(node.props?.children) } };
    if (element.props.ref) {
      const host = { focus() { focused.push(element.props['aria-label'] || text(element)); } };
      if (typeof element.props.ref === 'function') element.props.ref(host);
      else element.props.ref.current = host;
    }
    return element;
  };
  const flush = async () => {
    for (let count = 0; count < 20; count++) {
      if (dirty && !unmounted) {
        cursor = 0; dirty = false; tree = expand(exports.default(props));
        const pending = effects; effects = []; pending.forEach(fn => fn());
      }
      frames.splice(0).forEach(fn => fn());
      await new Promise(resolve => setImmediate(resolve));
      if (!dirty || unmounted) return;
    }
    throw new Error('Component did not settle');
  };
  return {
    calls, focused, flush, text: () => text(tree),
    buttons: () => all(tree, node => node.type === 'button').map(node => node.props['aria-label'] || text(node).trim()),
    async click(label) {
      const button = all(tree, node => node.type === 'button').find(node => (node.props['aria-label'] || text(node).trim()).startsWith(label));
      assert.ok(button, `Missing button ${label}`); button.props.onClick(); await flush();
    },
    async update(next) { props = { ...props, ...next }; dirty = true; await flush(); },
    unmount() { unmounted = true; slots.forEach(slot => slot?.cleanup?.()); },
  };
}

test('opening progress does not generate coaching, and circles expose status with recorded zero', async t => {
  const h = harness(); t.after(() => h.unmount()); await h.flush();
  assert.equal(h.calls.length, 1);
  assert.equal(h.calls[0].options.method, undefined);
  assert.ok(h.buttons().includes('Contribution: Needs attention, 0 out of 100. Get guidance'));
  assert.ok(h.buttons().includes('Adaptability: Not scored. View check-ins'));
});

test('neutral circle opens evidence and explanation without generating AI guidance', async t => {
  const h = harness(); t.after(() => h.unmount()); await h.flush();
  await h.click('Adaptability:');
  assert.equal(h.calls.length, 1);
  assert.match(h.text(), /No challenges reported/);
  assert.match(h.text(), /No challenges today/);
  assert.doesNotMatch(h.text(), /Preparing guidance/);
});

test('only the tapped concept generates guidance and back restores its circle focus', async t => {
  const h = harness(); t.after(() => h.unmount()); await h.flush();
  await h.click('Contribution:');
  assert.deepEqual(JSON.parse(h.calls[1].options.body), { userId: '42', pillarKey: 'purpose', conceptKey: 'contribution_connection' });
  assert.match(h.text(), /Insight for contribution_connection/);
  assert.doesNotMatch(h.text(), /Insight for values_alignment/);
  await h.click('Back to pillar progress');
  assert.equal(h.focused.at(-1), 'Contribution: Needs attention, 0 out of 100. Get guidance');
});

test('back aborts pending guidance and an ignored late response cannot replace a new selection', async t => {
  const pending = [];
  const h = harness((body, options) => new Promise(resolve => pending.push({ body, options, resolve })));
  t.after(() => h.unmount()); await h.flush();
  await h.click('Contribution:');
  await h.click('Back to pillar progress');
  assert.equal(pending[0].options.signal.aborted, true);
  await h.click('Values:');
  const payload = (item, insight) => ({ source: 'ai', pillar_key: item.body.pillarKey, concept_key: item.body.conceptKey, week_start: '2026-11-16', through: '2026-11-18', insight, action: 'A step.', reflection: 'Reflect?' });
  pending[1].resolve(payload(pending[1], 'NEW GUIDANCE')); await h.flush();
  pending[0].resolve(payload(pending[0], 'OLD GUIDANCE')); await h.flush();
  assert.match(h.text(), /NEW GUIDANCE/); assert.doesNotMatch(h.text(), /OLD GUIDANCE/);
});

test('unmount and member changes cancel pending guidance', async t => {
  const pending = [];
  const h = harness((_body, options) => new Promise(resolve => pending.push({ options, resolve })));
  t.after(() => h.unmount()); await h.flush(); await h.click('Contribution:');
  await h.update({ userId: '43' });
  assert.equal(pending[0].options.signal.aborted, true);
  assert.match(h.text(), /Pillar progress/); assert.doesNotMatch(h.text(), /Preparing guidance/);
  await h.click('Values:'); h.unmount();
  assert.equal(pending[1].options.signal.aborted, true);
});

test('AI failure shows an explicit retry state without substitute guidance', async t => {
  const h = harness(async () => Response.json({ error: 'AI guidance is unavailable right now.' }, { status: 503 }));
  t.after(() => h.unmount()); await h.flush(); await h.click('Values:');
  assert.match(h.text(), /AI guidance is unavailable/);
  assert.doesNotMatch(h.text(), /One small step/);
  assert.ok(h.buttons().includes('Try again'));
  assert.ok(h.buttons().includes('Refresh progress'));
});
