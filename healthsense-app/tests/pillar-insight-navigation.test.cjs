// Run with: node --test tests/pillar-insight-navigation.test.cjs
// Exercise the real component with browser geometry and React hook state simulated.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');

const source = fs.readFileSync(path.join(__dirname, '../src/components/PillarInsightHistory.tsx'), 'utf8');
const compiled = ts.transpileModule(source, { compilerOptions: {
  module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2017,
} }).outputText;
const today = { id: 1, quote_date: '2026-11-17', quote: 'TODAY. ' + 'A longer reflection to read carefully. '.repeat(30) };
const earlier = { id: 2, quote_date: '2026-11-15', quote: 'A short earlier insight.' };
const oldest = { id: 3, quote_date: '2026-11-10', quote: 'OLDEST. ' + 'An older long reflection. '.repeat(30) };
const page = (insights, has_more = false, next_before = null, user_id = 42) => ({ user_id, pillar_key: 'resilience', insights, has_more, next_before });

function harness(fetchPage = async () => page([today, earlier, oldest])) {
  let slots = [], cursor = 0, pendingEffects = [], tree, dirty = true, wrapperKey, requestId = 0;
  let props = { userId: '42', pillarKey: 'resilience', pillarLabel: 'Resilience', currentQuote: 'Current undated fallback.', currentDate: '2026-11-17' };
  const frames = new Map(), observers = [], calls = [], events = [], nodes = new Map();
  const equal = (left, right) => left && right && left.length === right.length && left.every((value, i) => Object.is(value, right[i]));
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
        pendingEffects.push(() => { cleanup?.(); slots[index].cleanup = fn(); });
      }
    },
  };
  react.useLayoutEffect = react.useEffect;
  const window = {
    requestAnimationFrame(fn) { frames.set(++requestId, fn); return requestId; },
    cancelAnimationFrame(id) { frames.delete(id); },
    addEventListener() {}, removeEventListener() {}, matchMedia: () => ({ matches: true }),
  };
  class IntersectionObserver {
    constructor(callback) { this.callback = callback; observers.push(this); }
    observe() {} disconnect() {}
  }
  class ResizeObserver { observe() {} disconnect() {} }
  const exports = {};
  vm.runInNewContext(compiled, {
    exports, window, document: { addEventListener() {}, removeEventListener() {} },
    IntersectionObserver, ResizeObserver, AbortController, URLSearchParams, console, setTimeout, clearTimeout, queueMicrotask,
    requestAnimationFrame: window.requestAnimationFrame, cancelAnimationFrame: window.cancelAnimationFrame,
    fetch: async (url, options) => {
      calls.push({ url, options });
      return { ok: true, json: async () => fetchPage(url, options) };
    },
    require: name => name === 'react' ? react : require(name),
  });
  const text = node => node == null || typeof node === 'boolean' ? '' : Array.isArray(node) ? node.map(text).join(' ') : typeof node === 'object' ? text(node.props?.children) : String(node);
  const all = (node, predicate) => {
    if (node == null || typeof node !== 'object') return [];
    if (Array.isArray(node)) return node.flatMap(child => all(child, predicate));
    return [...(predicate(node) ? [node] : []), ...all(node.props?.children, predicate)];
  };
  const expand = (node, location = 'root') => {
    if (node == null || typeof node !== 'object') return node;
    if (Array.isArray(node)) return node.map((child, i) => expand(child, `${location}.${i}`));
    if (typeof node.type === 'function') return expand(node.type(node.props), location);
    const element = { ...node, props: { ...node.props, children: expand(node.props?.children, `${location}.children`) } };
    if (element.props.ref) {
      let host = nodes.get(location);
      if (!host) {
        host = { position: 0, captured: new Set(), clientHeight: 188,
          get scrollHeight() { return Math.max(this.clientHeight, Math.ceil(text(this.element).length / 40) * 24); },
          get scrollTop() { return this.position; },
          set scrollTop(value) {
            const next = Math.max(0, Math.min(value, this.scrollHeight - this.clientHeight));
            if (next !== this.position) { this.position = next; events.push(() => this.element.props.onScroll?.({ currentTarget: this })); }
          },
          scrollBy({ top }) { this.scrollTop += top; }, scrollTo({ top }) { this.scrollTop = top; },
          setPointerCapture(id) { this.captured.add(id); }, hasPointerCapture(id) { return this.captured.has(id); }, releasePointerCapture(id) { this.captured.delete(id); }, focus() {},
        };
        nodes.set(location, host);
      }
      host.element = element;
      if (typeof element.props.ref === 'function') element.props.ref(host);
      else element.props.ref.current = host;
    }
    return element;
  };
  const render = () => {
    const wrapper = exports.default(props);
    if (wrapperKey !== undefined && wrapper.key !== wrapperKey) {
      slots.forEach(slot => slot?.cleanup?.()); slots = []; nodes.clear(); frames.clear(); pendingEffects = [];
    }
    wrapperKey = wrapper.key;
    cursor = 0; dirty = false;
    tree = expand(wrapper.type(wrapper.props));
    const effects = pendingEffects; pendingEffects = []; effects.forEach(fn => fn());
  };
  const flush = async () => {
    for (let i = 0; i < 20; i++) {
      if (dirty) render();
      const work = events.splice(0); work.forEach(fn => fn());
      const callbacks = Array.from(frames.values()); frames.clear(); callbacks.forEach(fn => fn());
      await new Promise(resolve => setImmediate(resolve));
      if (!dirty && !events.length && !frames.size) {
        await new Promise(resolve => setImmediate(resolve));
        if (!dirty && !events.length && !frames.size) return;
      }
    }
    throw new Error('Component did not settle');
  };
  const regionElement = () => all(tree, node => node.props?.role === 'region')[0];
  const region = () => Array.from(nodes.values()).find(node => node.element === regionElement());
  const buttons = glyph => all(tree, node => node.type === 'button' && text(node).trim() === glyph);
  return {
    calls, flush,
    async activate() { observers.at(-1).callback([{ isIntersecting: true }]); await flush(); },
    date() { const times = all(tree, node => node.type === 'time'); assert.equal(times.length, 1, 'one insight date at a time'); return times[0].props.dateTime; },
    text: () => text(tree), region,
    async click(glyph) { const button = buttons(glyph)[0]; assert.ok(button, `Missing ${glyph}`); if (!button.props.disabled) button.props.onClick(); await flush(); },
    disabled: glyph => buttons(glyph)[0]?.props.disabled,
    async position(value) { region().scrollTop = value === 'bottom' ? region().scrollHeight : value; await flush(); },
    async pointer({ dy = -90, dx = 0, cancel = false, lost = false, moves = 1, isPrimary = true } = {}) {
      const node = region();
      const event = (x, y) => ({ currentTarget: node, pointerId: 1, pointerType: 'touch', isPrimary, clientX: 100 + x, clientY: 100 + y, preventDefault() { this.prevented = true; } });
      node.element.props.onPointerDown(event(0, 0));
      let move;
      for (let i = 1; i <= moves; i++) { move = event(dx * i / moves, dy * i / moves); node.element.props.onPointerMove(move); }
      if (cancel) node.element.props.onPointerCancel(event(dx, dy));
      if (lost) node.element.props.onLostPointerCapture?.(event(dx, dy));
      node.element.props.onPointerUp(event(dx, dy));
      await flush();
      return move;
    },
    async key(key, repeat = false) {
      const node = region();
      const event = { key, repeat, currentTarget: node, preventDefault() { this.prevented = true; } };
      node.element.props.onKeyDown?.(event);
      if (!event.prevented) {
        if (key === 'ArrowDown') node.scrollTop += 80;
        if (key === 'ArrowUp') node.scrollTop -= 80;
      }
      await flush();
    },
    async pinch() {
      const node = region();
      const event = (id, primary, y) => ({ currentTarget: node, pointerId: id, pointerType: 'touch', isPrimary: primary, clientX: 100, clientY: y, preventDefault() {} });
      node.element.props.onPointerDown(event(1, true, 100));
      node.element.props.onPointerDown(event(2, false, 100));
      node.element.props.onPointerMove(event(1, true, 0));
      node.element.props.onPointerUp(event(1, true, 0));
      await flush();
    },
    async update(next) { props = { ...props, ...next }; dirty = true; await flush(); },
    unmount() { slots.forEach(slot => slot?.cleanup?.()); },
  };
}

test('reads a long current insight before arrow navigation changes exactly one insight', async t => {
  const h = harness(); t.after(() => h.unmount()); await h.flush(); await h.activate();
  assert.equal(h.date(), today.quote_date);
  await h.click('↓');
  assert.equal(h.date(), today.quote_date); assert.ok(h.region().scrollTop > 0);
  await h.position('bottom'); await h.click('↓');
  assert.equal(h.date(), earlier.quote_date); assert.equal(h.region().scrollTop, 0);
  assert.ok(!h.text().includes('TODAY.'));
  await h.click('↓'); assert.equal(h.date(), oldest.quote_date);
  await h.position('bottom'); await h.click('↑');
  assert.equal(h.date(), oldest.quote_date, 'up arrow reads long text before moving newer');
  await h.position(0); await h.click('↑');
  assert.equal(h.date(), earlier.quote_date); assert.equal(h.region().scrollTop, 0);
});

test('a swipe that reaches the boundary only scrolls; a fresh edge swipe pages once', async t => {
  const h = harness(); t.after(() => h.unmount()); await h.flush(); await h.activate();
  await h.position(h.region().scrollHeight - h.region().clientHeight - 20);
  await h.pointer({ dy: -100 }); assert.equal(h.date(), today.quote_date);
  await h.pointer({ dy: -160, moves: 4 }); assert.equal(h.date(), earlier.quote_date);
  await h.pointer({ dy: -100 }); assert.equal(h.date(), oldest.quote_date);
  await h.pointer({ dy: 90 }); assert.equal(h.date(), earlier.quote_date);
});

test('horizontal, tiny, cancelled, lost and secondary-pointer gestures do not page', async t => {
  const h = harness(); t.after(() => h.unmount()); await h.flush(); await h.activate(); await h.position('bottom');
  const horizontal = await h.pointer({ dx: 100, dy: -8 });
  assert.equal(horizontal.prevented, undefined);
  for (const gesture of [{ dy: -10 }, { cancel: true }, { lost: true }, { isPrimary: false }]) {
    await h.pointer(gesture); assert.equal(h.date(), today.quote_date);
  }
});

test('late older-page response cannot override navigation back to a newer insight', async t => {
  let resolveOlder;
  const h = harness(async url => new URL(url, 'https://app.test').searchParams.has('before')
    ? new Promise(resolve => { resolveOlder = resolve; })
    : page([today, earlier], true, earlier.quote_date));
  t.after(() => h.unmount()); await h.flush(); await h.activate(); await h.position('bottom'); await h.click('↓');
  assert.equal(h.date(), earlier.quote_date);
  await h.click('↓'); assert.ok(resolveOlder); assert.equal(h.calls.length, 2);
  await h.click('↑'); assert.equal(h.date(), today.quote_date);
  resolveOlder(page([oldest])); await h.flush(); assert.equal(h.date(), today.quote_date);
});

test('changing member aborts stale requests', async t => {
  let resolveOld;
  const h = harness(async (_url, options) => options.signal.aborted ? page([]) : new Promise(resolve => { resolveOld = resolve; }));
  t.after(() => h.unmount()); await h.flush(); await h.activate();
  const request = h.calls[0];
  await h.update({ userId: '43' }); assert.equal(request.options.signal.aborted, true);
  resolveOld(page([today])); await h.flush(); assert.ok(!h.text().includes('TODAY.'));
});


test('holding a keyboard key or pinching cannot skip insights', async t => {
  const h = harness(); t.after(() => h.unmount()); await h.flush(); await h.activate(); await h.position('bottom');
  await h.key('ArrowDown', true); assert.equal(h.date(), today.quote_date);
  await h.pinch(); assert.equal(h.date(), today.quote_date);
  await h.key('ArrowDown'); assert.equal(h.date(), earlier.quote_date);
});

test('oldest saved insight does not loop or request history again', async t => {
  const h = harness(async () => page([earlier])); t.after(() => h.unmount()); await h.flush(); await h.activate();
  assert.equal(h.date(), earlier.quote_date);
  await h.pointer({ dy: -100 }); assert.equal(h.date(), earlier.quote_date);
  assert.equal(h.calls.length, 1);
  assert.ok(h.disabled('↓') === true || h.disabled('↓') === undefined);
});
