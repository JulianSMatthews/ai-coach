// Run with: node --test tests/pillar-insight-navigation.test.cjs
// Exercise the real component with browser geometry and React hook state simulated.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');

const source = fs.readFileSync(path.join(__dirname, '../src/components/PillarInsight.tsx'), 'utf8');
const compiled = ts.transpileModule(source, { compilerOptions: {
  module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2017,
} }).outputText;
const today = { id: 1, quote_date: '2026-11-17', quote: 'TODAY. ' + 'A longer reflection to read carefully. '.repeat(30) };

function harness() {
  let slots = [], cursor = 0, pendingEffects = [], tree, dirty = true, requestId = 0;
  let props = { pillarLabel: 'Resilience', currentQuote: today.quote };
  const frames = new Map(), calls = [], events = [], nodes = new Map();
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
  class ResizeObserver { observe() {} disconnect() {} }
  const exports = {};
  vm.runInNewContext(compiled, {
    exports, window, document: { addEventListener() {}, removeEventListener() {} },
    ResizeObserver, console, setTimeout, clearTimeout, queueMicrotask,
    requestAnimationFrame: window.requestAnimationFrame, cancelAnimationFrame: window.cancelAnimationFrame,
    fetch: async (url, options) => {
      calls.push({ url, options });
      throw new Error('Current insight scrolling must not fetch history');
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
    cursor = 0; dirty = false;
    tree = expand(exports.default(props));
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

test('arrows scroll the current insight by 80px and stop at the reading boundaries', async t => {
  const h = harness(); t.after(() => h.unmount()); await h.flush();
  assert.equal(h.disabled('↑'), true);
  assert.equal(h.disabled('↓'), false);
  await h.click('↓'); assert.equal(h.region().scrollTop, 80);
  assert.equal(h.disabled('↑'), false);
  await h.click('↓'); assert.equal(h.region().scrollTop, 160);
  await h.click('↑'); assert.equal(h.region().scrollTop, 80);
  await h.position('bottom');
  assert.equal(h.disabled('↓'), true);
  await h.click('↓');
  assert.equal(h.region().scrollTop, h.region().scrollHeight - h.region().clientHeight);
  await h.click('↑'); assert.equal(h.disabled('↓'), false);
  assert.ok(h.text().includes(today.quote));
  assert.equal(h.calls.length, 0);
});

test('vertical swipes read the current insight and horizontal swipes remain available to the carousel', async t => {
  const h = harness(); t.after(() => h.unmount()); await h.flush();
  await h.pointer({ dy: -100 }); assert.equal(h.region().scrollTop, 100);
  await h.pointer({ dy: 60 }); assert.equal(h.region().scrollTop, 40);
  const horizontal = await h.pointer({ dx: 100, dy: -8 });
  assert.equal(horizontal.prevented, undefined);
  assert.equal(h.region().scrollTop, 40);
  await h.position('bottom');
  await h.pointer({ dy: -160, moves: 4 });
  assert.equal(h.region().scrollTop, h.region().scrollHeight - h.region().clientHeight);
  assert.ok(h.text().includes(today.quote));
  assert.equal(h.calls.length, 0);
});

test('keyboard scrolling keeps the current insight, including at the reading boundaries', async t => {
  const h = harness(); t.after(() => h.unmount()); await h.flush();
  await h.key('ArrowDown'); assert.equal(h.region().scrollTop, 80);
  await h.key('ArrowDown', true); assert.equal(h.region().scrollTop, 160);
  await h.key('PageUp'); assert.ok(h.region().scrollTop < 80);
  await h.position('bottom'); await h.key('ArrowDown'); await h.key('PageDown');
  assert.equal(h.disabled('↓'), true);
  await h.position(0); await h.key('ArrowUp'); await h.key('PageUp');
  assert.equal(h.region().scrollTop, 0);
  assert.ok(h.text().includes(today.quote));
  assert.equal(h.calls.length, 0);
});

test('short insights have no scrolling arrows and updated insights start at the top', async t => {
  const h = harness(); t.after(() => h.unmount()); await h.flush();
  await h.position(120);
  const nextQuote = 'A different long insight. '.repeat(40);
  await h.update({ currentQuote: nextQuote });
  assert.equal(h.region().scrollTop, 0);
  assert.equal(h.disabled('↑'), true);
  assert.ok(h.text().includes(nextQuote));
  assert.ok(!h.text().includes('TODAY.'));
  await h.update({ currentQuote: 'A short current insight.' });
  assert.equal(h.disabled('↑'), undefined);
  assert.equal(h.disabled('↓'), undefined);
  await h.pointer({ dy: -100 }); assert.equal(h.region().scrollTop, 0);
  assert.equal(h.calls.length, 0);
});
