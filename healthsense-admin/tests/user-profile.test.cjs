const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const ts = require('typescript');
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
function load(file, mocks) {
  const exports = {};
  vm.runInNewContext(ts.transpileModule(fs.readFileSync(file, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2020 } }).outputText, { exports, process, URL, require: name => name in mocks ? mocks[name] : require(name) });
  return exports.default;
}
async function render(section, failActivity = false) {
  const api = {
    getAdminUserDetails: async () => ({ user: { display_name: 'Test User', password_hash: 'secret-hash', consent_given: true }, onboarding: {} }),
    getAdminUserAppState: async () => ({ today: '2026-09-28', engagement_summary: { current_streak_days: 7, best_streak_days: 12 }, journey: { daily_recording: { completed_today_count: 0, completed_yesterday_count: 1, total_pillars: 2, pillars: [{ pillar_key: 'nutrition', label: 'Nutrition', day_before_yesterday_complete: false, yesterday_complete: true, today_complete: false }] } }, education: { available: true, concept_label: 'Hydration', current_streak_days: 2, progress: { lesson_date: '2026-09-28', watch_pct: 50 } } }),
    getAdminUserActivity: async () => {
      if (failActivity) throw new Error('offline');
      return { events: [{ id: 1, recorded_at: '2026-09-28T09:00:00Z', kind: 'pillar_tracker_update', label: 'Recorded check-in', pillar_key: 'nutrition', for_date: '2026-09-27' }] };
    },
    getAdminUserPerformance: async () => ({ today: '2026-09-28', week: { start: '2026-09-21', end: '2026-09-27' }, pillars: [{ pillar_key: 'nutrition', label: 'Nutrition', tracker_score: 0, completed_days_count: 1 }] }),
  };
  const mocks = { '@/lib/api': api, 'next/navigation': { notFound: () => { throw new Error('404'); }, redirect: () => {} }, 'next/cache': { revalidatePath: () => {} }, 'next/link': { default: props => React.createElement('a', props) }, '@/components/AdminNav': { default: ({ title }) => React.createElement('h1', null, title) } };
  mocks['./AccountTools'] = { default: load('src/app/admin/users/[userId]/AccountTools.tsx', mocks) };
  const Page = load('src/app/admin/users/[userId]/page.tsx', mocks);
  return renderToStaticMarkup(await Page({ params: Promise.resolve({ userId: '1' }), searchParams: Promise.resolve({ section }) }));
}
test('overview shows recording day separately and surfaces lesson progress', async () => {
  const html = await render('overview');
  assert.match(html, /Yesterday’s check-ins/);
  assert.match(html, /Check-in streak: 7 days/);
  assert.match(html, /Day before yesterday<\/th><th[^>]*>Yesterday<\/th><th>Today<\/th>/);
  assert.match(html, /Nutrition<\/td><td[^>]*>Not recorded<\/td><td[^>]*>Recorded<\/td><td[^>]*>Not recorded<\/td>/);
  assert.match(html, /27 Sept 2026/);
  assert.match(html, /28 Sept 2026/);
  assert.match(html, /Video progress: 50%/);
  assert.match(html, /Quiz: Not completed/);
  assert.doesNotMatch(html, /First-day coaching|Coaching activation|secret-hash|assessment/i);
});
test('account removes retired controls and retains preview and advanced settings', async () => {
  const html = await render('account');
  assert.match(html, /Open app preview/);
  assert.match(html, /Advanced settings/);
  assert.doesNotMatch(html, /Send SMS|24h template|fast on|Message history|secret-hash/);
});
test('history keeps real zero scores and cannot navigate into this week', async () => {
  const html = await render('history');
  assert.match(html, /Previous week\(s\)/);
  assert.match(html, /<td>0<\/td>/);
  assert.doesNotMatch(html, /Next week/);
});
test('activity failure is reported rather than claiming no user activity', async () => {
  const html = await render('activity', true);
  assert.match(html, /Activity could not be loaded/);
  assert.doesNotMatch(html, /No recorded app activity/);
});
