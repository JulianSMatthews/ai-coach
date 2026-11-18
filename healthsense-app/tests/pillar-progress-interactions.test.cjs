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
const paletteCode = compile('src/lib/pillars.ts');
const iconCode = compile('src/components/PillarIcon.tsx');

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

function harness(coachRequest = async body => ({ source: 'ai', pillar_key: body.pillarKey, concept_key: body.conceptKey, week_start: '2026-11-16', through: '2026-11-18', insight: `HIDDEN INSIGHT for ${body.conceptKey}`, action: `Step for ${body.conceptKey}`, reflection: `Reflect on ${body.conceptKey}?` }), progressData = sample(), initialProps = {}) {
  let slots = [], cursor = 0, effects = [], dirty = true, tree, unmounted = false;
  let props = { userId: '42', onBack() {}, onEditGoals() {}, ...initialProps };
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
    const data = JSON.parse(JSON.stringify(progressData)); data.user_id = Number(new URL(url, 'https://app.test').searchParams.get('userId'));
    return Response.json(data);
  };
  const helperExports = {};
  vm.runInNewContext(helperCode, { exports: helperExports, fetch: fetcher, Date, Error });
  const paletteExports = {};
  vm.runInNewContext(paletteCode, { exports: paletteExports });
  const iconExports = {};
  vm.runInNewContext(iconCode, { exports: iconExports, require });
  const exports = {};
  vm.runInNewContext(componentCode, {
    exports, AbortController, URLSearchParams, fetch: fetcher, Error,
    requestAnimationFrame: fn => frames.push(fn),
    require(name) {
      if (name === './PillarProgressPanel.module.css') return { default: { pillarSurface: 'pillar-surface', scoreCircle: 'score-circle', guidanceReveal: 'guidance-reveal', reflectionReveal: 'reflection-reveal' } };
      return name === 'react' ? react : name === '@/lib/pillarProgress' ? helperExports : name === '@/lib/pillars' ? paletteExports : name === '@/components/PillarIcon' ? iconExports : require(name);
    },
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
    rows: () => all(tree, node => node.type === 'article').map(node => ({
      label: node.props['aria-label'], style: node.props.style,
      grids: all(node, child => child.props?.style?.gridTemplateColumns).map(child => child.props.style.gridTemplateColumns),
      buttons: all(node, child => child.type === 'button').map(child => child.props['aria-label']),
      icons: all(node, child => child.type === 'svg').map(child => child.props['aria-hidden']),
    })),
    scoreBreakdownOpen: () => all(tree, node => node.type === 'details' && text(node).includes('How this score is made')).map(node => Boolean(node.props.open)),
    guidanceHeadings: () => all(tree, node => node.type === 'h3').map(node => text(node).trim()),
    reveals: () => all(tree, node => node.props?.className?.includes('guidance-reveal')).map(node => node.props.className),
    buttons: () => all(tree, node => node.type === 'button').map(node => node.props['aria-label'] || text(node).trim()),
    async click(label) {
      const button = all(tree, node => node.type === 'button').find(node => (node.props['aria-label'] || text(node).trim()).startsWith(label));
      assert.ok(button, `Missing button ${label}`); button.props.onClick(); await flush();
    },
    async update(next) { props = { ...props, ...next }; dirty = true; await flush(); },
    unmount() { unmounted = true; slots.forEach(slot => slot?.cleanup?.()); },
  };
}

test('opening progress shows only pillars and opening concept scores does not generate coaching', async t => {
  const h = harness(); t.after(() => h.unmount()); await h.flush();
  assert.equal(h.calls.length, 1);
  assert.equal(h.calls[0].options.method, undefined);
  assert.ok(h.buttons().some(label => /^Purpose:.*View concepts$/.test(label)));
  assert.ok(h.buttons().some(label => /^Resilience:.*View concepts$/.test(label)));
  assert.doesNotMatch(h.text(), /Values|Contribution|Adaptability/);
  await h.click('Purpose:');
  assert.equal(h.calls.length, 1);
  assert.ok(h.buttons().includes('Contribution: Needs attention, 0 out of 100. Get guidance'));
  assert.match(h.text(), /Get guidance/);
});

test('cue-card entry opens the requested pillar and Back returns to the overview without reopening it', async t => {
  const h = harness(undefined, sample(), { initialPillarKey: ' Purpose ' });
  t.after(() => h.unmount()); await h.flush();
  assert.equal(h.calls.length, 1);
  assert.equal(h.rows().length, 0);
  assert.ok(h.buttons().includes('Contribution: Needs attention, 0 out of 100. Get guidance'));
  assert.ok(!h.buttons().some(label => label.startsWith('Adaptability:')));
  await h.click('Back to pillars');
  assert.equal(h.rows().length, 2);
  assert.match(h.focused.at(-1), /^Purpose:.*View concepts$/);
  assert.doesNotMatch(h.text(), /Values|Contribution|Adaptability/);
  await h.click('Resilience:');
  assert.ok(h.buttons().includes('Adaptability: Not scored. View check-ins'));
  assert.equal(h.calls.length, 1);
});

test('an unavailable cue-card pillar falls back to the overview', async t => {
  const h = harness(undefined, sample(), { initialPillarKey: 'nutrition' });
  t.after(() => h.unmount()); await h.flush();
  assert.equal(h.rows().length, 2);
  assert.ok(h.buttons().some(label => /^Purpose:.*View concepts$/.test(label)));
  assert.equal(h.calls.length, 1);
});

test('changing the requested pillar cancels coaching before showing the new concept scores', async t => {
  let pending;
  const h = harness((body, options) => new Promise(resolve => { pending = { body, options, resolve }; }), sample(), { initialPillarKey: 'purpose' });
  t.after(() => h.unmount()); await h.flush();
  await h.click('Contribution:');
  await h.update({ initialPillarKey: 'resilience' });
  assert.equal(pending.options.signal.aborted, true);
  assert.ok(h.buttons().includes('Adaptability: Not scored. View check-ins'));
  pending.resolve({ source: 'ai', pillar_key: 'purpose', concept_key: 'contribution_connection', week_start: '2026-11-16', through: '2026-11-18', insight: 'Old insight', action: 'OLD GUIDANCE', reflection: 'Old reflection?' });
  await h.flush();
  assert.doesNotMatch(h.text(), /OLD GUIDANCE|Preparing guidance/);
  assert.equal(h.calls.filter(call => call.options.method === 'POST').length, 1);
});

test('neutral circle opens evidence and explanation without generating AI guidance', async t => {
  const h = harness(); t.after(() => h.unmount()); await h.flush();
  await h.click('Resilience:');
  assert.ok(h.buttons().includes('Adaptability: Not scored. View check-ins'));
  assert.match(h.text(), /View check-ins/);
  await h.click('Adaptability:');
  assert.equal(h.calls.length, 1);
  assert.match(h.text(), /No challenges reported/);
  assert.match(h.text(), /No challenges today/);
  assert.doesNotMatch(h.text(), /Preparing guidance/);
  assert.deepEqual(h.guidanceHeadings(), []);
});

test('only the tapped concept generates guidance and both back levels restore focus without extra requests', async t => {
  const h = harness(); t.after(() => h.unmount()); await h.flush();
  await h.click('Purpose:');
  await h.click('Contribution:');
  assert.deepEqual(JSON.parse(h.calls[1].options.body), { userId: '42', pillarKey: 'purpose', conceptKey: 'contribution_connection' });
  assert.match(h.text(), /Step for contribution_connection/);
  assert.match(h.text(), /Reflect on contribution_connection/);
  assert.doesNotMatch(h.text(), /Step for values_alignment|HIDDEN INSIGHT/);
  await h.click('Back to concepts');
  assert.equal(h.focused.at(-1), 'Contribution: Needs attention, 0 out of 100. Get guidance');
  assert.ok(h.buttons().includes('Values: On track, 100 out of 100. Get guidance'));
  assert.equal(h.calls.length, 2);
  await h.click('Back to pillars');
  assert.match(h.focused.at(-1), /^Purpose:.*View concepts$/);
  assert.doesNotMatch(h.text(), /Values|Contribution|Adaptability/);
  assert.equal(h.calls.length, 2);
});

test('back aborts pending guidance and an ignored late response cannot replace a new selection', async t => {
  const pending = [];
  const h = harness((body, options) => new Promise(resolve => pending.push({ body, options, resolve })));
  t.after(() => h.unmount()); await h.flush();
  await h.click('Purpose:');
  await h.click('Contribution:');
  await h.click('Back to concepts');
  assert.equal(pending[0].options.signal.aborted, true);
  await h.click('Values:');
  const payload = (item, marker) => ({ source: 'ai', pillar_key: item.body.pillarKey, concept_key: item.body.conceptKey, week_start: '2026-11-16', through: '2026-11-18', insight: `HIDDEN INSIGHT ${marker}`, action: `${marker} step`, reflection: `${marker} reflection?` });
  pending[1].resolve(payload(pending[1], 'NEW GUIDANCE')); await h.flush();
  pending[0].resolve(payload(pending[0], 'OLD GUIDANCE')); await h.flush();
  assert.match(h.text(), /NEW GUIDANCE/); assert.doesNotMatch(h.text(), /OLD GUIDANCE/);
});

test('scored guidance shows only the step and reflection with staggered reveal classes', async t => {
  const h = harness(); t.after(() => h.unmount()); await h.flush(); await h.click('Purpose:'); await h.click('Contribution:');
  assert.deepEqual(h.guidanceHeadings(), ['One small step', 'A moment to reflect']);
  assert.doesNotMatch(h.text(), /Your insight|HIDDEN INSIGHT|Question about|days answered|Your check-ins this week|How the purpose score is made/);
  assert.equal(h.reveals().length, 2);
  assert.ok(!h.reveals()[0].includes('reflection-reveal'));
  assert.ok(h.reveals()[1].includes('reflection-reveal'));
});

test('guidance reveal is finite, staggered and disabled for reduced motion', () => {
  const css = fs.readFileSync('src/components/PillarProgressPanel.module.css', 'utf8');
  assert.match(css, /animation:\s*guidanceReveal 420ms[^;]*both;/);
  assert.match(css, /animation-delay:\s*150ms;/);
  assert.doesNotMatch(css, /infinite/);
  assert.match(css, /@media\s*\(prefers-reduced-motion:\s*reduce\)[\s\S]*\.guidanceReveal\s*\{\s*animation:\s*none;/);
});

test('unmount and member changes cancel pending guidance', async t => {
  const pending = [];
  const h = harness((_body, options) => new Promise(resolve => pending.push({ options, resolve })));
  t.after(() => h.unmount()); await h.flush(); await h.click('Purpose:'); await h.click('Contribution:');
  await h.update({ userId: '43' });
  assert.equal(pending[0].options.signal.aborted, true);
  assert.match(h.text(), /Pillar progress/); assert.doesNotMatch(h.text(), /Preparing guidance/);
  await h.click('Purpose:');
  await h.click('Values:'); h.unmount();
  assert.equal(pending[1].options.signal.aborted, true);
});

test('AI failure shows an explicit retry state without substitute guidance', async t => {
  const h = harness(async () => Response.json({ error: 'AI guidance is unavailable right now.' }, { status: 503 }));
  t.after(() => h.unmount()); await h.flush(); await h.click('Purpose:'); await h.click('Values:');
  assert.match(h.text(), /AI guidance is unavailable/);
  assert.doesNotMatch(h.text(), /One small step/);
  assert.ok(h.buttons().includes('Try again'));
  assert.ok(h.buttons().includes('Refresh progress'));
});

test('overview shows only pillars and each pillar exposes every optional and historical concept with full labels', async t => {
  const data = sample();
  const definitions = {
    reflection: ['emotional_awareness', 'mindfulness_presence', 'pattern_recognition', 'self_awareness'],
    purpose: ['meaning_fulfilment', 'values_alignment', 'contribution_connection', 'direction_vision'],
    resilience: ['emotional_regulation', 'positive_connection', 'adaptability', 'support_connection', 'stress_recovery', 'optimism_perspective', 'support_openness'],
    recovery: ['sleep_duration', 'sleep_quality', 'bedtime_consistency', 'heat_exposure', 'cold_exposure', 'magnesium'],
    nutrition: ['protein_intake', 'fruit_veg', 'hydration', 'processed_food', 'alcohol_units', 'fasting_adherence', 'omega_3', 'vitamin_d'],
    training: ['cardio_frequency', 'strength_training', 'flexibility_mobility', 'creatine'],
  };
  const conceptLabel = key => key.split('_').map(word => word[0].toUpperCase() + word.slice(1)).join(' ');
  const template = data.pillars[0];
  data.pillars = Object.entries(definitions).map(([key, concepts]) => ({ ...template, pillar_key: key, label: key,
    concepts: concepts.map(concept_key => ({ ...template.concepts[0], concept_key, label: conceptLabel(concept_key),
      is_historical: ['self_awareness', 'direction_vision', 'support_openness'].includes(concept_key) })) }));
  const h = harness(undefined, data); t.after(() => h.unmount()); await h.flush();
  assert.equal(h.rows().length, 6);
  assert.deepEqual(h.rows().map(row => row.label), Object.keys(definitions).map(key => `${key} progress`));
  for (const row of h.rows()) {
    assert.equal(row.buttons.length, 1);
    assert.match(row.buttons[0], /View concepts$/);
    assert.ok(row.icons.length >= 1);
    assert.ok(row.icons.every(icon => String(icon) === 'true'));
  }
  assert.equal(h.rows().find(row => row.label === 'reflection progress').style['--pillar-background'], '#f2efff');
  assert.equal(h.rows().find(row => row.label === 'nutrition progress').style['--pillar-background'], '#fff4e6');
  assert.doesNotMatch(h.text(), /Question about|daily check-ins complete|Scores use your recorded/);
  assert.equal(h.calls.length, 1);
  for (const [key, concepts] of Object.entries(definitions)) {
    await h.click(`${key}:`);
    for (const concept_key of concepts) {
      const label = conceptLabel(concept_key);
      assert.ok(h.buttons().includes(`${label}: On track, 100 out of 100. Get guidance`), `Missing concept ${label}`);
      assert.ok(h.text().includes(label), `Missing full visible label ${label}`);
    }
    assert.equal(h.calls.length, 1);
    await h.click('Back to pillars');
    assert.match(h.focused.at(-1), new RegExp(`^${key}:.*View concepts$`));
  }
  assert.equal(h.calls.length, 1);
});

test('tapping a pillar opens its score explanation without requesting AI', async t => {
  const h = harness(); t.after(() => h.unmount()); await h.flush();
  await h.click('Purpose:');
  assert.match(h.text(), /How this score is made/);
  assert.match(h.text(), /Pillar total/);
  assert.match(h.text(), /An average of recorded answers/);
  assert.deepEqual(h.scoreBreakdownOpen(), [false]);
  assert.ok(h.buttons().includes('Values: On track, 100 out of 100. Get guidance'));
  assert.equal(h.calls.length, 1);
  await h.click('Back to pillars');
  assert.match(h.focused.at(-1), /^Purpose:.*View concepts$/);
});
