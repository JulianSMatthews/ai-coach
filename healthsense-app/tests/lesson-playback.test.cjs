const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const ts = require('typescript');
function compile(path, env) {
  vm.runInNewContext(ts.transpileModule(fs.readFileSync(path, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2020 } }).outputText, env);
  return env.exports;
}
const utils = compile('src/lib/lessonPlayback.ts', { exports: {} });
const played = (ranges) => ({ length: ranges.length, start: i => ranges[i][0], end: i => ranges[i][1] });
test('played intervals merge replays and mode switches without counting seeks', () => {
  const ranges = utils.mergePlayedRanges([[0, 20]], played([[10, 30], [95, 100]]));
  assert.equal(utils.playbackProgress(ranges, 100).watch_pct, 35);
  assert.equal(utils.playbackProgress(ranges, 100).watched_seconds, 35);
  assert.equal(utils.playbackProgress(ranges, NaN), null);
  assert.equal(utils.playbackProgress([], 100), null);
});
for (const mode of ['watch', 'listen']) {
  test(`${mode} player sends lesson identity, retries failure and flushes on pause`, async () => {
    const requests = [];
    let fail = true;
    const env = { exports: {}, Date, window: { addEventListener() {}, removeEventListener() {} }, document: { addEventListener() {}, removeEventListener() {} },
      fetch: async (url, options) => { requests.push({ url, ...JSON.parse(options.body) }); if (fail) throw Error('offline'); return { ok: true, json: async () => ({ video_progress_applied: true }) }; },
      require: name => name === 'react' ? { useRef: current => ({ current }), useState: value => [value, () => {}], useEffect: () => {}, useCallback: fn => fn } : name === '@/lib/lessonPlayback' ? utils : require(name),
    };
    const Component = compile('src/components/EducationLessonMedia.tsx', env).default;
    const tree = Component({ userId: '7', lessonVariantId: 17, src: 'lesson.mp4', mode });
    const surface = tree.props.children[0];
    const media = mode === 'watch' ? surface : surface.props.children[1];
    const element = { duration: 100, played: played([[0, 40]]) };
    media.props.ref(element);
    media.props.onTimeUpdate();
    await new Promise(resolve => setImmediate(resolve));
    fail = false;
    media.props.onPause();
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(requests.length, 2);
    assert.equal(requests[1].lesson_variant_id, 17);
    assert.equal(requests[1].watch_pct, 40);
    element.played = played([[0, 100]]);
    media.props.onEnded();
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(requests.at(-1).watch_pct, 100);
  });
}
