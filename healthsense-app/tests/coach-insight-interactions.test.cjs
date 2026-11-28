// Exercise the real selection, AI helper and shared guidance UI with async hook lifecycles.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');

const compile = filename => ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2017 },
}).outputText;
const styles = { pillarSurface: 'pillar-surface', scoreCircle: 'score-circle', guidanceReveal: 'guidance-reveal', reflectionReveal: 'reflection-reveal' };

function sample({ userId = 42, offTrackCount = 2, onTrackCount = 2, unloggedCount = 0, notApplicableCount = 0, focusCount = Math.min(offTrackCount, 6) } = {}) {
  return {
    user_id: userId,
    review: {
      status: offTrackCount > 0 ? 'off_track' : onTrackCount > 0 && unloggedCount === 0 ? 'on_track' : 'insufficient_data',
      reviewed_count: offTrackCount + onTrackCount + unloggedCount + notApplicableCount,
      off_track_count: offTrackCount, on_track_count: onTrackCount,
      unlogged_count: unloggedCount, not_applicable_count: notApplicableCount,
      focus_count: focusCount, week_start_date: '2026-11-16', through_date: '2026-11-18',
    },
    available_concepts: Array.from({ length: focusCount }, (_, index) => ({
      status: 'off_track', pillar_key: 'purpose', pillar_label: 'Purpose',
      concept_key: `concept_${index + 1}`, label: `Concept ${index + 1}`, score: index + 20,
      target_label: `PRIVATE TARGET ${index}`, anchor_date: '2026-11-18',
    })),
  };
}

function ai(body, extra = {}) {
  return {
    source: 'ai', pillar_key: body.pillarKey, concept_key: body.conceptKey,
    concept_label: body.conceptKey, week_start: '2026-11-16', through: '2026-11-18',
    cached: false, generated_at: '2026-11-18T10:00:00', insight: 'HIDDEN INSIGHT',
    action: `AI step for ${body.conceptKey}.`, reflection: `AI reflection for ${body.conceptKey}?`, ...extra,
  };
}

function componentHarness(componentPath, request, initialProps = {}) {
  const instances = new Map(), modules = new Map(), calls = [], renders = [], frames = [];
  let active, effects = [], dirty = true, tree, unmounted = false, updatesAfterUnmount = 0;
  let props = { userId: '42', onBack() {}, onEditGoals() {}, ...initialProps };
  const same = (a, b) => a && b && a.length === b.length && a.every((value, i) => Object.is(value, b[i]));
  const react = {
    useState(initial) {
      const instance = active, index = instance.cursor++;
      const slot = instance.slots[index] ||= { value: typeof initial === 'function' ? initial() : initial };
      return [slot.value, next => {
        if (!instance.alive) { updatesAfterUnmount++; return; }
        const value = typeof next === 'function' ? next(slot.value) : next;
        if (!Object.is(value, slot.value)) { slot.value = value; dirty = true; }
      }];
    },
    useRef(current) { const slot = active.slots[active.cursor++] ||= { value: { current } }; return slot.value; },
    useMemo(fn, deps) {
      const instance = active, index = instance.cursor++;
      if (!instance.slots[index] || !same(instance.slots[index].deps, deps)) instance.slots[index] = { value: fn(), deps };
      return instance.slots[index].value;
    },
    useCallback(fn, deps) { return react.useMemo(() => fn, deps); },
    useEffect(fn, deps) {
      const instance = active, index = instance.cursor++;
      if (!instance.slots[index] || !same(instance.slots[index].deps, deps)) {
        const previousCleanup = instance.slots[index]?.cleanup;
        const slot = instance.slots[index] = { deps };
        effects.push(() => {
          previousCleanup?.();
          if (instance.alive && instance.slots[index] === slot) slot.cleanup = fn();
        });
      }
    },
  };
  const fetcher = async (url, options = {}) => {
    calls.push({ url, options });
    const result = await request(url, options, calls.length);
    return result instanceof Response ? result : Response.json(result);
  };
  function load(filename) {
    filename = path.resolve(filename);
    if (modules.has(filename)) return modules.get(filename);
    const exports = {}; modules.set(filename, exports);
    vm.runInNewContext(compile(filename), {
      exports, AbortController, URLSearchParams, Date, Error, fetch: fetcher,
      requestAnimationFrame: fn => frames.push(fn),
      require(name) {
        if (name === 'react') return react;
        if (name.endsWith('.module.css')) return { default: styles };
        if (name.startsWith('@/')) {
          const target = path.join('src', name.slice(2));
          return load(fs.existsSync(`${target}.tsx`) ? `${target}.tsx` : `${target}.ts`);
        }
        return require(name);
      },
    });
    return exports;
  }
  const Component = load(componentPath).default;
  const text = node => node == null || typeof node === 'boolean' ? '' : Array.isArray(node) ? node.map(text).join(' ') : typeof node === 'object' ? text(node.props?.children) : String(node);
  const all = (node, predicate) => !node || typeof node !== 'object' ? [] : Array.isArray(node) ? node.flatMap(child => all(child, predicate)) : [...(predicate(node) ? [node] : []), ...all(node.props?.children, predicate)];
  const canonical = node => !node || typeof node !== 'object' ? node : Array.isArray(node) ? Array.from(node, canonical) : {
    type: typeof node.type === 'symbol' ? 'fragment' : node.type,
    className: node.props.className, ariaHidden: node.props['aria-hidden'],
    viewBox: node.props.viewBox, d: node.props.d, children: canonical(node.props.children),
  };
  const cleanup = instance => { instance.alive = false; instance.slots.forEach(slot => slot?.cleanup?.()); };
  const expand = (node, id, seen) => {
    if (!node || typeof node !== 'object') return node;
    if (Array.isArray(node)) return node.map((child, i) => expand(child, `${id}/${child?.key ?? i}`, seen));
    if (typeof node.type === 'function') {
      const key = `${id}:${node.type.name}`;
      const instance = instances.get(key) || { slots: [], alive: true };
      instances.set(key, instance); seen.add(key); instance.cursor = 0;
      const previous = active; active = instance;
      const result = node.type(node.props); active = previous;
      return expand(result, `${key}/render`, seen);
    }
    const element = { ...node, props: { ...node.props, children: expand(node.props.children, `${id}/children`, seen) } };
    if (element.props.ref) {
      const host = { focus() {} };
      if (typeof element.props.ref === 'function') element.props.ref(host);
      else element.props.ref.current = host;
    }
    return element;
  };
  const flush = async () => {
    for (let count = 0; count < 50; count++) {
      if (dirty && !unmounted) {
        dirty = false;
        const seen = new Set();
        tree = expand({ type: Component, props }, 'root', seen);
        for (const [key, instance] of instances) if (!seen.has(key)) { cleanup(instance); instances.delete(key); }
        renders.push(text(tree).replace(/\s+/g, ' ').trim());
        const pending = effects; effects = []; pending.forEach(fn => fn());
      }
      frames.splice(0).forEach(fn => fn());
      await new Promise(resolve => setImmediate(resolve));
      if (!dirty || unmounted) return;
    }
    throw new Error('Component did not settle');
  };
  return {
    calls, renders, flush, text: () => text(tree).replace(/\s+/g, ' ').trim(), updatesAfterUnmount: () => updatesAfterUnmount,
    rows: () => all(tree, node => node.type === 'article').map(node => ({ label: node.props['aria-label'], text: text(node) })),
    sections: () => all(tree, node => node.props?.className?.split(' ').includes('guidance-reveal')).map(canonical),
    roles: () => all(tree, node => node.props?.role).map(node => node.props.role),
    async click(label, rowLabel) {
      const scope = rowLabel ? all(tree, node => node.type === 'article' && node.props['aria-label'] === rowLabel)[0] : tree;
      const button = all(scope, node => node.type === 'button').find(node => (node.props['aria-label'] || text(node).trim()).startsWith(label));
      assert.ok(button, `Missing button ${label}`); button.props.onClick(); await flush();
    },
    async update(next) { props = { ...props, ...next }; dirty = true; await flush(); },
    unmount() { if (unmounted) return; unmounted = true; instances.forEach(cleanup); },
  };
}

function harness(reviewRequest = async () => sample(), coachRequest = async body => ai(body), props = {}) {
  return componentHarness('src/components/CoachInsightPanel.tsx', (url, options, attempt) => options.method === 'POST'
    ? coachRequest(JSON.parse(options.body), options, attempt)
    : reviewRequest(url, options, attempt), props);
}
const coachingCalls = h => h.calls.filter(call => call.options.method === 'POST');
const reviewCalls = h => h.calls.filter(call => call.options.method !== 'POST');

test('Insight completes and validates selection before requesting the same AI concept endpoint', async t => {
  let resolveSelection;
  const h = harness(() => new Promise(resolve => { resolveSelection = resolve; }));
  t.after(() => h.unmount()); await h.flush();
  assert.equal(coachingCalls(h).length, 0);
  assert.deepEqual(h.roles(), ['status']);
  assert.match(h.text(), /Reviewing all your concepts/);
  resolveSelection(sample({ offTrackCount: 3, onTrackCount: 7, unloggedCount: 2 })); await h.flush();
  assert.equal(h.rows().length, 3);
  assert.equal(reviewCalls(h).length, 1);
  assert.equal(reviewCalls(h)[0].url, '/api/coach-insight?userId=42');
  assert.deepEqual(coachingCalls(h).map(call => ({ url: call.url, cache: call.options.cache, body: JSON.parse(call.options.body) })),
    [1, 2, 3].map(i => ({ url: '/api/pillar-progress/coaching', cache: 'no-store', body: { userId: '42', pillarKey: 'purpose', conceptKey: `concept_${i}` } })));
  assert.match(h.text(), /Week to date · 16–18 Nov/);
  assert.match(h.text(), /AI step for concept_1/);
  assert.doesNotMatch(h.text(), /PRIVATE TARGET|Score to date|Your target|HIDDEN INSIGHT/);
});

test('rank globally before generation, select only six, allow repeated pillars, zero scores and stable ties', async t => {
  const data = sample({ offTrackCount: 8, focusCount: 8 });
  [45, 0, 20, 5, 10, 30, 20, 70].forEach((score, i) => {
    Object.assign(data.available_concepts[i], { score, guidance: 'OLD BANK ADVICE', reflection: 'FIXED QUESTION' });
  });
  const h = harness(async () => data); t.after(() => h.unmount()); await h.flush();
  const expected = [2, 4, 5, 3, 7, 6];
  assert.deepEqual(h.rows().map(row => row.label), expected.map(i => `Concept ${i}: off track`));
  assert.deepEqual(coachingCalls(h).map(call => JSON.parse(call.options.body).conceptKey), expected.map(i => `concept_${i}`));
  assert.equal(coachingCalls(h).length, 6);
  assert.match(h.text(), /6 lowest-scoring concepts/);
  assert.doesNotMatch(h.text(), /OLD BANK ADVICE|FIXED QUESTION|one concept per pillar|AI step for concept_[18]/);
});

test('Insight and manual Get guidance render identical AI text, cards, icons and animation without frontend word caps', async t => {
  const long = { cached: true, action: 'AI action\n' + 'Long step continues '.repeat(35), reflection: 'Consider this\n' + 'A thoughtful question '.repeat(10) + '?' };
  const selected = sample({ offTrackCount: 1 });
  const h = harness(async () => selected, async body => ai(body, long));
  const concept = {
    concept_key: 'concept_1', label: 'Concept 1', helper: 'Question?', score: 20, status: 'red', answered_days_count: 1,
    scored_days_count: 1, not_applicable_days_count: 0, elapsed_days: 3, contribution_points: 20, days: [],
  };
  const progress = {
    user_id: 42, week: { start: '2026-11-16', end: '2026-11-22', through: '2026-11-18', elapsed_days: 3 },
    pillars: [{ pillar_key: 'purpose', label: 'Purpose', score: 20, status: 'red', concepts: [concept], completed_days_count: 1, elapsed_days: 3 }],
  };
  const manual = componentHarness('src/components/PillarProgressPanel.tsx', async (_url, options) => options.method === 'POST'
    ? ai(JSON.parse(options.body), long) : progress, { initialPillarKey: 'purpose' });
  t.after(() => { h.unmount(); manual.unmount(); });
  await h.flush(); await manual.flush(); await manual.click('Concept 1:');
  assert.equal(h.sections().length, 2);
  assert.deepEqual(h.sections(), manual.sections());
  assert.ok(h.rows()[0].text.includes(long.action));
  assert.ok(h.rows()[0].text.includes(long.reflection));
  assert.match(h.text(), /One small step.*A moment to reflect/);
  assert.doesNotMatch(h.text(), /HIDDEN INSIGHT|What would help you work towards/);
});

test('each card loads independently and retries only its failed AI request', async t => {
  let resolveSecond;
  const attempts = new Map();
  const h = harness(async () => sample(), async body => {
    const attempt = (attempts.get(body.conceptKey) || 0) + 1; attempts.set(body.conceptKey, attempt);
    if (body.conceptKey === 'concept_1' && attempt === 1) return Response.json({ error: 'AI guidance is unavailable right now.' }, { status: 503 });
    if (body.conceptKey === 'concept_2') return new Promise(resolve => { resolveSecond = resolve; });
    return ai(body);
  });
  t.after(() => h.unmount()); await h.flush();
  assert.match(h.rows()[0].text, /AI guidance is unavailable/);
  assert.match(h.rows()[1].text, /Preparing guidance/);
  assert.equal(h.sections().length, 0);
  resolveSecond(ai({ pillarKey: 'purpose', conceptKey: 'concept_2' })); await h.flush();
  assert.match(h.rows()[1].text, /AI step for concept_2/);
  await h.click('Try again', 'Concept 1: off track');
  assert.match(h.rows()[0].text, /AI step for concept_1/);
  assert.deepEqual([...attempts], [['concept_1', 2], ['concept_2', 1]]);
  assert.equal(reviewCalls(h).length, 1);
  assert.equal(coachingCalls(h)[0].options.signal.aborted, true);
});

test('non-AI, blank, mismatched and stale guidance never turn into library advice or a fixed reflection', async t => {
  for (const override of [
    { source: 'library' }, { action: '' }, { reflection: '  ' }, { insight: '' },
    { pillar_key: 'nutrition' }, { concept_key: 'other_concept' }, { week_start: '2026-11-09' }, { through: '2026-11-19' },
  ]) {
    const data = sample({ offTrackCount: 1 });
    data.available_concepts[0].guidance = 'OLD LIBRARY BODY';
    const h = harness(async () => data, async body => ai(body, override));
    t.after(() => h.unmount()); await h.flush();
    assert.deepEqual(h.roles(), ['alert']);
    assert.equal(h.sections().length, 0);
    assert.match(h.text(), /refresh your progress/);
    assert.doesNotMatch(h.text(), /OLD LIBRARY BODY|AI step|What would help you work towards/);
  }
});

test('refresh after a stale week gets a new selection before requesting guidance again', async t => {
  let attempts = 0;
  const data = sample({ offTrackCount: 1 });
  const h = harness(async () => {
    attempts++;
    const payload = structuredClone(data);
    if (attempts > 1) payload.review.through_date = '2026-11-19';
    return payload;
  }, async body => ai(body, { through: '2026-11-19' }));
  t.after(() => h.unmount()); await h.flush();
  assert.equal(h.sections().length, 0);
  await h.click('Refresh insights');
  assert.equal(reviewCalls(h).length, 2);
  assert.equal(coachingCalls(h).length, 2);
  assert.match(h.text(), /Week to date · 16–19 Nov/);
  assert.match(h.text(), /AI step for concept_1/);
});

test('on-track, incomplete and neutral reviews generate no AI requests or corrective cards', async t => {
  for (const [data, title] of [
    [sample({ offTrackCount: 0, onTrackCount: 8 }), "You're on track"],
    [sample({ offTrackCount: 0, onTrackCount: 3, unloggedCount: 2 }), 'More data needed'],
    [sample({ offTrackCount: 0, onTrackCount: 0, unloggedCount: 4 }), 'More data needed'],
    [sample({ offTrackCount: 0, onTrackCount: 0, notApplicableCount: 7 }), 'No guidance needed'],
  ]) {
    const h = harness(async () => data); t.after(() => h.unmount()); await h.flush();
    assert.ok(h.text().includes(title));
    assert.equal(coachingCalls(h).length, 0);
    assert.equal(h.rows().length, 0);
    assert.doesNotMatch(h.text(), /One small step|A moment to reflect|AI step/);
  }
});

test('mismatched members, invalid selection metadata and incomplete reviews issue no AI requests', async t => {
  const mutations = [
    data => { data.user_id = 99; }, data => { data.review.reviewed_count++; },
    data => { data.review.status = 'on_track'; }, data => { data.available_concepts.pop(); },
    data => { data.available_concepts[0] = null; }, data => { data.review.focus_count = 0; },
    data => { data.available_concepts[0].score = null; }, data => { data.available_concepts[0].score = 80; },
    data => { data.available_concepts[0].score = -1; }, data => { data.available_concepts[0].score = '20'; },
    data => { data.available_concepts[0].label = ''; }, data => { data.available_concepts[0].concept_key = ''; },
    data => { data.available_concepts[1].concept_key = data.available_concepts[0].concept_key; },
    data => { data.review.week_start_date = '2026-11-31'; }, data => { data.review.through_date = null; },
    data => { data.review.through_date = '2026-11-15'; }, data => { data.review.unlogged_count = -1; },
  ];
  const invalid = mutations.map(mutate => { const data = sample(); mutate(data); return data; });
  for (const data of [{}, null, ...invalid, new Response('not JSON')]) {
    const h = harness(async () => data); t.after(() => h.unmount()); await h.flush();
    assert.deepEqual(h.roles(), ['alert']);
    assert.equal(h.rows().length, 0);
    assert.equal(coachingCalls(h).length, 0);
  }
});

test('a failed selection request offers retry without exposing server or network details', async t => {
  let attempts = 0;
  const h = harness(async () => ++attempts === 1 ? new Response('PRIVATE SERVER DETAIL', { status: 503 }) : sample());
  t.after(() => h.unmount()); await h.flush();
  assert.match(h.text(), /Could not load your insights/);
  assert.doesNotMatch(h.text(), /PRIVATE/);
  assert.equal(coachingCalls(h).length, 0);
  await h.click('Try again');
  assert.equal(reviewCalls(h).length, 2);
  assert.equal(coachingCalls(h).length, 2);
  assert.equal(reviewCalls(h)[0].options.signal.aborted, true);
  const network = harness(async () => { throw new Error('PRIVATE NETWORK DETAIL'); });
  t.after(() => network.unmount()); await network.flush();
  assert.doesNotMatch(network.text(), /PRIVATE NETWORK DETAIL/);
  assert.equal(coachingCalls(network).length, 0);
});

test('changing members aborts pending review and AI requests and hides both pending and loaded old guidance', async t => {
  const pending = [];
  const h = harness(async url => sample({ userId: Number(new URL(url, 'https://app.test').searchParams.get('userId')), offTrackCount: 1 }),
    (body, options) => new Promise(resolve => pending.push({ body, options, resolve })));
  t.after(() => h.unmount()); await h.flush();
  assert.equal(pending.length, 1);
  const offset = h.renders.length;
  await h.update({ userId: '43' });
  assert.equal(pending[0].options.signal.aborted, true);
  assert.equal(pending[1].body.userId, '43');
  pending[0].resolve(ai(pending[0].body, { action: 'STALE MEMBER ADVICE' })); await h.flush();
  assert.doesNotMatch(h.renders.slice(offset).join('\n'), /STALE MEMBER ADVICE/);
  pending[1].resolve(ai(pending[1].body, { action: 'CURRENT MEMBER ADVICE' })); await h.flush();
  assert.match(h.text(), /CURRENT MEMBER ADVICE/);
  const nextOffset = h.renders.length;
  await h.update({ userId: '44' });
  assert.doesNotMatch(h.renders.slice(nextOffset).join('\n'), /CURRENT MEMBER ADVICE|STALE MEMBER ADVICE/);
  assert.equal(pending[1].options.signal.aborted, true);
  h.unmount();
  pending[2].resolve(ai(pending[2].body)); await h.flush();
  assert.equal(pending[2].options.signal.aborted, true);
  assert.equal(h.updatesAfterUnmount(), 0);
});

test('late selection responses after member changes or unmount cannot start AI generation', async () => {
  const pending = [];
  const h = harness((url, options) => new Promise(resolve => pending.push({ url, options, resolve })));
  await h.flush(); await h.update({ userId: '43' });
  assert.equal(pending[0].options.signal.aborted, true);
  pending[0].resolve(sample()); await h.flush();
  assert.equal(coachingCalls(h).length, 0);
  assert.match(h.text(), /Reviewing all your concepts/);
  h.unmount(); pending[1].resolve(sample({ userId: 43 })); await h.flush();
  assert.equal(pending[1].options.signal.aborted, true);
  assert.equal(coachingCalls(h).length, 0);
  assert.equal(h.updatesAfterUnmount(), 0);
});

test('weekly labels retain first-day and cross-month periods without generation dates', async t => {
  for (const [start, through, expected] of [
    ['2026-11-16', '2026-11-16', '16 Nov'], ['2026-10-26', '2026-11-01', '26 Oct–1 Nov'],
  ]) {
    const data = sample({ offTrackCount: 0 });
    data.review.week_start_date = start; data.review.through_date = through; data.insight_date = '2026-11-25';
    const h = harness(async () => data); t.after(() => h.unmount()); await h.flush();
    assert.ok(h.text().includes(`Week to date · ${expected}`));
    assert.doesNotMatch(h.text(), /25 Nov/);
    assert.equal(coachingCalls(h).length, 0);
  }
});
