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
const guidanceIconExports = {};
vm.runInNewContext(compile('src/components/GuidanceIcon.tsx'), { exports: guidanceIconExports, require });

function sample({ userId = 42, offTrackCount = 2, onTrackCount = 2, unloggedCount = 0, notApplicableCount = 0, focusCount = Math.min(offTrackCount, 6), extras = [] } = {}) {
  const pillarKeys = ['nutrition', 'training', 'recovery', 'resilience', 'reflection', 'purpose'];
  return {
    user_id: userId,
    review: {
      status: offTrackCount > 0 ? 'off_track' : onTrackCount > 0 && unloggedCount === 0 ? 'on_track' : 'insufficient_data',
      reviewed_count: offTrackCount + onTrackCount + unloggedCount + notApplicableCount,
      off_track_count: offTrackCount, on_track_count: onTrackCount,
      unlogged_count: unloggedCount, not_applicable_count: notApplicableCount,
      focus_count: focusCount,
      week_start_date: '2026-11-16', through_date: '2026-11-18',
    },
    available_concepts: [
      ...Array.from({ length: focusCount }, (_, index) => ({
        status: 'off_track', pillar_key: pillarKeys[index],
        pillar_label: pillarKeys[index][0].toUpperCase() + pillarKeys[index].slice(1),
        concept_key: `concept_${index + 1}`, label: `Concept ${index + 1}`,
        guidance: `Personal next step ${index + 1}.`, reflection: `Personal reflection ${index + 1}?`,
        reason: `Recorded result ${index + 1} is below your target.`,
        score: index + 20, anchor_date: '2026-11-18', latest_value: `${index + 1} recorded`, target_label: `${index + 5} target`,
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
      return name === 'react' ? react : name === '@/lib/pillars' ? paletteExports : name === '@/components/PillarIcon' ? iconExports : name === '@/components/GuidanceIcon' ? guidanceIconExports : require(name);
    },
  });
  const text = node => node == null || typeof node === 'boolean' ? '' : Array.isArray(node) ? node.map(text).join(' ') : typeof node === 'object' ? text(node.props?.children) : String(node);
  const visualText = node => node == null || typeof node === 'boolean' ? '' : Array.isArray(node) ? node.map(visualText).join(' ') : typeof node === 'object' ? /(?:^|\s)sr-only(?:\s|$)/.test(node.props?.className || '') ? '' : visualText(node.props?.children) : String(node);
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
      narrative: all(node, child => child.type === 'p' && /leading-8/.test(child.props.className || '')).map(text).join(' '),
      guidanceBodies: all(node, child => child.type === 'p' && /leading-8/.test(child.props.className || '')).map(text),
      guidanceClasses: all(node, child => child.type === 'p' && /leading-8/.test(child.props.className || '')).map(child => child.props.className),
      guidanceHeadings: all(node, child => child.type === 'h4').map(heading => ({
        title: text(heading).trim(), visibleText: visualText(heading).trim(),
        icons: all(heading, child => child.type === 'svg').map(icon => ({
          hidden: icon.props['aria-hidden'], paths: all(icon, child => child.type === 'path').length,
          ellipses: all(icon, child => child.type === 'ellipse').length, circles: all(icon, child => child.type === 'circle').length,
        })),
      })),
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

test('opening Insight shows one focus per pillar with its weekly score, target and guidance while the review counts every off-track concept', async t => {
  const h = harness(async () => sample({ offTrackCount: 11, onTrackCount: 3, unloggedCount: 1, notApplicableCount: 2 }));
  t.after(() => h.unmount()); await h.flush();
  assert.equal(h.rows().length, 6);
  for (let index = 1; index <= 6; index++) {
    assert.equal(h.rows()[index - 1].label, `Concept ${index}: off track`);
    assert.deepEqual(h.rows()[index - 1].guidanceBodies, [`Personal next step ${index}.`, `Personal reflection ${index}?`]);
    assert.match(h.rows()[index - 1].text, new RegExp(`${index + 19} / 100`));
    assert.match(h.rows()[index - 1].text, new RegExp(`${index + 4} target`));
  }
  assert.match(h.text(), /Week to date · 16–18 Nov/);
  assert.match(h.text(), /Focus on one concept per pillar needing support this week/);
  assert.doesNotMatch(h.text(), /concepts reviewed|concepts need attention|without scored data|not applicable|Latest check-in|Recorded result|\d+ recorded/);
  assert.equal(h.calls.length, 1);
  assert.equal(h.calls[0].url, '/api/coach-insight?userId=42');
  assert.equal(h.calls[0].options.cache, 'no-store');
  assert.deepEqual(h.buttons(), []);
});

test('legacy responses with several concepts per pillar show only the lowest score including zero and retain the first concept on ties', async t => {
  const data = sample({ offTrackCount: 8 });
  delete data.review.focus_count;
  const template = data.available_concepts[0];
  const concepts = [
    ['nutrition', 'Higher nutrition', 45],
    ['training', 'Unscored training', null],
    ['recovery', 'First tied recovery', 20],
    ['nutrition', 'Zero nutrition', 0],
    ['nutrition', 'Second zero nutrition', 0],
    ['training', 'Lowest training', 10],
    ['training', 'Higher training', 30],
    ['recovery', 'Second tied recovery', 20],
  ];
  data.available_concepts = concepts.map(([pillar_key, label, score], index) => ({
    ...template, pillar_key, label, score, concept_key: `legacy_${index}`,
    guidance: `Action for ${label}.`, reflection: `Reflection for ${label}?`,
  }));
  const h = harness(async () => data); t.after(() => h.unmount()); await h.flush();
  assert.deepEqual(h.rows().map(row => row.label), [
    'Zero nutrition: off track', 'Lowest training: off track', 'First tied recovery: off track',
  ]);
  assert.deepEqual(h.rows().map(row => row.guidanceBodies), [
    ['Action for Zero nutrition.', 'Reflection for Zero nutrition?'],
    ['Action for Lowest training.', 'Reflection for Lowest training?'],
    ['Action for First tied recovery.', 'Reflection for First tied recovery?'],
  ]);
  assert.match(h.rows()[0].text, /0 \/ 100/);
  assert.doesNotMatch(h.text(), /Higher nutrition|Unscored training|Second zero nutrition|Higher training|Second tied recovery/);
  assert.equal(h.calls.length, 1);
});

test('injected on-track, unlogged and not-applicable concepts never display corrective guidance', async t => {
  const extras = ['on_track', 'unlogged', 'not_applicable'].map(status => ({
    status, pillar_key: 'resilience', concept_key: status, label: `HIDDEN ${status}`,
    guidance: `UNWANTED ADVICE ${status}`, reflection: `UNWANTED REFLECTION ${status}`,
  }));
  const h = harness(async () => sample({ extras })); t.after(() => h.unmount()); await h.flush();
  assert.equal(h.rows().length, 2);
  assert.doesNotMatch(h.text(), /HIDDEN|UNWANTED ADVICE|UNWANTED REFLECTION/);
  assert.match(h.text(), /Personal next step 1/);
});

test('each concept shares a 100-word budget across action and reflection without spending words on an obsolete reason', async t => {
  const data = sample({ offTrackCount: 3 });
  const [first, second, third] = data.available_concepts;
  first.reason = 'Your latest result is below your target.';
  first.guidance = 'Take one small step today. ' + 'Long guidance continues '.repeat(60);
  second.reason = 'Oversized reason '.repeat(40);
  second.guidance = Array.from({ length: 150 }, (_, i) => `advice${i + 1}`).join('\n');
  second.reflection = Array.from({ length: 60 }, (_, i) => `reflection${i + 1}`).join(' ');
  third.reason = '';
  third.guidance = Array.from({ length: 75 }, (_, i) => `step${i + 1}`).join(' ');
  third.reflection = Array.from({ length: 25 }, (_, i) => `question${i + 1}`).join(' ');
  const h = harness(async () => data); t.after(() => h.unmount()); await h.flush();
  assert.equal(h.rows().length, 3);
  for (const row of h.rows()) assert.ok(row.narrative.trim().split(/\s+/).length <= 100);
  assert.deepEqual(h.rows()[0].guidanceBodies, ['Take one small step today.', first.reflection]);
  assert.match(h.rows()[1].guidanceBodies[0], /advice75…$/);
  assert.match(h.rows()[1].guidanceBodies[1], /reflection25…$/);
  assert.doesNotMatch(h.rows()[1].narrative, /advice76\b|reflection26\b/);
  assert.deepEqual(h.rows()[2].guidanceBodies, [third.guidance, third.reflection]);
  assert.equal(h.rows()[2].narrative.trim().split(/\s+/).length, 100);
  assert.doesNotMatch(h.text(), /Your latest result|Oversized reason/);
});

test('each concept restores action then reflection with icon-only headers, accessible labels and larger readable bodies', async t => {
  const h = harness(); t.after(() => h.unmount()); await h.flush();
  for (const row of h.rows()) {
    assert.deepEqual(row.guidanceHeadings, [
      { title: 'One small step', visibleText: '', icons: [{ hidden: 'true', paths: 4, ellipses: 0, circles: 0 }] },
      { title: 'A moment to reflect', visibleText: '', icons: [{ hidden: 'true', paths: 0, ellipses: 1, circles: 2 }] },
    ]);
    assert.equal(row.guidanceClasses.length, 2);
    for (const className of row.guidanceClasses) {
      assert.match(className, /(?:^|\s)text-lg(?:\s|$)/);
      assert.match(className, /(?:^|\s)leading-8(?:\s|$)/);
      assert.match(className, /(?:^|\s)sm:text-xl(?:\s|$)/);
    }
  }
});

test('older responses without reflection still show a concept-specific question within the combined word limit', async t => {
  for (const reflection of [undefined, null, '', ' \n ']) {
    const data = sample({ offTrackCount: 1 });
    const concept = data.available_concepts[0];
    concept.label = 'Protein intake';
    concept.reflection = reflection;
    concept.guidance = Array.from({ length: 120 }, (_, index) => `action${index + 1}`).join(' ');
    const h = harness(async () => data); t.after(() => h.unmount()); await h.flush();
    assert.equal(h.rows().length, 1);
    const [action, question] = h.rows()[0].guidanceBodies;
    assert.equal(question, 'What would help you work towards your existing protein intake target this week?');
    assert.match(action, /^action1 /);
    assert.ok(h.rows()[0].narrative.trim().split(/\s+/).length <= 100);
    assert.deepEqual(h.rows()[0].guidanceHeadings.map(heading => heading.title), ['One small step', 'A moment to reflect']);
    assert.doesNotMatch(h.text(), /Could not load/);
  }
});

test('an all-on-track review confirms progress without corrective guidance or fabricated off-track cards', async t => {
  const h = harness(async () => sample({ offTrackCount: 0, onTrackCount: 12, notApplicableCount: 2 }));
  t.after(() => h.unmount()); await h.flush();
  assert.match(h.text(), /You're on track/);
  assert.match(h.text(), /on track so far this week/);
  assert.match(h.text(), /Week to date · 16–18 Nov/);
  assert.equal(h.rows().length, 0);
  assert.doesNotMatch(h.text(), /One small step|A moment to reflect|Where to focus|concepts need attention|concepts reviewed|12 on track|2 not applicable/);
});

test('partial and empty reviews distinguish unscored concepts from off-track progress without requesting repeat check-ins', async t => {
  for (const [data, expected] of [
    [sample({ offTrackCount: 0, onTrackCount: 4, unloggedCount: 3 }), /Your scored concepts are on track.*do not yet have scored data/],
    [sample({ offTrackCount: 0, onTrackCount: 0, unloggedCount: 7 }), /isn't enough scored check-in data/],
    [sample({ offTrackCount: 0, onTrackCount: 0 }), /isn't enough scored check-in data this week/],
  ]) {
    const h = harness(async () => data); t.after(() => h.unmount()); await h.flush();
    assert.match(h.text(), /More data needed/);
    assert.match(h.text(), expected);
    assert.equal(h.rows().length, 0);
    assert.doesNotMatch(h.text(), /One small step|A moment to reflect|You're on track/);
    assert.doesNotMatch(h.text(), /remaining check-ins|awaiting check-ins|Complete your/);
  }
});

test('the requested week-to-date window stays visible even when insight generation and latest-answer dates differ', async t => {
  const data = sample({ offTrackCount: 2, onTrackCount: 6, notApplicableCount: 2 });
  data.insight_date = '2026-11-25';
  data.review.evidence_start_date = '2026-11-19';
  data.review.evidence_end_date = '2026-11-22';
  data.available_concepts.forEach(concept => { concept.anchor_date = '2026-11-22'; });
  const h = harness(async () => data); t.after(() => h.unmount()); await h.flush();
  assert.match(h.text(), /Week to date · 16–18 Nov/);
  assert.equal(h.rows().length, 2);
  h.rows().forEach(row => assert.match(row.text, /Score to date/));
  assert.doesNotMatch(h.text(), /19 Nov|22 Nov|25 Nov|latest saved answers|Latest check-in|without scored data|remaining check-ins|awaiting check-ins|Complete your/);
});

test('the weekly period appears for on-track and neutral answers when no off-track cards exist', async t => {
  const data = sample({ offTrackCount: 0, onTrackCount: 5, notApplicableCount: 2 });
  data.insight_date = '2026-11-25';
  const h = harness(async () => data); t.after(() => h.unmount()); await h.flush();
  assert.match(h.text(), /Week to date · 16–18 Nov/);
  assert.match(h.text(), /You're on track/);
  assert.equal(h.rows().length, 0);
  assert.doesNotMatch(h.text(), /25 Nov|without scored data|More data needed|concepts reviewed/);
});

test('weekly dates format first-day, same-month and cross-month windows without using the generation date', async t => {
  for (const [first, last, expected] of [
    ['2026-11-16', '2026-11-16', '16 Nov'],
    ['2026-11-16', '2026-11-18', '16–18 Nov'],
    ['2026-10-26', '2026-11-01', '26 Oct–1 Nov'],
  ]) {
    const data = sample({ offTrackCount: 0, onTrackCount: 8 });
    data.insight_date = '2026-11-25';
    data.review.week_start_date = first;
    data.review.through_date = last;
    const h = harness(async () => data); t.after(() => h.unmount()); await h.flush();
    assert.ok(h.text().includes(`Week to date · ${expected}`));
    assert.doesNotMatch(h.text(), /25 Nov|last 7 days|without scored data|latest saved answers/);
  }
});

test('missing or invalid weekly dates do not fall back to generation or saved-answer dates', async t => {
  const data = sample({ offTrackCount: 0, onTrackCount: 0, unloggedCount: 10 });
  data.insight_date = '2026-11-25';
  data.review.evidence_start_date = '2026-11-22';
  data.review.evidence_end_date = '2026-11-22';
  for (const [start, through] of [[null, null], ['2026-11-31', 'not-a-date']]) {
    data.review.week_start_date = start;
    data.review.through_date = through;
    const h = harness(async () => data); t.after(() => h.unmount()); await h.flush();
    assert.match(h.text(), /Week to date/);
    assert.match(h.text(), /More data needed/);
    assert.match(h.text(), /isn't enough scored check-in data this week/);
    assert.doesNotMatch(h.text(), /Week to date ·|latest saved answers|22 Nov|25 Nov|31 Nov|not-a-date|10 without scored data|remaining check-ins|awaiting check-ins/);
    assert.equal(h.rows().length, 0);
  }
});

test('extra progression details and obsolete narratives remain out of the weekly guidance presentation', async t => {
  const data = sample({ offTrackCount: 1, onTrackCount: 3, unloggedCount: 2, notApplicableCount: 4 });
  const concept = data.available_concepts[0];
  concept.reason = 'PRIVATE OLD REASON';
  concept.latest_value = 'PRIVATE LATEST VALUE';
  concept.anchor_date = '2026-10-02';
  concept.days = [{ date: '2026-10-02', value_label: 'PRIVATE DAILY LOG', score: 0 }];
  concept.score_explanation = 'PRIVATE SCORE BREAKDOWN';
  concept.answered_days_count = 99;
  concept.scored_days_count = 98;
  concept.not_applicable_days_count = 97;
  data.review.evidence_start_date = '2026-10-01';
  data.review.evidence_end_date = '2026-10-02';
  const h = harness(async () => data); t.after(() => h.unmount()); await h.flush();
  assert.match(h.text(), /Week to date · 16–18 Nov/);
  assert.match(h.text(), /20 \/ 100/);
  assert.match(h.text(), /5 target/);
  assert.match(h.text(), /Personal next step 1/);
  assert.doesNotMatch(h.text(), /PRIVATE|1 Oct|2 Oct|99|98|97|concepts reviewed|3 on track|2 without scored data|4 not applicable|Latest check-in|days answered|days scored|check-ins this week/);
});

test('complete neutral answers do not falsely claim missing check-ins or demand more data', async t => {
  const data = sample({ offTrackCount: 0, onTrackCount: 0, notApplicableCount: 6 });
  const h = harness(async () => data); t.after(() => h.unmount()); await h.flush();
  assert.match(h.text(), /No guidance needed/);
  assert.match(h.text(), /Your answers this week mark these concepts as not applicable/);
  assert.match(h.text(), /Week to date · 16–18 Nov/);
  assert.doesNotMatch(h.text(), /6 not applicable|concepts reviewed/);
  assert.doesNotMatch(h.text(), /More data needed|without scored data|remaining check-ins|awaiting check-ins|One small step|A moment to reflect/);
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
  const invalidReflection = sample(); invalidReflection.available_concepts[0].reflection = { private: 'PRIVATE MALFORMED REFLECTION' };
  const duplicatePillar = sample(); duplicatePillar.available_concepts[1].pillar_key = duplicatePillar.available_concepts[0].pillar_key;
  const mismatchedFocusCount = sample(); mismatchedFocusCount.review.focus_count = 1;
  const malformedFocusCounts = [-1, 1.5, '2', 3].map(focusCount => {
    const data = sample(); data.review.focus_count = focusCount; return data;
  });
  const noFocusForOffTrack = sample({ offTrackCount: 2, focusCount: 0 });
  for (const data of [sample({ userId: 99 }), {}, null, wrongTotal, wrongStatus, noGuidance, wrongOffTrackCount, negativeCount, nullConcept, nullOnTrack,
    invalidReflection, duplicatePillar, mismatchedFocusCount, noFocusForOffTrack, ...malformedFocusCounts,
    new Response('not JSON', { headers: { 'content-type': 'application/json' } }),
  ]) {
    const h = harness(async () => data); t.after(() => h.unmount()); await h.flush();
    assert.deepEqual(h.roles(), ['alert']);
    assert.equal(h.rows().length, 0);
    assert.doesNotMatch(h.text(), /Personal next step|Personal reflection|PRIVATE MALFORMED REFLECTION/);
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
  const stale = sample(); stale.available_concepts[0].guidance = 'STALE MEMBER GUIDANCE'; stale.available_concepts[0].reflection = 'STALE MEMBER REFLECTION';
  pending[0].resolve(stale); await h.flush();
  assert.match(h.text(), /Reviewing all your concepts/);
  assert.doesNotMatch(h.text(), /STALE MEMBER GUIDANCE|STALE MEMBER REFLECTION|Could not load/);
  pending[1].resolve(sample({ userId: 43, offTrackCount: 0, onTrackCount: 5 })); await h.flush();
  assert.match(h.text(), /You're on track/);
  assert.doesNotMatch(h.renders.join('\n'), /STALE MEMBER GUIDANCE|STALE MEMBER REFLECTION/);
});

test('changing members hides an already loaded review immediately until their own data arrives', async t => {
  let resolveNext;
  const h = harness((_url, _options, attempt) => attempt === 1 ? sample() : new Promise(resolve => { resolveNext = resolve; }));
  t.after(() => h.unmount()); await h.flush();
  assert.match(h.text(), /Personal next step/);
  const renderOffset = h.renders.length;
  await h.update({ userId: '43' });
  assert.match(h.text(), /Reviewing all your concepts/);
  assert.doesNotMatch(h.renders.slice(renderOffset).join('\n'), /Personal next step|Personal reflection/);
  resolveNext(sample({ userId: 43, offTrackCount: 0, onTrackCount: 3 })); await h.flush();
  assert.match(h.text(), /You're on track/);
  assert.match(h.text(), /Week to date · 16–18 Nov/);
});

test('unmounting aborts an in-flight review and late completion cannot update component state', async () => {
  let resolve;
  const h = harness(() => new Promise(done => { resolve = done; }));
  await h.flush(); h.unmount();
  assert.equal(h.calls[0].options.signal.aborted, true);
  resolve(sample()); await h.flush();
  assert.equal(h.updatesAfterUnmount(), 0);
  assert.doesNotMatch(h.renders.join('\n'), /Personal next step|Personal reflection/);
});
