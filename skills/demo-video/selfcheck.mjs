#!/usr/bin/env node
/* selfcheck.mjs (the demo-video skill) — the kit's own checks.

    node selfcheck.mjs          # no browser: the director's frames, the camera, the encode, the joins, the limits, the recorder,
                                #   and motion/: its maths, its stutter measure and its React pieces (rendered to markup)
    node selfcheck.mjs --film   # also films a moving page and a tiny sandboxed terminal in Chromium and checks the MP4s

Each case builds what it needs in its own temp dir and prints one line; the exit code is the number that failed. */
import { execFileSync } from 'node:child_process';
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { createRequire } from 'node:module';
import { fadeOffsets, firstDenied, captionFilter, encodeFrames, stitch, checkLength, lengthOf, contactSheet,
  director, encodeClip, handEase, reachMs, sleep, FFMPEG, RESULT_MS, MAX_FILM_S } from './film.mjs';
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

/** A page that is not a browser: its clock counts the ms it is moved on (and fires `at` hooks), a capture is an empty
 *  PNG, and the mouse moves it is sent are kept. */
const fakePage = () => {
  const log = { ran: 0, moves: [], hooks: [] };
  return {
    log,
    addInitScript: async () => {},
    clock: { install: async () => {}, pauseAt: async () => {}, resume: async () => {},
      runFor: async (ms) => { log.ran += ms; log.hooks = log.hooks.filter(([at, fn]) => (log.ran >= at ? (fn(), false) : true)); } },
    context: () => ({ newCDPSession: async () => ({ send: async (m) => (m === 'Page.captureScreenshot' ? { data: '' } : {}) }) }),
    viewportSize: () => ({ width: 1920, height: 1080 }),
    evaluate: async () => '',
    frames: () => [{ evaluate: async () => {} }],
    mouse: { move: async (x, y) => { log.moves.push([x, y]); }, down: async () => {}, up: async () => {} },
    keyboard: { type: async () => {}, press: async () => {} },
    url: () => 'about:blank',
  };
};
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);

await check('director: a beat takes frames only in its own calls, one per 1/fps of film, and the page clock moves exactly that', async () => {
  for (const fps of [30, 60]) {
    const page = fakePage(), dir = tmp();
    try {
      const d = await director(page, { frames: dir, fps });
      await d.beat('one', '');
      await page.evaluate(() => 1);
      eq(page.log.ran, 0, `${fps} fps: no frame before the first call that takes time`);
      await d.hold(1000);
      await d.hold(500);
      await d.stop();
      await d.hold(300);   // after the beat: real time, no frame
      eq([d.beats()[0].frames.length, page.log.ran], [fps * 1.5, 1500], `${fps} fps: frames and page ms for 1.5 s of film`);
      eq(d.beats()[0].frames.every((f) => f.dur === 1 / fps), true, `${fps} fps: every frame lasts 1/fps`);
    } finally { rmSync(dir, { recursive: true, force: true }); }
  }
});

await check('director: a camera cue right after beat() is in force on its first frame (no pop), and a move changes the view every frame', async () => {
  const page = fakePage(), dir = tmp(), box = { x: 1200, y: 600, w: 480, h: 270 };
  try {
    const d = await director(page, { frames: dir });
    await d.beat('wide', '');
    await d.hold(200);
    await d.beat('close', '');
    await d.camera(box, { ms: 0 });
    await d.hold(200);
    await d.camera('all', { ms: 500 });
    await d.beat('after', '');
    await d.hold(100);
    await d.stop();
    const [wide, close, after] = d.beats();
    const v = viewFor(box, { w: 1920, h: 1080 });
    eq(wide.frames.map((f) => f.view.s), wide.frames.map(() => 1), 'the beat before stays wide to its last frame');
    eq(close.frames[0].view, v, 'the first frame of the beat is already on the box');
    const move = close.frames.slice(6);
    eq(move.length, 15, 'the move takes its 500 ms of frames');
    move.forEach((f, i) => { if (i && same(f.view, move[i - 1].view)) throw new Error(`frame ${i} of the move repeats the one before`); });
    eq(after.frames[0].view, rest({ w: 1920, h: 1080 }), 'a beat with no cue opens where the last one left the camera');
  } finally { rmSync(dir, { recursive: true, force: true }); }
});

await check('director: the cursor moves on every frame of a move like a hand, and a far reach takes longer than a near one', async () => {
  const page = fakePage(), dir = tmp();
  try {
    const d = await director(page, { frames: dir });
    await d.moveTo(100, 100, 0);
    await d.beat('reach', '');
    await d.moveTo(1500, 800);
    await d.page.mouse.down(); await d.hold(100); await d.page.mouse.up();
    await d.stop();
    const f = d.beats()[0].frames, n = Math.round((reachMs(Math.hypot(1400, 700)) * 30) / 1000);
    eq(f.length, n + 3, 'the reach takes reachMs of frames, then the press');
    const pts = [{ x: 100, y: 100 }, ...f.slice(0, n).map((x) => x.cursor)];
    const stepAt = (i) => Math.hypot(pts[i + 1].x - pts[i].x, pts[i + 1].y - pts[i].y);
    for (let i = 0; i < n; i++) if (!(stepAt(i) > 0.01)) throw new Error(`the cursor stood still on frame ${i}`);
    const mid = stepAt(Math.floor(n / 2));
    if (!(stepAt(0) < mid / 3 && stepAt(n - 1) < mid / 3)) throw new Error(`not eased: ${stepAt(0)}, ${mid}, ${stepAt(n - 1)}`);
    eq(f[n - 1].cursor, { x: 1500, y: 800 }, 'it arrives');
    eq(page.log.moves.length, n + 1, 'the page is told where the mouse is on each frame it moves');
    eq(f.slice(n).map((x) => Math.round(x.click.age * 30)), [0, 1, 2], 'the ring ages a frame a frame from the press');
    if (!(reachMs(1400) > reachMs(100) && reachMs(100) > 0 && reachMs(5000) <= 900)) throw new Error('reachMs does not grow with distance');
    near(handEase(0.5), 0.5, 1e-9, 'handEase is symmetric');
  } finally { rmSync(dir, { recursive: true, force: true }); }
});

await check('director: wait() films until the page call settles, and sleep() is the film\'s clock inside a beat and real time outside', async () => {
  const page = fakePage(), dir = tmp();
  try {
    const d = await director(page, { frames: dir });
    await d.beat('one', '');
    const done = new Promise((r) => page.log.hooks.push([400, () => r('typed')]));
    eq(await d.wait(done), 'typed', 'wait() gives back what the call gave');
    eq(d.beats()[0].frames.length, 12, 'frames until it settled');
    await sleep(100);
    eq(d.beats()[0].frames.length, 15, 'sleep() in a beat is frames');
    await d.stop();
    const t0 = Date.now();
    await sleep(120);
    if (Date.now() - t0 < 100) throw new Error('sleep() outside a beat did not wait');
    eq([d.beats()[0].frames.length, page.log.ran], [15, 500], 'no frames and no page time outside the beat');
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

/** The frames of a video: each one's time (s, from ffprobe) and a hash of its picture (framemd5). */
const probeFrames = (mp4) => {
  const times = execFileSync(FFMPEG.replace(/ffmpeg$/, 'ffprobe'), ['-v', 'error', '-select_streams', 'v', '-show_entries', 'frame=pts_time',
    '-of', 'csv=p=0', mp4], { encoding: 'utf8' }).trim().split('\n').map(Number);
  const md5 = execFileSync(FFMPEG, ['-v', 'error', '-i', mp4, '-f', 'framemd5', '-'], { encoding: 'utf8' })
    .split('\n').filter((l) => l && !l.startsWith('#')).map((l) => l.split(',').pop().trim());
  return { times, md5 };
};
/** Every time an exact 1/fps step from the first (to the microsecond ffprobe prints). */
const exact = (times, fps, what) => times.forEach((t, i) => near(t, i / fps, 1e-6, `${what}: frame ${i}'s time`));

await check('encodeFrames: one image sequence at -framerate, every timestamp an exact 1/fps step and every frame kept', () => {
  const dir = tmp();
  try {
    const files = ['red', 'lime', 'blue', 'white'].map((c) => {
      const f = join(dir, `${c}.png`);
      execFileSync(FFMPEG, ['-loglevel', 'error', '-y', '-f', 'lavfi', '-i', `color=c=${c}:s=640x360`, '-frames:v', '1', f]);
      return f;
    });
    for (const fps of [30, 60]) {
      const mp4 = join(dir, `x${fps}.mp4`);
      near(encodeFrames(files.map((file) => ({ file, dur: 1 / fps })), { mp4, list: join(dir, 'l'), fps }), 4 / fps, 1e-9, 'returned length');
      const { times, md5 } = probeFrames(mp4);
      exact(times, fps, `${fps} fps`);
      eq(new Set(md5).size, 4, `${fps} fps: four frames in, four different frames out`);
    }
    const mp4 = join(dir, 'held.mp4');
    near(encodeFrames([{ file: files[0], dur: 0.1 }, { file: files[1], dur: 0 }, { file: files[2], dur: 0.2 }], { mp4, list: join(dir, 'l') }), 0.3, 1e-9, 'held length');
    const { times, md5 } = probeFrames(mp4);
    exact(times, 30, 'held');
    eq([md5.length, new Set(md5.slice(0, 3)).size, new Set(md5.slice(3)).size, md5[0] !== md5[3]], [9, 1, 1, true], 'a held frame repeats for its length; a zero-length one is dropped');
    const fmt = execFileSync(FFMPEG.replace(/ffmpeg$/, 'ffprobe'), ['-v', 'error', '-select_streams', 'v', '-show_entries', 'stream=pix_fmt',
      '-of', 'csv=p=0', mp4], { encoding: 'utf8' }).trim();
    eq(fmt, 'yuv420p', 'pixel format');
  } finally { rmSync(dir, { recursive: true, force: true }); }
});

await check('stitch: hard cuts add up the clips, a crossfade overlaps them', () => {
  const dir = tmp();
  try {
    const c = [clip(dir, 'a', 1.2), clip(dir, 'b', 1, 'teal'), clip(dir, 'c', 0.8, 'olive')];
    stitch(c, { mp4: join(dir, 'cut.mp4') });
    near(lengthOf(join(dir, 'cut.mp4')), 3.0, 0.07, 'hard cuts');
    exact(probeFrames(join(dir, 'cut.mp4')).times, 30, 'across the cuts');
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
    // each side waits on the other, not on the clock, so a loaded box only makes it slower: 'one' is printed before
    // the mark is dropped, and 'two' half a second after (record.py reads the marks every 20 ms)
    const said = join(dir, 'said'), marked = join(dir, 'marked');
    const script = `echo one; touch ${said}; until [ -f ${marked} ]; do sleep 0.02; done; echo two; touch ${stop}; sleep 5; echo never`;
    const driver = `until [ -f ${said} ]; do sleep 0.02; done; printf 'mid\\t{"panes":[]}\\n' >> ${marks}; sleep 0.5; touch ${marked}`;
    execFileSync('bash', ['-c', `(${driver}) & python3 ${join(HERE, 'record.py')} --out ${cast} --cols 40 --rows 5 --marks ${marks} --stop ${stop} -- bash -c '${script}'; wait`]);
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

// ── motion/: the drawn-film kit (pure maths, the React pieces, the stutter measure) ──
const M = await import('./motion/motion.mjs');
const { frameDiffs, stutters } = await import('./motion/measure.mjs');

await check('motion: every easing runs 0 to 1 without going back, and bezier() matches CSS where CSS is known', () => {
  for (const [name, e] of Object.entries(M.EASE)) {
    near(e(0), 0, 1e-6, `${name}(0)`); near(e(1), 1, 1e-6, `${name}(1)`);
    for (let i = 1; i <= 100; i++) if (e(i / 100) < e((i - 1) / 100) - 1e-9) throw new Error(`${name} goes back at ${i / 100}`);
  }
  near(M.bezier(0, 0, 1, 1)(0.3), 0.3, 1e-6, 'linear bezier');
  near(M.bezier(0.42, 0, 0.58, 1)(0.5), 0.5, 1e-4, 'ease-in-out at half way');
  near(M.tween(5, 1, 2, 10, 20), 20, 0, 'tween holds its end'); near(M.tween(0, 1, 2, 10, 20), 10, 0, 'tween holds its start');
});

await check('motion: a critically damped spring never overshoots and settles when settle() says; an underdamped one does overshoot', () => {
  eq(M.spring(0.5, 1), 0, 'before release');
  const s = M.settle({ freq: 1.6 });
  for (let ms = 0; ms <= 3000; ms++) if (M.spring(ms / 1000, 0, { freq: 1.6 }) > 1 + 1e-9) throw new Error(`overshoots at ${ms} ms`);
  if (Math.abs(1 - M.spring(s, 0, { freq: 1.6 })) > 0.005 || Math.abs(1 - M.spring(s - 0.05, 0, { freq: 1.6 })) <= 0.005) throw new Error(`settle ${s} is not the edge`);
  let peak = 0;
  for (let ms = 0; ms <= 3000; ms++) peak = Math.max(peak, M.spring(ms / 1000, 0, { freq: 1.6, damping: 0.4 }));
  if (peak < 1.2) throw new Error(`damping 0.4 peaked at ${peak}, no bounce`);
});

await check('motion: a ripple exists only for its own span, its ring grows every frame while fading, and the press dot is gone by half way', () => {
  eq([M.ripple(0.99, 1), M.ripple(1 + 0.55, 1)], [null, null], 'outside its span');
  let last = null;
  for (let f = 0; f < 16; f++) {
    const r = M.ripple(1 + f / 30, 1);
    if (!r) throw new Error(`frame ${f} has no ripple`);
    if (last && !(r.r > last.r && r.ring < last.ring)) throw new Error(`frame ${f}: ring did not grow and fade`);
    if (f / 30 >= 0.55 / 2 && r.dot !== 0) throw new Error(`frame ${f}: dot still there`);
    last = r;
  }
});

await check('motion: drift is the same for the same seed, different for another, and moves under 0.2 px a frame', () => {
  eq(M.drift(7.3, { seed: 2 }), M.drift(7.3, { seed: 2 }), 'same seed');
  if (same(M.drift(7.3, { seed: 2 }), M.drift(7.3, { seed: 3 }))) throw new Error('two seeds drift alike');
  for (let f = 1; f < 1800; f++) {
    const a = M.drift((f - 1) / 30), b = M.drift(f / 30);
    if (Math.hypot(b.x - a.x, b.y - a.y) > 0.2) throw new Error(`frame ${f} jumps`);
  }
});

await check('motion: camera keys hold before the first and after the last, move on every frame between, and never pop at a key', () => {
  const keys = [{ t: 1, s: 1, fx: 640, fy: 360 }, { t: 2, s: 1.5, fx: 500, fy: 300 }, { t: 3, s: 1.2, fx: 700, fy: 400, ease: M.EASE.out }];
  eq(M.cameraKeys(keys, 0), { s: 1, fx: 640, fy: 360 }, 'before'); eq(M.cameraKeys(keys, 9), { s: 1.2, fx: 700, fy: 400 }, 'after');
  for (let f = 31; f < 90; f++) if (same(M.cameraKeys(keys, (f - 1) / 30), M.cameraKeys(keys, f / 30))) throw new Error(`frame ${f} still`);
  for (const k of keys) { const a = M.cameraKeys(keys, k.t - 1e-6), b = M.cameraKeys(keys, k.t); near(a.fx, b.fx, 1e-3, `fx at ${k.t}`); near(a.s, b.s, 1e-5, `s at ${k.t}`); }
});

await check('motion: blur samples sit centred on the frame across the shutter, and one sample is the sharp frame', () => {
  eq(M.blurTimes(2, 30, 1), [2], 'one sample');
  const ts = M.blurTimes(2, 30, 5, 0.5);
  eq(ts.length, 5, 'count'); near(ts[2], 2, 1e-9, 'centre'); near(ts[4] - ts[0], 0.5 / 30, 1e-9, 'span');
  near(M.frameTravel((t) => ({ x: 300 * t, y: 0 }), 1, 30), 10, 1e-9, 'travel of 300 px/s at 30 fps');
  eq(M.typed('hello', 0.5, 0, 1), 'hel', 'typed');
});

await check('measure: stutters() flags a frame frozen inside a move, and passes a hold and a smooth move', () => {
  const smooth = Array.from({ length: 40 }, (_, i) => (i ? 2 : 0));
  eq(stutters(smooth), [], 'smooth');
  const hold = [0, 2, 2, 2, ...Array(20).fill(0), 2, 2];
  eq(stutters(hold), [], 'a hold');
  const jank = smooth.map((v, i) => (i % 6 === 5 ? 0 : v));
  eq(stutters(jank), [5, 11, 17, 23, 29, 35], 'every 6th frozen');
});

await check('measure: frameDiffs finds the 25-to-30 fps repeat in a real encode and none in a native 30 fps one', () => {
  const dir = tmp();
  try {
    const enc = (name, vf) => {
      const f = join(dir, name);
      execFileSync(FFMPEG, ['-hide_banner', '-loglevel', 'error', '-y', '-f', 'lavfi', '-i', 'testsrc2=s=320x180:r=25:d=2', '-vf', vf,
        '-c:v', 'libx264', '-crf', '12', '-pix_fmt', 'yuv420p', f]);
      return f;
    };
    const bad = stutters(frameDiffs(enc('jank.mp4', 'fps=30')));
    if (bad.length < 8) throw new Error(`found ${bad.length} stutters in a 25->30 resample`);
    execFileSync(FFMPEG, ['-hide_banner', '-loglevel', 'error', '-y', '-f', 'lavfi', '-i', 'testsrc2=s=320x180:r=30:d=2',
      '-c:v', 'libx264', '-crf', '12', '-pix_fmt', 'yuv420p', join(dir, 'ok.mp4')]);
    eq(stutters(frameDiffs(join(dir, 'ok.mp4'))), [], 'native 30 fps');
  } finally { rmSync(dir, { recursive: true, force: true }); }
});

await check('pieces: render to markup, each a function of t: a ripple only in its span, a message only once in, n blur samples', async () => {
  const { modules, MOTION_PINS } = await import('./deps.mjs');
  const req = createRequire(join(dirname(modules(MOTION_PINS)), 'x.js'));
  const React = req('react'), { renderToStaticMarkup: html } = req('react-dom/server');
  const P = (await import('./motion/pieces.mjs')).pieces(React);
  const h = React.createElement;
  eq([html(h(P.Ripple, { t: 0.9, at: 1 })), html(h(P.Ripple, { t: 2, at: 1 }))], ['', ''], 'ripple outside its span');
  const r = html(h(P.Ripple, { t: 1.05, at: 1 }));
  if (!r.includes('data-piece="ring"') || !r.includes('data-piece="dot"')) throw new Error('ripple without ring or dot: ' + r);
  eq(html(h(P.MessageIn, { t: 0.9, at: 1 }, 'hi')), '', 'message before it lands');
  if (!html(h(P.MessageIn, { t: 3, at: 1 }, 'hi')).includes('hi')) throw new Error('message after it lands');
  /* the entrance blur is gone before the rise's still tail (q 0.85, about 0.27 s in at freq 2.4), and on while it moves fast */
  if (!html(h(P.MessageIn, { t: 1.1, at: 1 }, 'hi')).includes('blur(')) throw new Error('no blur early in the rise');
  if (html(h(P.MessageIn, { t: 1.4, at: 1 }, 'hi')).includes('blur(')) throw new Error('blur still on in the tail');
  /* the height opens as a fraction of the real one (a grid row of p fr) and clips only while it opens; once open the row
     stays (dropping it re-rasters the text), and an item that was always there has no row at all */
  const opening = html(h(P.MessageIn, { t: 1.2, at: 1 }, 'hi')), open = html(h(P.MessageIn, { t: 3, at: 1 }, 'hi'));
  if (!/grid-template-rows:0\.\d+fr/.test(opening) || !opening.includes('overflow:hidden')) throw new Error('no clipped p fr row while opening');
  if (!open.includes('grid-template-rows') || open.includes('overflow:hidden')) throw new Error('row dropped or clip kept after opening');
  if (html(h(P.MessageIn, { t: 3 }, 'hi')).includes('grid-template-rows')) throw new Error('a row on an item that was always there');
  const b = html(h(P.MotionBlur, { t: 1, fps: 30, n: 5, render: (t) => h('i', null, t.toFixed(4)) }));
  eq((b.match(/data-sample/g) || []).length, 5, 'blur samples');
  if (!b.includes('opacity:0.2')) throw new Error('the 5th sample is not at 1/5: ' + b);
  eq(html(h(P.MotionBlur, { t: 1, n: 1, render: () => h('i', null, 'x') })), '<i>x</i>', 'one sample is the sharp frame');
  const typedNow = html(h(P.Typed, { t: 0.5, t0: 0, t1: 1, text: 'abcd', caret: false }));
  eq(typedNow, 'ab', 'typed half way');
});

if (process.argv.includes('--film')) {
  const { recordTerminal, terminalPage } = await import('./term.mjs');
  const { launch } = await import('./deps.mjs');
  /** Rows `y`..`y+h` of every frame of `mp4`, full width, as RGB: [{w, h, px}] one per frame. */
  const band = (mp4, y, h) => {
    const buf = execFileSync(FFMPEG, ['-v', 'error', '-i', mp4, '-vf', `crop=iw:${h}:0:${y},format=rgb24`, '-f', 'rawvideo', '-'], { maxBuffer: 1 << 30 });
    const w = 1920, size = w * h * 3, out = [];
    for (let o = 0; o + size <= buf.length; o += size) out.push({ w, h, px: buf.subarray(o, o + size) });
    return out;
  };
  /** The mean x of the pixels in a frame's band that `hit(r, g, b)` picks, weighted by how strongly; none: NaN. */
  const centroid = ({ w, h, px }, hit) => {
    let sx = 0, sw = 0;
    for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) { const i = (y * w + x) * 3, k = hit(px[i], px[i + 1], px[i + 2]); sx += x * k; sw += k; }
    return sw ? sx / sw : NaN;
  };
  await check('--film: a moving element and the cursor advance on every output frame, timestamps are exact, and a zoom has no pop', async () => {
    const dir = tmp();
    try {
      const browser = await launch();
      let beats;
      try {
        const p = await (await browser.newContext({ viewport: { width: 1920, height: 1080 } })).newPage();
        const d = await director(p, { frames: join(dir, 'frames'), deny: ['nosuchword'] });
        await p.setContent(`<body style="margin:0;background:#fff">
          <div id="lime" style="position:absolute;left:0;top:0;width:300px;height:300px;background:#0f0"></div>
          <div id="red" style="position:absolute;left:0;top:400px;width:60px;height:60px;background:#f00"></div>
          <style>.go{animation:mv 1.2s linear forwards}@keyframes mv{from{left:0}to{left:1500px}}</style></body>`);
        await d.moveTo(100, 800, 0);
        await d.beat('move', '');
        await p.evaluate(() => document.getElementById('red').classList.add('go'));
        await d.moveTo(1700, 800, 1000);
        await d.beat('zoom', '');
        await d.camera({ x: 1400, y: 700, w: 480, h: 270 }, { ms: 0 });
        await d.hold(300);
        await d.stop();
        beats = d.beats();
      } finally { await browser.close(); }
      const move = join(dir, 'move.mp4'), zoom = join(dir, 'zoom.mp4'), both = join(dir, 'both.mp4');
      await encodeClip(beats[0], { mp4: move, work: dir });
      await encodeClip(beats[1], { mp4: zoom, work: dir });
      stitch([move, zoom], { mp4: both });
      for (const f of [move, zoom, both]) exact(probeFrames(f).times, 30, f.split('/').pop());
      const red = band(move, 420, 20).map((f) => centroid(f, (r, g, b) => (r > 180 && g < 90 && b < 90 ? 1 : 0)));
      const arrow = band(move, 740, 100).map((f) => centroid(f, (r, g, b) => Math.max(0, 200 - (r + g + b) / 3)));
      eq(red.length, 30, 'frames in the move beat');
      for (let i = 1; i < 30; i++) {
        near(red[i] - red[i - 1], 1500 / 36, 3, `the element's step into frame ${i}`);
        if (!(arrow[i] > arrow[i - 1])) throw new Error(`the cursor did not advance into frame ${i}: ${arrow[i - 1].toFixed(2)} -> ${arrow[i].toFixed(2)}`);
      }
      const lime = band(zoom, 0, 1080).map((f) => centroid(f, (r, g, b) => (g > 180 && r < 90 && b < 90 ? 1 : 0)));
      eq(lime.length, 9, 'frames in the zoom beat');
      eq(lime.map(Number.isNaN), lime.map(() => true), 'the zoomed beat never shows the corner it zoomed away from, frame 0 included');
    } finally { rmSync(dir, { recursive: true, force: true }); }
  });

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
        await d.wait(p.evaluate(() => window.player.play('start', 'said', { speed: 2, idle: 0.2 })));
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
