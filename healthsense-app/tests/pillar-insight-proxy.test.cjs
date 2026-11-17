const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');
const ts = require('typescript');

const source = fs.readFileSync(path.join(__dirname, '../src/app/api/pillar-tracker/insights/route.ts'), 'utf8');
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2017 } }).outputText;

function route(fetch, env = { API_BASE_URL: 'https://api.example.test/' }) {
  const exports = {};
  vm.runInNewContext(compiled, {
    exports, URL, URLSearchParams, process: { env }, fetch,
    require(name) {
      assert.equal(name, 'next/server');
      return { NextResponse: { json: (body, options) => Response.json(body, options) } };
    },
  });
  return exports.GET;
}

function request(query = 'userId=42&pillarKey=nutrition', cookie = 'hs_session=member-session; hs_user_id=42') {
  return new Request(`https://app.example.test/api/pillar-tracker/insights?${query}`, { headers: { cookie } });
}

test('forwards member session, pillar and cursor without admin credentials', async () => {
  const calls = [];
  const payload = { user_id: 42, pillar_key: 'nutrition', insights: [{ id: 7, quote_date: '2026-11-16', quote: 'Saved insight' }], has_more: false, next_before: null };
  const get = route(async (url, options) => { calls.push({ url, options }); return Response.json(payload); });
  const response = await get(request('userId=42&pillarKey=nutrition&before=2026-11-17&limit=5'));
  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), payload);
  assert.equal(calls[0].url, 'https://api.example.test/api/v1/users/42/pillar-tracker/nutrition/insights?limit=5&before=2026-11-17');
  assert.deepEqual(Object.entries(calls[0].options.headers), [['X-Session-Token', 'member-session']]);
  assert.equal(calls[0].options.cache, 'no-store');
});

test('requires a session even when server admin credentials exist', async () => {
  let fetched = false;
  const get = route(async () => { fetched = true; }, { API_BASE_URL: 'https://api.example.test', ADMIN_API_TOKEN: 'server-only', ADMIN_USER_ID: '1' });
  assert.equal((await get(request(undefined, 'hs_user_id=42'))).status, 401);
  assert.equal(fetched, false);
});

test('uses user cookie when query user is omitted', async () => {
  let target;
  const get = route(async url => { target = url; return Response.json({ insights: [] }); });
  assert.equal((await get(request('pillarKey=recovery'))).status, 200);
  assert.match(target, /\/users\/42\/pillar-tracker\/recovery\/insights\?limit=10$/);
});

test('rejects malformed users, pillars, dates and page limits before upstream access', async () => {
  let fetched = false;
  const get = route(async () => { fetched = true; });
  for (const query of [
    'userId=-1&pillarKey=nutrition', 'userId=abc&pillarKey=nutrition',
    'userId=42&pillarKey=unknown', 'userId=42&pillarKey=nutrition&before=yesterday',
    'userId=42&pillarKey=nutrition&limit=0', 'userId=42&pillarKey=nutrition&limit=31',
    'userId=42&pillarKey=nutrition&limit=1.5',
  ]) assert.equal((await get(request(query))).status, 400, query);
  assert.equal(fetched, false);
});

test('preserves upstream access denial and hides internal response details', async () => {
  const get = route(async () => new Response('private internal detail', { status: 403 }));
  const response = await get(request());
  assert.equal(response.status, 403);
  assert.ok(!(await response.text()).includes('private internal detail'));
});

test('handles missing config and network failures without leaking server details', async () => {
  assert.equal((await route(async () => { throw new Error('should not fetch'); }, {})(request())).status, 503);
  const response = await route(async () => { throw new Error('internal connection string'); })(request());
  assert.equal(response.status, 502);
  assert.ok(!(await response.text()).includes('internal connection string'));
});
