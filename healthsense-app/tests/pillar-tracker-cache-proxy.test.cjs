// Cached tracker reads and saves must stay independent of AI generation, including old clients.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');

function route(relativePath) {
  const source = fs.readFileSync(path.join(__dirname, '../src/app/api/pillar-tracker', relativePath), 'utf8');
  const compiled = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2017 },
  }).outputText;
  const exports = {}, calls = [];
  vm.runInNewContext(compiled, {
    exports, URL, URLSearchParams,
    process: { env: { API_BASE_URL: 'https://api.example.test/' } },
    fetch: async (url, options) => { calls.push({ url, options }); return Response.json({ saved: true }); },
    require(name) {
      assert.equal(name, 'next/server');
      return { NextResponse: { json: (body, options) => Response.json(body, options) } };
    },
  });
  return { ...exports, calls };
}

function request(url, body) {
  return new Request(`https://app.example.test${url}`, {
    method: body ? 'POST' : 'GET',
    headers: { cookie: 'hs_session=member-session; hs_user_id=42', ...(body ? { 'Content-Type': 'application/json' } : {}) },
    ...(body ? { body: JSON.stringify(body) } : {}),
  });
}

test('home summary proxy always requests cached insights even if an older client asks for generation', async () => {
  for (const flag of ['', '&skipQuoteGeneration=false', '&skip_quote_generation=false']) {
    const h = route('summary/route.ts');
    const response = await h.GET(request(`/api/pillar-tracker/summary?userId=42&anchorDate=2026-11-20${flag}`));
    assert.equal(response.status, 200);
    assert.equal(h.calls.length, 1);
    const call = h.calls[0], url = new URL(call.url);
    assert.equal(url.pathname, '/api/v1/users/42/pillar-tracker');
    assert.equal(url.searchParams.get('anchor_date'), '2026-11-20');
    assert.equal(url.searchParams.get('skip_quote_generation'), 'true');
    assert.equal(call.options.method, 'GET');
    assert.equal(call.options.headers['X-Session-Token'], 'member-session');
    assert.equal(call.options.cache, 'no-store');
  }
});

test('opening tracker detail never asks the API to generate an insight', async () => {
  for (const flag of ['', '&skipQuoteGeneration=false', '&skip_quote_generation=false']) {
    const h = route('[pillar]/route.ts');
    const response = await h.GET(request(`/api/pillar-tracker/recovery?userId=42&anchorDate=2026-11-20${flag}`),
      { params: Promise.resolve({ pillar: 'recovery' }) });
    assert.equal(response.status, 200);
    assert.equal(h.calls.length, 1);
    const call = h.calls[0], url = new URL(call.url);
    assert.equal(url.pathname, '/api/v1/users/42/pillar-tracker/recovery');
    assert.equal(url.searchParams.get('anchor_date'), '2026-11-20');
    assert.equal(url.searchParams.get('skip_quote_generation'), 'true');
    assert.equal(call.options.method, 'GET');
    assert.equal(call.options.headers['X-Session-Token'], 'member-session');
  }
});

test('save proxy forwards answers while forcing generation off for current and older clients', async () => {
  const entries = [{ concept_key: 'meaning_fulfilment', value: 3 }];
  for (const flag of [{}, { skipQuoteGeneration: false }, { skip_quote_generation: false }]) {
    const h = route('[pillar]/route.ts');
    const response = await h.POST(request('/api/pillar-tracker/purpose', {
      userId: '42', score_date: '2026-11-20', entries, ...flag,
    }), { params: Promise.resolve({ pillar: 'purpose' }) });
    assert.equal(response.status, 200);
    assert.equal(h.calls.length, 1);
    const call = h.calls[0];
    assert.equal(call.url, 'https://api.example.test/api/v1/users/42/pillar-tracker/purpose');
    assert.equal(call.options.method, 'POST');
    assert.equal(call.options.headers['X-Session-Token'], 'member-session');
    assert.deepEqual(JSON.parse(call.options.body), {
      score_date: '2026-11-20', entries, skip_quote_generation: true,
    });
  }
});
