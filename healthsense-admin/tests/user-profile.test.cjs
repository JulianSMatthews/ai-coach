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
async function render(section, failActivity = false, activity = "all", educationOverride = null) {
  const api = {
    getAdminUserDetails: async () => ({ user: { display_name: 'Test User', password_hash: 'secret-hash', consent_given: true }, onboarding: {} }),
    getAdminUserAppState: async () => ({ today: '2026-09-28', pillar_configuration: { setup_last_saved_at: '2026-09-20T10:00:00Z', pillars: [{key: 'nutrition', label: 'Nutrition', selected: true, source: 'saved', last_saved_at: '2026-09-20T10:00:00Z'}], objectives: [{pillar_key: 'nutrition', label: 'Nutrition', objective: 'Eat well', concepts: [{concept_key: 'alcohol', label: 'Alcohol', selected_value: 0, unit_label: 'units', target_source: 'default'}]}]}, engagement_summary: { current_streak_days: 7, best_streak_days: 12 }, journey: { daily_recording: { completed_today_count: 0, completed_yesterday_count: 1, total_pillars: 2, pillars: [{ pillar_key: 'nutrition', label: 'Nutrition', day_before_yesterday_complete: false, yesterday_complete: true, today_complete: false }] } }, education: educationOverride || { available: true, concept_label: 'Hydration', current_streak_days: 2, progress: { lesson_date: '2026-09-28', watch_pct: 50 } } }),
    getAdminUserActivity: async (_userId, category) => {
      assert.equal(category, section === "activity" ? activity : "all");
      if (failActivity) throw new Error('offline');
      return { events: [{ id: 1, recorded_at: '2026-09-28T09:00:00Z', kind: 'pillar_tracker_update', label: 'Recorded check-in', pillar_key: 'nutrition', for_date: '2026-09-27' }] };
    },
    getAdminUserPerformance: async () => ({ today: '2026-09-28', week: { start: '2026-09-21', end: '2026-09-27' }, pillars: [{ pillar_key: 'nutrition', label: 'Nutrition', tracker_score: 0, completed_days_count: 1 }] }),
  };
  const mocks = { '@/lib/api': api, 'next/navigation': { notFound: () => { throw new Error('404'); }, redirect: () => {} }, 'next/cache': { revalidatePath: () => {} }, 'next/link': { default: props => React.createElement('a', props) }, '@/components/AdminNav': { default: ({ title }) => React.createElement('h1', null, title) } };
  mocks['./AccountTools'] = { default: load('src/app/admin/users/[userId]/AccountTools.tsx', mocks) };
  const Page = load('src/app/admin/users/[userId]/page.tsx', mocks);
  return renderToStaticMarkup(await Page({ params: Promise.resolve({ userId: '1' }), searchParams: Promise.resolve({ section, activity }) }));
}
test('overview shows recording day separately and surfaces lesson progress', async () => {
  const html = await render('overview');
  assert.match(html, /Yesterday’s check-ins/);
  assert.match(html, /Check-in streak<\/h2><p[^>]*>7 days<\/p>/);
  assert.ok(html.indexOf("Check-in streak") < html.indexOf("Check-ins by pillar"));
  assert.match(html, /Day before yesterday<\/th><th[^>]*>Yesterday<\/th><th>Today<\/th>/);
  assert.match(html, /Nutrition<\/td><td[^>]*>Not recorded<\/td><td[^>]*>Recorded<\/td><td[^>]*>Not recorded<\/td>/);
  assert.match(html, /27 Sept 2026/);
  assert.match(html, /28 Sept 2026/);
  assert.match(html, /Pillars &amp; objectives/);
  assert.match(html, /Nutrition — objectives &amp; targets/);
  assert.match(html, /0 units/);
  assert.match(html, /App default/);
  assert.doesNotMatch(html, /Plan &amp; targets|Daily plan:|Coach insight:/);
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

test('activity filters select learning and check-ins while retaining the user profile', async () => {
  for (const [filter, label] of [['learn', 'Learning'], ['checkin', 'Check-ins']]) {
    const html = await render('activity', false, filter);
    assert.match(html, /aria-label="Activity filters"/);
    assert.ok(html.includes(`/admin/users/1?section=activity&amp;activity=${filter}" aria-current="page"`));
    assert.ok(html.includes(label));
  }
});

test('learning shows programme completion and saved quiz counts', async () => {
  const quiz = {question_count: 5, answered_count: 4, correct_count: 3, incorrect_count: 2, ungraded_count: 0};
  const html = await render('overview', false, 'all', {
    available: true, lesson_title: 'Making time to restore', programme_name: 'Recovery',
    lesson_number: 2, programme_lesson_count: 7, programme_completed_count: 2,
    progress: {lesson_date: '2026-09-29', quiz_completed_at: '2026-09-29T09:00:00Z', quiz_score_pct: 60, quiz, completed_at: '2026-09-29T09:00:00Z'},
    programme_lessons: [{programme_day_id: 12, number: 2, title: 'Making time to restore', completed: true, quiz_completed_at: '2026-09-29T09:00:00Z', quiz}],
  });
  assert.match(html, /Programme: Recovery/);
  assert.match(html, /Lesson 2 of 7/);
  assert.match(html, /2 of 7 programme lessons completed/);
  assert.match(html, /3 of 5 questions correct/);
  assert.match(html, /4 answered · 1 unanswered/);
  assert.match(html, /Lessons in this programme/);
});
