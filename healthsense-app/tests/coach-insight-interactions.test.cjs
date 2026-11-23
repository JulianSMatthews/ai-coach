// Exercise the actual insight component with asynchronous requests and React hook state.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const ts = require('typescript');

const compile = filename => ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2017 },
}).outputText;
const componentCode = compile('src/components/CoachInsightPanel.tsx');
const paletteExports = {};
vm.runInNewContext(compile('src/lib/pillars.ts'), { exports: paletteExports });
const iconExports = {};
vm.runInNewContext(compile('src/components/PillarIcon.tsx'), { exports: iconExports, require });

function sample({ userId = 42, offTrackCount = 2, onTrackCount = 2, unloggedCount = 0, notApplicableCount = 0, extras = [] } = {}) {
  return {
    user_id: userId,
    review: {
      status: offTrackCount > 0 ? 'off_track' : onTrackCount > 0 && unloggedCount === 0 ? 'on_track' : 'insufficient_data',
      reviewed_count: offTrackCount + onTrackCount + unloggedCount + notApplicableCount,
      off_track_count: offTrackCount, on_track_count: onTrackCount,
      unlogged_count: unloggedCount, not_applicable_count: notApplicableCount,
    },
    available_concepts: [
      ...Array.from({ length: offTrackCount }, (_, index) => ({
        status: 'off_track', pillar_key: index % 2 ? 'training' : 'nutrition',
        pillar_label: index % 2 ? 'Training' : 'Nutrition',
        concept_key: `concept_${index + 1}`, label: `Concept ${index + 1}`,
        guidance: `Personal next step ${index + 1}.`, reason: `Recorded result ${index + 1} is below your target.`,
        anchor_date: '2026-11-18', latest_value: `${index + 1} recorded`, target_label: `${index + 5} target`,
      })), ...extras,
    ],
  };
}

function harness(request = async () => sample(), initialProps = {}) {
  let slots = [], cursor = 0, effects = [], dirty = true, tree, unmounted = false;
  let props = { userId: '42', ...initialProps };
  const calls = [], renders = [];
  let updatesAfterUnmount = 0;
  const same = (left, right) => left && right && left.length === right.length && left.every((value, index) => Object.is(value, right[index]));
  const react = {
    useState(initial) {
      const index = cursor++;
      if (!slots[index]) slots[index] = { value: typeof initial === 'function' ? initial() : initial };
      return [slots[index].value, next => {
        if (unmounted) updatesAfterUnmount++;
        const value = typeof next === 'function' ? next(slots[index].value) : next;
        if (!Object.is(value, slots[index].value)) { slots[index].value = value; dirty = true; }
      }];
    },
    useEffect(fn, deps) {
      const index = cursor++;
      if (!slots[index] || !same(slots[index].deps, deps)) {
        const cleanup = slots[index]?.cleanup;
        slots[index] = { deps, cleanup };
        effects.push(() => { cleanup?.(); slots[index].cleanup = fn(); });
      }
    },
  };
  const componentExports = {};
  vm.runInNewContext(componentCode, {
    exports: componentExports, AbortController, URLSearchParams, Date, Error,
    fetch: async (url, options) => {
      calls.push({ url, options });
      const result = await request(url, options, calls.length);
      return result instanceof Response ? result : Response.json(result);
    },
    require(name) {
      return name === 'react' ? react : name === '@/lib/pillars' ? paletteExports : name === '@/components/PillarIcon' ? iconExports : require(name);
    },
  });
  const text = node => node == null || typeof node === 'boolean' ? '' : Array.isArray(node) ? node.map(text).join(' ') : typeof node === 'object' ? text(node.props?.children) : String(node);
  const visibleText = node => text(node).replace(/\s+/g, ' ').trim();
  const all = (node, predicate) => !node || typeof node !== 'object' ? [] : Array.isArray(node) ? node.flatMap(child => all(child, predicate)) : [...(predicate(node) ? [node] : []), ...all(node.props?.children, predicate)];
  const expand = node => {
    if (!node || typeof node !== 'object') return node;
    if (Array.isArray(node)) return node.map(expand);
    if (typeof node.type === 'function') return expand(node.type(node.props));
    return { ...node, props: { ...node.props, children: expand(node.props?.children) } };
  };
  const flush = async () => {
    for (let count = 0; count < 20; count++) {
      if (dirty && !unmounted) {
        cursor = 0; dirty = false; tree = expand(componentExports.default(props));
        renders.push(visibleText(tree));
        const pending = effects; effects = []; pending.forEach(fn => fn());
      }
      await new Promise(resolve => setImmediate(resolve));
      if (!dirty || unmounted) return;
    }
    throw new Error('Component did not settle');
  };
  return {
    calls, renders, flush, text: () => visibleText(tree),
    updatesAfterUnmount: () => updatesAfterUnmount,
    roles: () => all(tree, node => node.props?.role).map(node => node.props.role),
    rows: () => all(tree, node => node.type === 'article').map(node => ({
      label: node.props['aria-label'], text: text(node),
      narrative: all(node, child => child.type === 'p' && /leading-(6|7)/.test(child.props.className || '')).map(text).join(' '),
    })),
    buttons: () => all(tree, node => node.type === 'button').map(node => text(node).trim()),
    async click(label) {
      const button = all(tree, node => node.type === 'button' && text(node).trim() === label)[0];
      assert.ok(button, `Missing button ${label}`); button.props.onClick(); await flush();
    },
    async update(next) { props = { ...props, ...next }; dirty = true; await flush(); },
    unmount() { if (unmounted) return; unmounted = true; slots.forEach(slot => slot?.cleanup?.()); },
  };
}

test('opening Insight shows every off-track concept, its evidence and guidance without a selector or eight-card limit', async t => {
  const h = harness(async () => sample({ offTrackCount: 11, onTrackCount: 3, unloggedCount: 1, notApplicableCount: 2 }));
  t.after(() => h.unmount()); await h.flush();
  assert.equal(h.rows().length, 11);
  for (let index = 1; index <= 11; index++) {
    assert.equal(h.rows()[index - 1].label, `Concept ${index}: off track`);
    assert.match(h.rows()[index - 1].text, new RegExp(`Personal next step ${index}\\.`));
    assert.match(h.rows()[index - 1].text, new RegExp(`${index} recorded`));
    assert.match(h.rows()[index - 1].text, new RegExp(`${index + 4} target`));
  }
  assert.match(h.text(), /17 concepts reviewed/);
  assert.match(h.text(), /11 concepts need attention/);
  assert.match(h.text(), /1 without scored data/);
  assert.match(h.text(), /2 not applicable/);
  assert.equal(h.calls.length, 1);
  assert.equal(h.calls[0].url, '/api/coach-insight?userId=42');
  assert.equal(h.calls[0].options.cache, 'no-store');
  assert.deepEqual(h.buttons(), []);
});

test('injected on-track, unlogged and not-applicable concepts never display corrective guidance', async t => {
  const extras = ['on_track', 'unlogged', 'not_applicable'].map(status => ({
    status, pillar_key: 'resilience', concept_key: status, label: `HIDDEN ${status}`, guidance: `UNWANTED ADVICE ${status}`,
  }));
  const h = harness(async () => sample({ extras })); t.after(() => h.unmount()); await h.flush();
  assert.equal(h.rows().length, 2);
  assert.doesNotMatch(h.text(), /HIDDEN|UNWANTED ADVICE/);
  assert.match(h.text(), /Personal next step 1/);
});

test('each concept keeps its own 100-word budget including its reason, even with older oversized responses', async t => {
  const data = sample({ offTrackCount: 3 });
  const [first, second, third] = data.available_concepts;
  first.reason = 'Your latest result is below your target.';
  first.guidance = 'Take one small step today. ' + 'Long guidance continues '.repeat(60);
  second.reason = 'Oversized reason '.repeat(40);
  second.guidance = Array.from({ length: 150 }, (_, i) => `advice${i + 1}`).join('\n');
  third.reason = '';
  third.guidance = Array.from({ length: 100 }, (_, i) => `step${i + 1}`).join(' ');
  const h = harness(async () => data); t.after(() => h.unmount()); await h.flush();
  assert.equal(h.rows().length, 3);
  for (const row of h.rows()) assert.ok(row.narrative.trim().split(/\s+/).length <= 100);
  assert.equal(h.rows()[0].narrative, `${first.reason} Take one small step today.`);
  assert.match(h.rows()[1].narrative, /advice75…$/);
  assert.doesNotMatch(h.rows()[1].narrative, /advice76\b/);
  assert.equal(h.rows()[2].narrative.trim(), third.guidance);
});

test('an all-on-track review confirms progress without corrective guidance or fabricated off-track cards', async t => {
  const h = harness(async () => sample({ offTrackCount: 0, onTrackCount: 12, notApplicableCount: 2 }));
  t.after(() => h.unmount()); await h.flush();
  assert.match(h.text(), /You're on track/);
  assert.match(h.text(), /14 concepts reviewed/);
  assert.match(h.text(), /12 on track/);
  assert.equal(h.rows().length, 0);
  assert.doesNotMatch(h.text(), /Your next step|Where to focus|concepts need attention/);
});

test('partial and empty reviews distinguish unscored concepts from off-track progress without requesting repeat check-ins', async t => {
  for (const [data, expected] of [
    [sample({ offTrackCount: 0, onTrackCount: 4, unloggedCount: 3 }), /Your scored concepts are on track.*do not yet have scored data/],
    [sample({ offTrackCount: 0, onTrackCount: 0, unloggedCount: 7 }), /isn't enough scored check-in data/],
    [sample({ offTrackCount: 0, onTrackCount: 0 }), /0 concepts reviewed/],
  ]) {
    const h = harness(async () => data); t.after(() => h.unmount()); await h.flush();
    assert.match(h.text(), /More data needed/);
    assert.match(h.text(), expected);
    assert.equal(h.rows().length, 0);
    assert.doesNotMatch(h.text(), /Your next step|You're on track/);
    assert.doesNotMatch(h.text(), /remaining check-ins|awaiting check-ins|Complete your/);
  }
});

test('a complete set of yesterday\'s answers is dated as saved evidence without asking for today\'s check-ins', async t => {
  const data = sample({ offTrackCount: 2, onTrackCount: 6, notApplicableCount: 2 });
  data.insight_date = '2026-11-23';
  data.review.evidence_start_date = '2026-11-22';
  data.review.evidence_end_date = '2026-11-22';
  data.available_concepts.forEach(concept => { concept.anchor_date = '2026-11-22'; });
  const h = harness(async () => data); t.after(() => h.unmount()); await h.flush();
  assert.match(h.text(), /10 concepts reviewed/);
  assert.match(h.text(), /Based on your latest saved answers · 22 Nov/);
  assert.equal(h.rows().length, 2);
  h.rows().forEach(row => assert.match(row.text, /Latest check-in\s+· 22 Nov/));
  assert.doesNotMatch(h.text(), /23 Nov|without scored data|remaining check-ins|awaiting check-ins|Complete your/);
});

test('summary evidence dates include on-track and neutral answers when no off-track cards exist', async t => {
  const data = sample({ offTrackCount: 0, onTrackCount: 5, notApplicableCount: 2 });
  data.insight_date = '2026-11-23';
  data.review.evidence_start_date = '2026-11-22';
  data.review.evidence_end_date = '2026-11-22';
  const h = harness(async () => data); t.after(() => h.unmount()); await h.flush();
  assert.match(h.text(), /Based on your latest saved answers · 22 Nov/);
  assert.match(h.text(), /You're on track/);
  assert.equal(h.rows().length, 0);
  assert.doesNotMatch(h.text(), /23 Nov|without scored data|More data needed/);
});

test('mixed latest answer dates appear as the evidence range instead of the date the insight was generated', async t => {
  for (const [first, last, expected] of [
    ['2026-11-20', '2026-11-22', '20–22 Nov'],
    ['2026-10-01', '2026-11-22', '1 Oct–22 Nov'],
  ]) {
    const data = sample({ offTrackCount: 0, onTrackCount: 8 });
    data.insight_date = '2026-11-23';
    data.review.evidence_start_date = first;
    data.review.evidence_end_date = last;
    const h = harness(async () => data); t.after(() => h.unmount()); await h.flush();
    assert.ok(h.text().includes(`Based on your latest saved answers · ${expected}`));
    assert.doesNotMatch(h.text(), /23 Nov|last 7 days|without scored data/);
  }
});

test('no evidence dates leave the review undated and identify missing scored data without inventing a saved answer date', async t => {
  const data = sample({ offTrackCount: 0, onTrackCount: 0, unloggedCount: 10 });
  data.insight_date = '2026-11-23';
  data.review.evidence_start_date = null;
  data.review.evidence_end_date = null;
  const h = harness(async () => data); t.after(() => h.unmount()); await h.flush();
  assert.match(h.text(), /More data needed/);
  assert.match(h.text(), /10 without scored data/);
  assert.doesNotMatch(h.text(), /Based on your latest saved answers|23 Nov|remaining check-ins|awaiting check-ins/);
  assert.equal(h.rows().length, 0);
});

test('complete neutral answers do not falsely claim missing check-ins or demand more data', async t => {
  const data = sample({ offTrackCount: 0, onTrackCount: 0, notApplicableCount: 6 });
  data.review.evidence_start_date = '2026-11-22';
  data.review.evidence_end_date = '2026-11-22';
  const h = harness(async () => data); t.after(() => h.unmount()); await h.flush();
  assert.match(h.text(), /No guidance needed/);
  assert.match(h.text(), /Your saved answers mark these concepts as not applicable/);
  assert.match(h.text(), /Based on your latest saved answers · 22 Nov/);
  assert.match(h.text(), /6 not applicable/);
  assert.doesNotMatch(h.text(), /More data needed|without scored data|remaining check-ins|awaiting check-ins|Your next step/);
  assert.equal(h.rows().length, 0);
});

test('loading is accessible and a failed request can be retried without exposing server details', async t => {
  let resolveFirst;
  const h = harness(async (_url, _options, attempt) => attempt === 1 ? new Promise(resolve => { resolveFirst = resolve; }) : sample());
  t.after(() => h.unmount()); await h.flush();
  assert.deepEqual(h.roles(), ['status']);
  assert.match(h.text(), /Reviewing all your concepts/);
  assert.equal(h.rows().length, 0);
  resolveFirst(new Response('PRIVATE SERVER DETAIL', { status: 503 })); await h.flush();
  assert.deepEqual(h.roles(), ['alert']);
  assert.match(h.text(), /Could not load your insights/);
  assert.doesNotMatch(h.text(), /PRIVATE SERVER DETAIL/);
  await h.click('Try again');
  assert.equal(h.calls.length, 2);
  assert.equal(h.calls[0].options.signal.aborted, true);
  assert.equal(h.rows().length, 2);
  assert.doesNotMatch(h.text(), /Could not load|Reviewing/);
});

test('network failures offer retry and do not leak private error messages', async t => {
  const h = harness(async () => { throw new Error('PRIVATE NETWORK DETAIL'); });
  t.after(() => h.unmount()); await h.flush();
  assert.deepEqual(h.roles(), ['alert']);
  assert.deepEqual(h.buttons(), ['Try again']);
  assert.doesNotMatch(h.text(), /PRIVATE NETWORK DETAIL/);
});

test('mismatched users and incomplete or inconsistent reviews are rejected without rendering guidance', async t => {
  const wrongTotal = sample(); wrongTotal.review.reviewed_count++;
  const wrongStatus = sample(); wrongStatus.review.status = 'on_track';
  const noGuidance = sample(); delete noGuidance.available_concepts[0].guidance;
  const wrongOffTrackCount = sample(); wrongOffTrackCount.available_concepts.pop();
  const negativeCount = sample(); negativeCount.review.unlogged_count = -1;
  const nullConcept = sample(); nullConcept.available_concepts.push(null);
  const nullOnTrack = sample({ offTrackCount: 0 }); nullOnTrack.available_concepts.push(null);
  for (const data of [sample({ userId: 99 }), {}, null, wrongTotal, wrongStatus, noGuidance, wrongOffTrackCount, negativeCount, nullConcept, nullOnTrack,
    new Response('not JSON', { headers: { 'content-type': 'application/json' } }),
  ]) {
    const h = harness(async () => data); t.after(() => h.unmount()); await h.flush();
    assert.deepEqual(h.roles(), ['alert']);
    assert.equal(h.rows().length, 0);
    assert.doesNotMatch(h.text(), /Personal next step/);
  }
});

test('changing members aborts the old request and ignores its late response while the new review loads', async t => {
  const pending = [];
  const h = harness((url, options) => new Promise(resolve => pending.push({ url, options, resolve })));
  t.after(() => h.unmount()); await h.flush();
  await h.update({ userId: '43' });
  assert.equal(pending[0].options.signal.aborted, true);
  assert.equal(pending[1].options.signal.aborted, false);
  assert.equal(pending[1].url, '/api/coach-insight?userId=43');
  const stale = sample(); stale.available_concepts[0].guidance = 'STALE MEMBER GUIDANCE';
  pending[0].resolve(stale); await h.flush();
  assert.match(h.text(), /Reviewing all your concepts/);
  assert.doesNotMatch(h.text(), /STALE MEMBER GUIDANCE|Could not load/);
  pending[1].resolve(sample({ userId: 43, offTrackCount: 0, onTrackCount: 5 })); await h.flush();
  assert.match(h.text(), /You're on track/);
  assert.doesNotMatch(h.renders.join('\n'), /STALE MEMBER GUIDANCE/);
});

test('changing members hides an already loaded review immediately until their own data arrives', async t => {
  let resolveNext;
  const h = harness((_url, _options, attempt) => attempt === 1 ? sample() : new Promise(resolve => { resolveNext = resolve; }));
  t.after(() => h.unmount()); await h.flush();
  assert.match(h.text(), /Personal next step/);
  const renderOffset = h.renders.length;
  await h.update({ userId: '43' });
  assert.match(h.text(), /Reviewing all your concepts/);
  assert.doesNotMatch(h.renders.slice(renderOffset).join('\n'), /Personal next step/);
  resolveNext(sample({ userId: 43, offTrackCount: 0, onTrackCount: 3 })); await h.flush();
  assert.match(h.text(), /3 concepts reviewed/);
});

test('unmounting aborts an in-flight review and late completion cannot update component state', async () => {
  let resolve;
  const h = harness(() => new Promise(done => { resolve = done; }));
  await h.flush(); h.unmount();
  assert.equal(h.calls[0].options.signal.aborted, true);
  resolve(sample()); await h.flush();
  assert.equal(h.updatesAfterUnmount(), 0);
  assert.doesNotMatch(h.renders.join('\n'), /Personal next step/);
});
