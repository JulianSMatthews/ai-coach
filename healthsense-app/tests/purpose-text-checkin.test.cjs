const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const ts = require('typescript');

const context = { exports: {} };
const code = ts.transpileModule(fs.readFileSync('src/lib/pillarTrackerAnswers.ts', 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS },
}).outputText;
vm.runInNewContext(code, context);
const { trackerDraftFromConcepts, isTrackerAnswerComplete, trackerEntriesFromDraft } = context.exports;

const rating = (key = 'meaning_fulfilment') => ({
  concept_key: key, input_type: 'choice', options: [0, 1, 2, 3].map(value => ({ value })),
});
const contribution = () => ({
  concept_key: 'contribution_connection', input_type: 'text',
  helper: "How did you positively contribute to someone else's day?", options: [],
});

test('saved Purpose ratings and written reflection hydrate without converting text to a number', () => {
  const draft = trackerDraftFromConcepts([
    { ...rating(), value: 0 },
    { ...rating('values_alignment'), value: 3 },
    { ...contribution(), value: null, value_text: 'I listened to a friend.' },
  ]);
  assert.equal(draft.meaning_fulfilment, 0);
  assert.equal(draft.values_alignment, 3);
  assert.equal(draft.contribution_connection, 'I listened to a friend.');
});

test('blank or absent ratings are not converted into recorded zero answers', () => {
  for (const value of [null, undefined, '', '  ']) {
    const draft = trackerDraftFromConcepts([{ ...rating(), value }]);
    assert.equal(Object.hasOwn(draft, 'meaning_fulfilment'), false);
    assert.equal(isTrackerAnswerComplete(rating(), value), false);
  }
  assert.equal(isTrackerAnswerComplete(rating(), 0), true);
  assert.equal(isTrackerAnswerComplete(rating(), '0'), false);
  assert.equal(isTrackerAnswerComplete(rating(), 5), false);
});

test('Contribution requires a nonblank written response within the limit', () => {
  for (const value of [undefined, 0, '', ' \n\t', 'x'.repeat(2001)]) {
    assert.equal(isTrackerAnswerComplete(contribution(), value), false);
  }
  assert.equal(isTrackerAnswerComplete(contribution(), 'Nothing today.'), true);
  assert.equal(isTrackerAnswerComplete(contribution(), 'x'.repeat(2000)), true);
});

test('Purpose serializes two numeric answers and the exact written response separately', () => {
  const concepts = [rating(), rating('values_alignment'), contribution()];
  const entries = trackerEntriesFromDraft(concepts, {
    meaning_fulfilment: 2, values_alignment: 3,
    contribution_connection: '  I helped my neighbour.\nWe talked.  ',
  });
  assert.deepEqual(JSON.parse(JSON.stringify(entries)), [
    { concept_key: 'meaning_fulfilment', value: 2 },
    { concept_key: 'values_alignment', value: 3 },
    { concept_key: 'contribution_connection', text: 'I helped my neighbour.\nWe talked.' },
  ]);
});

test('negative neutral choices in other pillars remain valid and numeric', () => {
  const adaptability = { concept_key: 'adaptability', options: [-1, 0, 1 / 3, 2 / 3, 1].map(value => ({ value })) };
  const draft = trackerDraftFromConcepts([{ ...adaptability, value: -1 }]);
  assert.equal(isTrackerAnswerComplete(adaptability, draft.adaptability), true);
  assert.equal(trackerEntriesFromDraft([adaptability], draft)[0].value, -1);
});

test('written numeric characters remain a written answer', () => {
  const draft = trackerDraftFromConcepts([{ ...contribution(), value_text: '0' }]);
  assert.equal(draft.contribution_connection, '0');
  assert.equal(isTrackerAnswerComplete(contribution(), draft.contribution_connection), true);
  const entry = trackerEntriesFromDraft([contribution()], draft)[0];
  assert.equal(entry.text, '0');
  assert.equal(Object.hasOwn(entry, 'value'), false);
});
