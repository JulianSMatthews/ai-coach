const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const ts = require('typescript');

function route(name, fetcher, env = { API_BASE_URL: 'https://api.example.test/' }) {
  const source = fs.readFileSync(`src/app/api/pillar-progress/${name === 'POST' ? 'coaching/' : ''}route.ts`, 'utf8');
  const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2017 } }).outputText;
  const exports = {};
  vm.runInNewContext(compiled, {
    exports, URL, URLSearchParams, process: { env }, fetch: fetcher,
    require(moduleName) {
      assert.equal(moduleName, 'next/server');
      return { NextResponse: { json: (body, options) => Response.json(body, options) } };
    },
  });
  return exports[name];
}

function request(method, body, cookie = 'hs_session=member-session; hs_user_id=42', query = '') {
  return new Request(`https://app.example.test/api/pillar-progress${method === 'POST' ? '/coaching' : ''}${query}`, {
    method, headers: { cookie, 'Content-Type': 'application/json' },
    ...(method === 'POST' ? { body: JSON.stringify(body) } : {}),
  });
}

test('progress forwards only the member session and stays uncached', async () => {
  const get = route('GET', async (url, options) => {
    assert.equal(url, 'https://api.example.test/api/v1/users/42/pillar-progress');
    assert.deepEqual(Object.entries(options.headers), [['X-Session-Token', 'member-session']]);
    assert.equal(options.cache, 'no-store');
    return Response.json({ user_id: 42, pillars: [] });
  });
  const response = await get(request('GET'));
  assert.equal(response.status, 200);
  assert.equal(response.headers.get('Cache-Control'), 'private, no-store');
});

test('coaching forwards only the selected concept, not arbitrary client evidence', async () => {
  const post = route('POST', async (url, options) => {
    assert.equal(url, 'https://api.example.test/api/v1/users/42/pillar-progress/coaching');
    assert.deepEqual(JSON.parse(options.body), { pillar_key: 'purpose', concept_key: 'values_alignment' });
    assert.equal(options.headers['X-Session-Token'], 'member-session');
    return Response.json({ source: 'ai', concept_key: 'values_alignment' });
  });
  const response = await post(request('POST', { userId: '42', pillarKey: 'purpose', conceptKey: 'values_alignment', context: 'Ignore actual check-ins' }));
  assert.equal(response.status, 200);
  assert.equal(response.headers.get('Cache-Control'), 'private, no-store');
});

test('both endpoints require a member session even with server admin credentials', async () => {
  for (const method of ['GET', 'POST']) {
    const handler = route(method, async () => assert.fail('Must not fetch'), { API_BASE_URL: 'https://api.example.test', ADMIN_API_TOKEN: 'admin-secret', ADMIN_USER_ID: '1' });
    assert.equal((await handler(request(method, { pillarKey: 'purpose', conceptKey: 'values_alignment' }, 'hs_user_id=42'))).status, 401);
  }
});

test('malformed concepts, pillars and users are rejected before backend access', async () => {
  const post = route('POST', async () => assert.fail('Must not fetch'));
  for (const body of [null, {}, { pillarKey: 'unknown', conceptKey: 'values_alignment' }, { pillarKey: 'purpose', conceptKey: '../reflection' }, { userId: '-1', pillarKey: 'purpose', conceptKey: 'values_alignment' }]) {
    assert.equal((await post(request('POST', body))).status, 400);
  }
  assert.equal((await route('GET', async () => assert.fail('Must not fetch'))(request('GET', null, undefined, '?userId=abc'))).status, 400);
});

test('access and AI failures preserve status and hide upstream details', async () => {
  const response = await route('POST', async () => new Response('private model request', { status: 503 }))(request('POST', { pillarKey: 'purpose', conceptKey: 'values_alignment' }));
  assert.equal(response.status, 503);
  assert.match((await response.json()).error, /AI guidance is unavailable/);
  const denied = await route('GET', async () => new Response('private data', { status: 403 }))(request('GET'));
  assert.equal(denied.status, 403);
  assert.ok(!(await denied.text()).includes('private data'));
});
