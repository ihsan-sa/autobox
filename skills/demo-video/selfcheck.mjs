#!/usr/bin/env node
/* selfcheck.mjs (the demo-video skill) — the kit's own checks.

    node selfcheck.mjs          # no browser: the timeline, the joins, the length limit, the denied words, the recorder
    node selfcheck.mjs --film   # also records a tiny terminal in the sandbox, films it and checks the MP4

Each case builds what it needs in its own temp dir and prints one line; the exit code is the number that failed. */
import { execFileSync } from 'node:child_process';
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { timeline, fadeOffsets, firstDenied, captionFilter, encodeFrames, stitch, checkLength, lengthOf, contactSheet,
  director, encodeClip, camerawork, FFMPEG, RESULT_MS, MAX_FILM_S } from './film.mjs';
import { cameraAt, viewFor, transformOf, rest } from './camera.mjs';

process.env.DEMO_VIDEO_CHECKED = '1';  // a check, not a render: director() skips the preflight
const HERE = dirname(fileURLToPath(import.meta.url));
let failed = 0;
const tmp = () => mkdtempSync(join(tmpdir(), 'dv-check-'));
async function check(name, fn) {
  try { await fn(); console.log(`ok   ${name}`); } catch (e) { failed++; console.log(`FAIL ${name}: ${e.message}`); }
}
const eq = (a, b, what) => { if (JSON.stringify(a) !== JSON.stringify(b)) throw new Error(`${what}: ${JSON.stringify(a)} != ${JSON.stringify(b)}`); };
const near = (a, b, tol, what) => { if (Math.abs(a - b) > tol) throw new Error(`${what}: ${a} is not ${b} ± ${tol}`); };
const throws = async (fn, re, what) => {
  try { await fn(); } catch (e) { if (re.test(e.message)) return; throw new Error(`${what}: threw "${e.message}"`); }
  throw new Error(`${what}: did not throw`);
};
/** A solid-colour clip of `secs` at 1920x1080, made by ffmpeg alone. */
const clip = (dir, name, secs, color = 'navy') => {
  const f = join(dir, `${name}.mp4`);
  execFileSync(FFMPEG, ['-hide_banner', '-loglevel', 'error', '-y', '-f', 'lavfi', '-i', `color=c=${color}:s=1920x1080:r=30:d=${secs}`,
    '-c:v', 'libx264', '-pix_fmt', 'yuv420p', f]);
  return f;
};

await check('timeline: a frame lasts until the next, and the last until the end', () => {
  const t = timeline([{ file: 'a', t: 10 }, { file: 'b', t: 10.5 }, { file: 'c', t: 11 }], [], 12);
  eq(t.map((f) => f.dur), [0.5, 0.5, 1], 'durations');
});

await check('timeline: a cut stretch is taken out, the frames around it keep their length', () => {
  const shots = [{ file: 'a', t: 0 }, { file: 'b', t: 1 }, { file: 'c', t: 4 }];
  eq(timeline(shots, [[1.2, 3.8]], 5).map((f) => +f.dur.toFixed(3)), [1, 0.4, 1], 'with the cut');
  eq(timeline(shots, [], 5).map((f) => f.dur), [1, 3, 1], 'without it');
});

await check('camera: at rest before a move, moving on every frame of it, and at rest again after the way back', () => {
  const size = { w: 1920, h: 1080 }, box = { x: 100, y: 100, w: 600, h: 300 };
  const cues = [{ t: 500, ms: 700, box, fill: 0.92, max: 2.2, dip: 0 }, { t: 2000, ms: 400, box: null, fill: 0.92, max: 2.2, dip: 0 }];
  const at = (frame) => cameraAt((frame * 1000) / 30, cues, size);
  eq(at(0), rest(size), 'a rest frame');
  eq(at(0).s, 1, 'rest scale');
  for (let f = 16; f < 36; f++) {   // 533 ms to 1167 ms: inside the first move
    const [a, b, c] = [at(f - 1), at(f), at(f + 1)];
    if (JSON.stringify(a) === JSON.stringify(b) || JSON.stringify(b) === JSON.stringify(c)) throw new Error(`frame ${f} repeats a neighbour`);
  }
  const v = viewFor(box, size, cues[0]);
  near(v.s, 2.2, 1e-9, 'the zoom is capped at max');
  near(v.x, 960 / 2.2, 1e-9, 'the centre is kept inside the page');
  for (const k of ['x', 'y', 's']) near(at(40)[k], v[k], 1e-9, 'arrived: ' + k);
  eq(at(80), rest(size), 'back at rest');
  const tr = transformOf(at(40), size);
  near(tr.tx, 0, 1e-9, 'the frame\'s left edge stays on the page\'s');
});

await check('camera: a move that starts mid-flight starts where the camera had got to, and a dip pulls back mid-move', () => {
  const size = { w: 1000, h: 500 }, a = { x: 0, y: 0, w: 250, h: 125 }, b = { x: 750, y: 375, w: 250, h: 125 };
  const cues = [{ t: 0, ms: 1000, box: a }, { t: 500, ms: 1000, box: b }];
  const mid = cameraAt(500, cues.slice(0, 1), size);
  near(cameraAt(500, cues, size).s, mid.s, 1e-9, 'the second move opens at the first one\'s scale');
  near(cameraAt(500, cues, size).x, mid.x, 1e-9, 'and its centre');
  const swoop = cameraAt(500, [{ t: 0, ms: 1000, box: null, dip: 0.2 }], size, { x: 200, y: 100, s: 2 });
  if (!(swoop.s < Math.sqrt(2) * 0.81)) throw new Error('no pull-back at the middle: ' + swoop.s);
});

await check('director: a camera move is a cue in the clip\'s time, the page is never moved, and the next beat opens where it left off', async () => {
  let onFrame = null, evals = 0;
  const cdp = { on: (ev, fn) => { if (ev === 'Page.screencastFrame') onFrame = fn; }, send: async () => {} };
  const page = { addInitScript: async () => {}, context: () => ({ newCDPSession: async () => cdp }), viewportSize: () => ({ width: 1920, height: 1080 }),
    evaluate: async () => { evals++; return ''; }, url: () => 'about:blank' };
  const dir = tmp();
  try {
    const d = await director(page, { frames: dir });
    const shot = () => onFrame({ data: '', metadata: { timestamp: Date.now() / 1000 }, sessionId: 1 });
    await d.beat('one', '');
    shot();
    await d.hold(200);
    const before = evals;
    await d.camera({ x: 0, y: 0, w: 960, h: 540 }, { ms: 100 });
    if (evals !== before) throw new Error('camera() ran code in the page');
    shot();
    await d.beat('two', '');
    shot();
    await d.hold(50);
    shot();
    await d.stop();
    const [one, two] = d.beats();
    eq(one.camera.cues.length, 1, 'one cue in the first beat');
    near(one.camera.cues[0].t, 200, 60, 'the cue\'s time from the clip\'s first frame');
    eq(one.camera.cues[0].box, { x: 0, y: 0, w: 960, h: 540 }, 'the box, in rest pixels');
    eq([camerawork(one.camera), camerawork(two.camera)], [true, true], 'both beats need the camera rendered');
    eq(two.camera.cues, [], 'no cue in the second beat');
    near(two.camera.from.s, 1.84, 0.01, 'the second beat opens zoomed in');
    eq(camerawork({ size: { w: 10, h: 10 }, from: rest({ w: 10, h: 10 }), cues: [] }), false, 'a still camera is plain ffmpeg');
  } finally { rmSync(dir, { recursive: true, force: true }); }
});

await check('fadeOffsets: each fade starts one fade before the end of the film so far', () => {
  eq(fadeOffsets([4, 5, 3], 0.5), [3.5, 8], 'offsets');
  eq(fadeOffsets([4], 0.5), [], 'one clip');
});

await check('firstDenied: finds a word in any case, and passes clean text', () => {
  eq(firstDenied('Signed in as Alex on MYHOST', ['myhost', 'nobody']), 'myhost', 'hit');
  eq(firstDenied('Signed in as Alex', ['myhost']), undefined, 'clean');
});

await check('captionFilter: the strip goes below the page by default and above it when asked', () => {
  const cap = { height: 60, at: 'bottom', bg: '#fff', rule: '#ccc', accent: '#a00', ink: '#111', size: 24, x: 40, font: '/f.otf' };
  const bottom = captionFilter('/t.txt', cap), top = captionFilter('/t.txt', { ...cap, at: 'top' });
  if (!/pad=iw:ih\+60:0:0:/.test(bottom)) throw new Error('bottom strip not padded below: ' + bottom);
  if (!/pad=iw:ih\+60:0:60:/.test(top)) throw new Error('top strip not padded above: ' + top);
});

await check('the pace limits are the documented ones', () => { eq([RESULT_MS, MAX_FILM_S], [800, 30], 'RESULT_MS, MAX_FILM_S'); });

await check('encodeFrames: frames play at their own timing, and a zero-length frame is dropped', () => {
  const dir = tmp();
  try {
    const a = join(dir, 'a.jpg'), b = join(dir, 'b.jpg');
    for (const [f, c] of [[a, 'red'], [b, 'blue']]) execFileSync(FFMPEG, ['-loglevel', 'error', '-y', '-f', 'lavfi', '-i', `color=c=${c}:s=640x360`, '-frames:v', '1', f]);
    const secs = encodeFrames([{ file: a, dur: 0.6 }, { file: b, dur: 0 }, { file: b, dur: 0.9 }], { mp4: join(dir, 'x.mp4'), list: join(dir, 'l.txt') });
    near(secs, 1.5, 0.001, 'returned length');
    near(lengthOf(join(dir, 'x.mp4')), 1.5, 0.05, 'file length');
    const fmt = execFileSync(FFMPEG.replace(/ffmpeg$/, 'ffprobe'), ['-v', 'error', '-select_streams', 'v', '-show_entries', 'stream=pix_fmt',
      '-of', 'csv=p=0', join(dir, 'x.mp4')], { encoding: 'utf8' }).trim();
    eq(fmt, 'yuv420p', 'pixel format of JPEG frames');
    if (/duration 0\.0000/.test(readFileSync(join(dir, 'l.txt'), 'utf8'))) throw new Error('a zero-length frame was listed');
  } finally { rmSync(dir, { recursive: true, force: true }); }
});

await check('stitch: hard cuts add up the clips, a crossfade overlaps them', () => {
  const dir = tmp();
  try {
    const c = [clip(dir, 'a', 1.2), clip(dir, 'b', 1, 'teal'), clip(dir, 'c', 0.8, 'olive')];
    stitch(c, { mp4: join(dir, 'cut.mp4') });
    near(lengthOf(join(dir, 'cut.mp4')), 3.0, 0.07, 'hard cuts');
    stitch(c, { mp4: join(dir, 'fade.mp4'), fade: 0.3 });
    near(lengthOf(join(dir, 'fade.mp4')), 2.4, 0.07, 'crossfades');
  } finally { rmSync(dir, { recursive: true, force: true }); }
});

await check('checkLength: passes a film at the limit, fails one over it, and DEMO_LONG lets it through', async () => {
  const dir = tmp(), long = process.env.DEMO_LONG;
  try {
    delete process.env.DEMO_LONG;
    const f = clip(dir, 'f', 2);
    near(checkLength(f, 2.5), 2, 0.05, 'under the limit');
    await throws(() => checkLength(f, 1.5), /over 1\.5 s/, 'over the limit');
    process.env.DEMO_LONG = '1';
    near(checkLength(f, 1.5), 2, 0.05, 'DEMO_LONG');
  } finally {
    if (long == null) delete process.env.DEMO_LONG; else process.env.DEMO_LONG = long;
    rmSync(dir, { recursive: true, force: true });
  }
});

await check('contactSheet: one PNG tiled from the film', () => {
  const dir = tmp();
  try {
    const png = contactSheet(clip(dir, 'f', 2), join(dir, 's.png'), { n: 4, cols: 2, width: 200 });
    if (!existsSync(png) || readFileSync(png).subarray(1, 4).toString() !== 'PNG') throw new Error('no PNG');
  } finally { rmSync(dir, { recursive: true, force: true }); }
});

await check('record.py: records what a command prints, with the marks the driver drops, until the stop file', async () => {
  const dir = tmp();
  try {
    const marks = join(dir, 'marks'), stop = join(dir, 'stop'), cast = join(dir, 'c.cast');
    writeFileSync(marks, '');
    const script = `echo one; sleep 0.4; echo two; sleep 0.4; touch ${stop}; sleep 5; echo never`;
    execFileSync('bash', ['-c', `(sleep 0.2; printf 'mid\\t{"panes":[]}\\n' >> ${marks}) & python3 ${join(HERE, 'record.py')} --out ${cast} --cols 40 --rows 5 --marks ${marks} --stop ${stop} -- bash -c '${script}'; wait`]);
    const [head, ...ev] = readFileSync(cast, 'utf8').trim().split('\n').map((l) => JSON.parse(l));
    eq([head.version, head.width, head.height], [2, 40, 5], 'header');
    const out = ev.filter((e) => e[1] === 'o').map((e) => e[2]).join('');
    if (!/one[\s\S]*two/.test(out)) throw new Error('output missing: ' + JSON.stringify(out));
    if (/never/.test(out)) throw new Error('recorded past the stop file');
    const m = ev.find((e) => e[1] === 'm');
    if (!m || JSON.parse(m[2]).name !== 'mid') throw new Error('mark missing');
    const tOne = ev.find((e) => e[1] === 'o' && /one/.test(e[2]))[0], tTwo = ev.find((e) => e[1] === 'o' && /two/.test(e[2]))[0];
    if (!(m[0] > tOne && m[0] < tTwo)) throw new Error(`mark at ${m[0]} is not between ${tOne} and ${tTwo}`);
  } finally { rmSync(dir, { recursive: true, force: true }); }
});

if (process.argv.includes('--film')) {
  const { recordTerminal, terminalPage } = await import('./term.mjs');
  const { launch } = await import('./deps.mjs');
  await check('--film: a real sandboxed terminal is recorded, refuses a denied word, and films to a 1080p MP4', async () => {
    const dir = tmp(), home = join(dir, 'home'), cast = join(dir, 't.cast');
    execFileSync('mkdir', ['-p', join(home, 'dev', 'demo')]);
    try {
      const script = async (t) => {
        await t.run('clear', { cps: 3000 });
        await t.mark('start');
        await t.run('echo "hello from $(whoami)@$(hostname) in $PWD"', { cps: 80 });
        await t.mark('said');
      };
      await recordTerminal({ out: cast, home, cols: 80, rows: 12, user: 'sam', host: 'workbench', deny: [], script });
      const printed = readFileSync(cast, 'utf8');
      if (!/hello from sam@workbench in \/home\/sam/.test(printed)) throw new Error('the sandbox did not show the made-up user, host and home');
      await throws(() => recordTerminal({ out: join(dir, 'd.cast'), home, cols: 80, rows: 12, deny: ['workbench'], script }),
        /denied word/, 'a denied word in the terminal');
      if (existsSync(join(dir, 'd.cast'))) throw new Error('the refused cast was kept');
      const page = terminalPage(cast, { dir, width: 1920, height: 1080 });
      const browser = await launch(['--allow-file-access-from-files']);
      let beats;
      try {
        const p = await (await browser.newContext({ viewport: { width: 1920, height: 1080 } })).newPage();
        const d = await director(p, { frames: join(dir, 'frames'), deny: ['nosuchword'] });
        await p.goto(pathToFileURL(page).href);
        await p.waitForFunction(() => window.player && window.player.ready);
        await p.evaluate(() => window.player.seek('start'));
        await d.beat('say', '');
        await p.evaluate(() => window.player.play('start', 'said', { speed: 2, idle: 0.2 }));
        await throws(() => d.show(RESULT_MS - 100), /floor/, 'a result held under the floor');
        await d.camera({ x: 0, y: 0, w: 960, h: 540 }, { ms: 300 });
        await d.show();
        await d.stop();
        beats = d.beats();
      } finally { await browser.close(); }
      const mp4 = join(dir, 'say.mp4');
      await encodeClip(beats[0], { mp4, work: dir });
      const [w, h] = execFileSync(FFMPEG.replace(/ffmpeg$/, 'ffprobe'), ['-v', 'error', '-select_streams', 'v', '-show_entries', 'stream=width,height',
        '-of', 'csv=p=0', mp4], { encoding: 'utf8' }).trim().split(',').map(Number);
      eq([w, h], [1920, 1080], 'frame size');
      const secs = lengthOf(mp4);
      if (secs < RESULT_MS / 1000 || secs > 10) throw new Error(`clip is ${secs} s`);
    } finally { rmSync(dir, { recursive: true, force: true }); }
  });
}

console.log(failed ? `${failed} failed` : 'all passed');
process.exit(failed);
