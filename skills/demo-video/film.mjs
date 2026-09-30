/* film.mjs (the demo-video skill) — what every demo video shares: a drawn cursor with eased moves, a recorder that films a few short
beats and can cut the dull parts (a server restart, a compile) out of each, a check that nothing real is in frame,
and the encode: each beat a clip with its caption, the clips crossfaded into one film, and a GIF of it. A surface
seeds its own fake data, starts its own throwaway server and writes the script.

The recorder is Chromium's screencast (CDP), not Playwright's recordVideo: it keeps every frame as a JPEG with the
compositor's timestamp, so the film is sharp, its timing is the real one, and a paused stretch is simply not there.
The camera is not filmed: the page is captured at rest, each camera move is kept as a cue, and a clip with a move in
it is rendered by Remotion (remotion/), which frames every output frame from the cues, so a move is smooth even when
headless Chromium delivered 10 frames a second. */
import { createReadStream, mkdirSync, writeFileSync, rmSync } from 'node:fs';
import { execFileSync, spawnSync } from 'node:child_process';
import { createServer } from 'node:http';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { cameraAt, rest } from './camera.mjs';

export const FFMPEG = process.env.FFMPEG || '/usr/bin/ffmpeg';
export const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/* The pace (docs/demo-video-research.md): a film of about 20 s and never over MAX_FILM_S, quick cuts, and a result
held at least RESULT_MS so it can be read — a floor for a result, not the pace of the film. */
export const RESULT_MS = 800;
export const MAX_FILM_S = 30;

/* The caption, in one place: a strip of its own below (or above) the page, drawn by ffmpeg, so it never covers what
it describes. One caption per beat. The look is the library's: its paper and ink, a rust mark before the words, and
Source Serif. Change the look here and nowhere else; a surface with a font of its own sets CAPTION.font (or
DEMO_CAPTION_FONT), and without either it is the system's semibold serif. */
const serif = () => { try { return execFileSync('fc-match', ['-f', '%{file}', 'serif:semibold'], { encoding: 'utf8' }); } catch { return ''; } };
export const CAPTION = {
  at: 'bottom',                                  // 'bottom' or 'top'
  height: 56,                                    // px; the page's viewport is the film's height less this
  bg: '#FAF8F3', rule: '#DED8CA',                // the library's paper, and a hairline between it and the page
  ink: '#15140F', accent: '#9C4221',             // the words, and the mark before them
  font: process.env.DEMO_CAPTION_FONT || serif(), size: 23,
  x: 36,                                         // left inset of the mark; the words follow it
};

// The cursor and the click ring live in the page, above everything and never in the way of a click.
const OVERLAY = String.raw`(() => {
  const css = '#demo-cursor{position:fixed;left:0;top:0;width:26px;height:26px;z-index:2147483647;pointer-events:none;' +
    'transform:translate(-100px,-100px);filter:drop-shadow(0 2px 3px rgba(0,0,0,.35))}' +
    '#demo-ring{position:fixed;width:36px;height:36px;margin:-18px 0 0 -18px;border-radius:50%;border:3px solid #9C4221;' +
    'z-index:2147483646;pointer-events:none;opacity:0;transform:scale(.3)}' +
    '#demo-ring.go{animation:demo-ring .4s ease-out}' +
    '@keyframes demo-ring{0%{opacity:.9;transform:scale(.3)}100%{opacity:0;transform:scale(1.4)}}';
  const add = () => {
    if (document.getElementById('demo-cursor')) return;
    const st = document.createElement('style'); st.textContent = css; document.documentElement.appendChild(st);
    const c = document.createElement('div'); c.id = 'demo-cursor';
    c.innerHTML = '<svg viewBox="0 0 26 26" width="26" height="26"><path d="M3 2 L3 21 L8 16.5 L11.5 24 L14.8 22.6 L11.4 15.2 L18 15.2 Z" fill="#111" stroke="#fff" stroke-width="1.6" stroke-linejoin="round"/></svg>';
    const ring = document.createElement('div'); ring.id = 'demo-ring';
    document.documentElement.append(c, ring);
    // under the page's zoom (the director's zoom) a fixed box is placed in zoomed pixels, and the mouse is in screen pixels
    const z = () => window.__demoZoom || 1;
    const put = (x, y) => { c.style.transform = 'translate(' + (x / z() - 3) + 'px,' + (y / z() - 2) + 'px)'; };
    const at = window.__demoAt || [-100, -100];
    put(at[0], at[1]);
    addEventListener('mousemove', (e) => { window.__demoAt = [e.clientX, e.clientY]; put(e.clientX, e.clientY); }, true);
    addEventListener('mousedown', (e) => { ring.style.left = e.clientX / z() + 'px'; ring.style.top = e.clientY / z() + 'px'; ring.classList.remove('go'); void ring.offsetWidth; ring.classList.add('go'); }, true);
  };
  if (window.__demoZoom && window.__demoZoom !== 1) {
    const zoom = () => { document.documentElement.style.zoom = window.__demoZoom; };
    if (document.documentElement) zoom(); else addEventListener('DOMContentLoaded', zoom);
  }
  if (document.readyState === 'loading') addEventListener('DOMContentLoaded', add); else add();
})();`;

const ease = (t) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);

/** Every render runs the kit's own selfcheck first (once per process tree), so a broken kit fails loudly before
 *  anything is filmed. DEMO_VIDEO_CHECKED is set for the rest of the run and inherited by the selfcheck itself. */
export function preflight() {
  if (process.env.DEMO_VIDEO_CHECKED) return;
  process.env.DEMO_VIDEO_CHECKED = '1';
  const r = spawnSync(process.execPath, ['--no-warnings', join(dirname(fileURLToPath(import.meta.url)), 'selfcheck.mjs')],
    { encoding: 'utf8', env: process.env });
  if (r.status !== 0) throw new Error(`demo-video selfcheck failed, so nothing was filmed:\n${(r.stdout || '') + (r.stderr || '')}`);
}

/** The director of one page: moves, clicks and typing at a quick human pace, a camera, and the screencast behind
 *  them. The film is a few short beats, each its own clip with at most one caption: `beat(name, caption)` starts one
 *  (and ends the one before), `cut()` / `roll()` take a slow stretch out of the current one, `stop()` ends the last.
 *  `zoom` scales the whole page (CSS zoom), so a layout made for 1280x720 fills a 1920x1080 viewport sharply. */
export async function director(page, { frames, deny = [], zoom = 1 }) {
  preflight();
  await page.addInitScript(`window.__demoZoom = ${Number(zoom)};`);
  await page.addInitScript(OVERLAY);
  const cdp = await page.context().newCDPSession(page);
  const beats = [];   // {name, caption, shots: [{file, t}], cuts: [[from, to]], end}, times wall clock in seconds
  const cues = [];    // the camera's moves, {wall (s), ms, box, fill, max, dip}, over the whole page's life
  const vp = (page.viewportSize && page.viewportSize()) || { width: 1280, height: 720 };
  const size = { w: vp.width, h: vp.height };
  let pos = { x: vp.width / 2, y: vp.height / 2 }, n = 0, rolling = false;
  const cur = () => beats[beats.length - 1];
  /** The cursor from where it is to `to` over `ms` of wall clock, bent sideways by `bend` px at the middle. Each step is
   *  placed by the clock, not counted, so a slow round trip to the browser costs smoothness, never length. */
  const glide = async (to, ms, bend) => {
    const from = { ...pos }, dist = Math.hypot(to.x - from.x, to.y - from.y);
    const nx = -(to.y - from.y) / (dist || 1), ny = (to.x - from.x) / (dist || 1);
    const t0 = Date.now();
    for (;;) {
      const f = ms > 0 ? Math.min(1, (Date.now() - t0) / ms) : 1, t = ease(f), arc = Math.sin(Math.PI * t) * bend;
      await page.mouse.move(from.x + (to.x - from.x) * t + nx * arc, from.y + (to.y - from.y) * t + ny * arc);
      if (f >= 1) break;
      await sleep(12);
    }
    pos = { x: to.x, y: to.y };
  };
  mkdirSync(frames, { recursive: true });
  cdp.on('Page.screencastFrame', async ({ data, metadata, sessionId }) => {
    cdp.send('Page.screencastFrameAck', { sessionId }).catch(() => {});
    if (!rolling || !cur()) return;
    const file = join(frames, `f${String(++n).padStart(6, '0')}.jpg`);
    writeFileSync(file, Buffer.from(data, 'base64'));
    cur().shots.push({ file, t: metadata.timestamp || Date.now() / 1000 });
  });
  const start = async () => {
    rolling = true;
    // frames come at the viewport's CSS size whatever the deviceScaleFactor, so the viewport is the film's size
    await cdp.send('Page.startScreencast', { format: 'jpeg', quality: 92, everyNthFrame: 1 });
    await sleep(120);
  };
  const halt = async () => { rolling = false; await cdp.send('Page.stopScreencast'); };
  const end = async () => {
    const b = cur();
    if (!b || b.end) return;
    await sleep(150);
    b.end = Date.now() / 1000;
    if (rolling) await halt();
    await d.scrub();
  };
  const d = {
    page,
    /** Start the next beat, a clip of its own under `caption` (the caption is checked like the page). */
    async beat(name, caption) {
      await end();
      const hit = firstDenied(caption, deny);
      if (hit) throw new Error(`a real name is in the caption ("${hit}")`);
      beats.push({ name, caption, shots: [], cuts: [], end: 0 });
      await d.scrub();
      await start();
    },
    /** Resume the current beat after a cut. */
    async roll() { const c = cur().cuts; if (c.length && c[c.length - 1][1] == null) c[c.length - 1][1] = Date.now() / 1000; await start(); },
    /** Pause the current beat: what happens until the next roll() is not in it. */
    async cut() { await sleep(100); await halt(); cur().cuts.push([Date.now() / 1000, null]); },
    /** End the last beat. */
    stop: () => end(),
    hold: (ms) => sleep(ms),
    /** Hold on a result long enough to read it: at least RESULT_MS, whatever the pace around it. */
    show: (ms = RESULT_MS) => { if (ms < RESULT_MS) throw new Error(`a result is held ${ms} ms, under the ${RESULT_MS} ms floor`); return sleep(ms); },
    /** Move the camera to `view` over `ms`: 'all' (the whole page), a locator, or a box {x, y, w, h} in screen pixels.
     *  The page is never moved (it is filmed at rest, so a box, the cursor and a click are all in the same pixels
     *  whatever the camera does): the move is kept as a cue and drawn when the clip is rendered, and this waits `ms`
     *  so the script's pace is the film's. `fill` is how much of the frame the box takes, `max` caps the zoom
     *  (research: 1.5-2.2x reads as a zoom, more loses the place), `dip` pulls back mid-flight for a swoop. */
    async camera(view, { ms = 700, fill = 0.92, max = 2.2, dip = 0 } = {}) {
      let box = null;
      if (view !== 'all') {
        box = view;
        if (typeof view.boundingBox === 'function') {
          const r = await view.boundingBox();
          if (!r) throw new Error('nothing to point the camera at: ' + view);
          box = { x: r.x, y: r.y, w: r.width, h: r.height };
        }
      }
      cues.push({ wall: Date.now() / 1000, ms, box, fill, max, dip });
      await sleep(ms);
    },
    /** Move the drawn cursor to (x, y) along a slight arc, easing in and out, in `ms` of wall clock. */
    async moveTo(x, y, ms) {
      const dist = Math.hypot(x - pos.x, y - pos.y);
      const bend = Math.min(40, dist * 0.08) * (x > pos.x ? -1 : 1);
      await glide({ x, y }, ms ?? Math.min(550, 180 + dist * 0.35), bend);
    },
    /** Re-draw the cursor where it was (after a reload the page has forgotten it). */
    async park() { await page.mouse.move(pos.x, pos.y); },
    /** The point to aim at in a locator's box: fx, fy are fractions of its width and height. */
    async aim(loc, fx = 0.5, fy = 0.5) {
      // a toolbar that re-renders between the lookup and the scroll detaches the element: look it up again
      for (let i = 0; ; i++) {
        try { await loc.scrollIntoViewIfNeeded(); break; } catch (e) { if (i >= 3 || !/not attached/.test(e.message)) throw e; await sleep(100); }
      }
      const b = await loc.boundingBox();
      if (!b) throw new Error('nothing to aim at: ' + loc);
      return { x: b.x + b.width * fx, y: b.y + b.height * fy };
    },
    async click(loc, opts = {}) {
      const p = await d.aim(loc, opts.fx, opts.fy);
      await d.moveTo(p.x, p.y);
      await sleep(70);
      await page.mouse.down(); await sleep(50); await page.mouse.up();
      await sleep(opts.after ?? 220);
      await d.scrub();
    },
    /** Scroll `loc`'s nearest scrolling box, eased over `ms`, until its middle sits at `frac` of the viewport's
     *  height (as far as the box can go). In the page, so the motion is smooth whatever the round trips cost. */
    async scrollTo(loc, frac = 0.45, ms = 450) {
      await loc.evaluate((el, [frac, ms]) => new Promise((done) => {
        let box = el.parentElement;
        while (box && !(box.scrollHeight > box.clientHeight + 1 && /(auto|scroll)/.test(getComputedStyle(box).overflowY))) box = box.parentElement;
        box = box || document.scrollingElement;
        const r = el.getBoundingClientRect();
        const from = box.scrollTop;
        const to = Math.max(0, Math.min(box.scrollHeight - box.clientHeight, from + r.top + r.height / 2 - innerHeight * frac));
        const e = (t) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);
        const t0 = performance.now();
        const step = (now) => {
          const t = Math.min(1, (now - t0) / ms);
          box.scrollTop = from + (to - from) * e(t);
          if (t < 1) requestAnimationFrame(step); else done();
        };
        requestAnimationFrame(step);
      }), [frac, ms]);
      await sleep(80);
    },
    /** Drag-select from one point to another, quick but visible. */
    async drag(a, b, ms = 320) {
      await d.moveTo(a.x, a.y); await sleep(60);
      await page.mouse.down();
      await glide(b, ms, 0);
      await page.mouse.up(); await sleep(120);
    },
    /** Type as a quick typist does, about `cps` keys a second of wall clock, not every key at the same speed. */
    async type(text, cps = 32) {
      const t0 = Date.now();
      let due = 0;
      for (const ch of text) {
        await page.keyboard.type(ch);
        due += (1000 / cps) * (0.6 + Math.random() * 0.8) * (ch === ' ' ? 1.3 : 1);
        await sleep(due - (Date.now() - t0));
      }
    },
    async press(key, after = 250) { await page.keyboard.press(key); await sleep(after); },
    /** Fail if any denied word is on screen: the visible text, field values and the tab title. */
    async scrub() {
      const seen = await page.evaluate(() => [document.title, document.body.innerText,
        ...[...document.querySelectorAll('input, textarea')].map((e) => e.value || e.placeholder || '')].join('\n'));
      const hit = firstDenied(seen, deny);
      if (hit) throw new Error(`a real name is in frame ("${hit}") at ${page.url()}`);
    },
    /** The beats, each with its frames' durations and its camera: [{name, caption, frames: [{file, dur}], camera}]. */
    beats() { return beats.map((b) => ({ name: b.name, caption: b.caption, frames: timeline(b.shots, b.cuts, b.end), camera: beatCamera(b) })); },
  };
  const wallCues = () => cues.map((c) => ({ ...c, t: c.wall * 1000 }));
  /* A beat's camera: the view it opens in (where the moves before it left the camera) and its own moves, their t in
  ms of the clip, counted from its first frame with the cut stretches taken out, as the frames' durations are. */
  const beatCamera = (b) => {
    if (!b.shots.length) return { size, from: rest(size), cues: [] };
    const t0 = b.shots[0].t, film = filmClock(b.cuts);
    return {
      size,
      from: cameraAt(t0 * 1000, wallCues().filter((c) => c.wall < t0), size),
      cues: cues.filter((c) => c.wall >= t0 && c.wall <= b.end)
        .map(({ wall, ms, box, fill, max, dip }) => ({ t: (film(wall) - film(t0)) * 1000, ms, box, fill, max, dip })),
    };
  };
  return d;
}

/** The first denied word in `text`, any case; none: undefined. */
export function firstDenied(text, deny) {
  const low = String(text).toLowerCase();
  return deny.find((w) => low.includes(w.toLowerCase()));
}

/** The film's clock for a wall-clock time: the cut stretches before it taken out (inside one, where it began). */
export function filmClock(cuts) {
  const lost = (t) => cuts.reduce((s, [a, b]) => s + (b != null && b <= t ? b - a : a <= t ? t - a : 0), 0);
  return (t) => t - lost(t);
}

/** Frame durations from capture times, with the cut stretches taken out. Exported for the selfcheck. */
export function timeline(shots, cuts, end) {
  const film = filmClock(cuts);
  const out = [];
  for (let i = 0; i < shots.length; i++) {
    const t0 = film(shots[i].t), t1 = film(i + 1 < shots.length ? shots[i + 1].t : end);
    out.push({ file: shots[i].file, dur: Math.max(0, t1 - t0) });
  }
  return out;
}

const hex = (c) => c.replace(/^#/, '0x');
const q = ['-hide_banner', '-loglevel', 'error', '-y'];
const H264 = ['-c:v', 'libx264', '-preset', 'slow', '-crf', '20', '-pix_fmt', 'yuv420p', '-movflags', '+faststart'];

/** The ffmpeg filter that adds the caption strip (CAPTION's look) to a frame, its words read from `textFile`.
 *  Exported for the selfcheck. */
export function captionFilter(textFile, cap = CAPTION) {
  const H = cap.height, strip = cap.at === 'top' ? '0' : `ih-${H}`;
  const pad = cap.at === 'top' ? `pad=iw:ih+${H}:0:${H}:color=${hex(cap.bg)}` : `pad=iw:ih+${H}:0:0:color=${hex(cap.bg)}`;
  const rule = `drawbox=x=0:y=${cap.at === 'top' ? H - 1 : `ih-${H}`}:w=iw:h=1:color=${hex(cap.rule)}:t=fill`;
  const bar = `drawbox=x=${cap.x}:y=${strip}+${Math.round(H / 2 - cap.size * 0.55)}:w=3:h=${Math.round(cap.size * 1.1)}:color=${hex(cap.accent)}:t=fill`;
  // drawtext calls the frame's height h, not ih
  const words = `drawtext=fontfile='${cap.font}':textfile='${textFile}':fontsize=${cap.size}:fontcolor=${hex(cap.ink)}:` +
    `x=${cap.x + 16}:y=${cap.at === 'top' ? '0' : `h-${H}`}+(${H}-lh)/2:y_align=font`;
  return [pad, rule, bar, words].join(',');
}

/** Whether a beat's camera moves or opens anywhere but at rest, so its clip needs rendering by Remotion. */
export const camerawork = (cam) => !!cam && (cam.cues.length > 0 || cam.from.s !== 1 || cam.from.x !== cam.size.w / 2 || cam.from.y !== cam.size.h / 2);

/** One beat's clip: its frames at their real timing, 30 fps H.264, with its caption strip when it has a caption. A
 *  beat whose camera moves is rendered by Remotion first (renderCamera), then captioned by ffmpeg like the rest.
 *  Resolves to the clip's seconds. */
export async function encodeClip(beat, { mp4, work }) {
  const kept = beat.frames.filter((f) => f.dur > 0);
  if (!kept.length) throw new Error(`beat ${beat.name} has no frames`);
  const list = join(work, `${beat.name}.frames.txt`), text = join(work, `${beat.name}.caption.txt`);
  writeFileSync(text, beat.caption || '');
  const vf = beat.caption ? captionFilter(text) : '';
  if (!camerawork(beat.camera)) return encodeFrames(kept, { mp4, list, vf });
  const raw = join(work, `${beat.name}.camera.mp4`);
  writeFileSync(join(work, `${beat.name}.camera.json`), JSON.stringify(beat.camera));   // the moves, to check a clip against
  const secs = await renderCamera(kept, beat.camera, { mp4: raw });
  execFileSync(FFMPEG, [...q, '-i', raw, '-vf', `${vf ? vf + ',' : ''}scale=trunc(iw/2)*2:trunc(ih/2)*2:out_range=tv,format=yuv420p`,
    ...H264, mp4], { stdio: 'inherit' });
  rmSync(raw, { force: true });
  return secs;
}

const REMOTION = join(dirname(fileURLToPath(import.meta.url)), 'remotion', 'index.jsx');
let bundled = null;   // one webpack bundle of the composition per process

/** Frames (each {file, dur}) with a camera ({size, from, cues}) as a 30 fps MP4, rendered by Remotion's Film
 *  composition in the Chromium deps.mjs finds: every output frame shows the latest frame captured at or before it,
 *  moved by the camera at that exact time. The frames reach the renderer from a throwaway local HTTP server. Near
 *  lossless (crf 10), since encodeClip encodes it once more with the caption. Resolves to seconds. */
export async function renderCamera(frames, camera, { mp4, bg = '#ffffff' }) {
  const { need, chrome, modules } = await import('./deps.mjs');
  const { bundle } = need('@remotion/bundler'), { selectComposition, renderMedia } = need('@remotion/renderer');
  const nm = modules();
  bundled ||= bundle({
    entryPoint: REMOTION,
    rootDir: dirname(nm),   // webpack's cache goes beside the modules, not into the checkout
    // the composition's imports (remotion, react) come from the film's node_modules, not from beside it
    webpackOverride: (c) => ({ ...c, resolve: { ...c.resolve, modules: [nm, 'node_modules'] } }),
  });
  const serveUrl = await bundled;
  const server = createServer((req, res) => {
    const f = frames[Number((req.url.match(/^\/(\d+)\.jpg$/) || [])[1])];
    if (!f) { res.writeHead(404).end(); return; }
    res.writeHead(200, { 'content-type': 'image/jpeg', 'access-control-allow-origin': '*' });
    createReadStream(f.file).pipe(res);
  });
  await new Promise((r) => server.listen(0, '127.0.0.1', r));
  try {
    const base = `http://127.0.0.1:${server.address().port}`;
    let t = 0;
    const shots = frames.map((f, i) => { const s = { src: `${base}/${i}.jpg`, t }; t += f.dur * 1000; return s; });
    const inputProps = { width: camera.size.w, height: camera.size.h, frames: shots, cues: camera.cues, from: camera.from, bg, ms: t };
    const browserExecutable = chrome() || null;
    const opts = { serveUrl, inputProps, browserExecutable, chromeMode: 'chrome-for-testing', logLevel: 'error' };
    const composition = await selectComposition({ ...opts, id: 'Film' });
    await renderMedia({ ...opts, composition, codec: 'h264', crf: 10, pixelFormat: 'yuv420p', imageFormat: 'jpeg', jpegQuality: 95,
      outputLocation: mp4, overwrite: true });
    return composition.durationInFrames / composition.fps;
  } finally { server.close(); }
}

/** Frames as an MP4 at their real timing, 30 fps, yuv420p in TV range (the screencast's JPEGs are full range, which
 *  some players show washed out), with an optional extra filter `vf`. The last frame is listed twice
 *  (the concat demuxer's way to honour its duration), so -t holds the clip to the frames' own length. Returns seconds. */
export function encodeFrames(frames, { mp4, list, vf = '' }) {
  const kept = frames.filter((f) => f.dur > 0);
  if (!kept.length) throw new Error(`no frames for ${mp4}`);
  writeFileSync(list, kept.map((f) => `file '${f.file}'\nduration ${f.dur.toFixed(4)}\n`).join('') + `file '${kept[kept.length - 1].file}'\n`);
  const secs = kept.reduce((s, f) => s + f.dur, 0);
  execFileSync(FFMPEG, [...q, '-f', 'concat', '-safe', '0', '-i', list,
    '-vf', `fps=30,${vf ? vf + ',' : ''}scale=trunc(iw/2)*2:trunc(ih/2)*2:out_range=tv,format=yuv420p`, '-t', secs.toFixed(3), ...H264, mp4], { stdio: 'inherit' });
  return secs;
}

/** Where each crossfade starts, for clips of these lengths joined with `fade` seconds of overlap. Exported for the
 *  selfcheck. */
export function fadeOffsets(lengths, fade) {
  const out = [];
  let t = 0;
  for (let i = 0; i < lengths.length - 1; i++) { t += lengths[i] - fade; out.push(t); }
  return out;
}

/** The clips joined into one film: hard cuts by default (fade 0), or each crossfading into the next over `fade` s. */
export function stitch(clips, { mp4, fade = 0 }) {
  if (clips.length === 1) { execFileSync(FFMPEG, [...q, '-i', clips[0], '-c', 'copy', mp4]); return; }
  if (!fade) {
    const graph = clips.map((_, i) => `[${i}:v]`).join('') + `concat=n=${clips.length}:v=1:a=0[v]`;
    execFileSync(FFMPEG, [...q, ...clips.flatMap((c) => ['-i', c]), '-filter_complex', graph, '-map', '[v]', '-r', '30', ...H264, mp4], { stdio: 'inherit' });
    return;
  }
  const at = fadeOffsets(clips.map(lengthOf), fade);
  let graph = '', last = '0:v';
  at.forEach((off, i) => {
    const out = i === at.length - 1 ? 'v' : `x${i}`;
    graph += `[${last}][${i + 1}:v]xfade=transition=fade:duration=${fade}:offset=${off.toFixed(3)}[${out}];`;
    last = out;
  });
  execFileSync(FFMPEG, [...q, ...clips.flatMap((c) => ['-i', c]), '-filter_complex', graph.replace(/;$/, ''), '-map', '[v]',
    '-r', '30', ...H264, mp4], { stdio: 'inherit' });
}

/** A GIF of a film: fewer frames, smaller, its own palette. */
export function toGif(mp4, { gif, work, width = 960, fps = 12 }) {
  const pal = join(work, 'palette.png');
  const vf = `fps=${fps},scale=${width}:-1:flags=lanczos`;
  execFileSync(FFMPEG, [...q, '-i', mp4, '-vf', `${vf},palettegen=stats_mode=diff`, pal], { stdio: 'inherit' });
  execFileSync(FFMPEG, [...q, '-i', mp4, '-i', pal, '-lavfi', `${vf}[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle`, gif], { stdio: 'inherit' });
  rmSync(pal, { force: true });
}

/** Seconds of a media file, from ffprobe beside ffmpeg. */
export function lengthOf(file) {
  const probe = FFMPEG.replace(/ffmpeg$/, 'ffprobe');
  return Number(execFileSync(probe, ['-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', file], { encoding: 'utf8' }).trim());
}

/** Fail when a film runs over MAX_FILM_S (DEMO_LONG=1 lets a long one through on purpose). Returns its length. */
export function checkLength(mp4, max = MAX_FILM_S) {
  const secs = lengthOf(mp4);
  if (secs > max && !process.env.DEMO_LONG) throw new Error(`${mp4} is ${secs.toFixed(1)} s, over ${max} s: cut it down`);
  return secs;
}

/** A contact sheet of a film: `n` frames spread evenly over it, tiled `cols` wide, each `width` px, into one PNG. Look
 *  at it before calling a film done: it shows at a glance what is on screen, and anything that should not be. */
export function contactSheet(mp4, png, { n = 12, cols = 4, width = 480 } = {}) {
  const secs = lengthOf(mp4), rows = Math.ceil(n / cols);
  execFileSync(FFMPEG, [...q, '-i', mp4, '-vf', `fps=${(n / secs).toFixed(5)},scale=${width}:-2,tile=${cols}x${rows}:padding=6:margin=6:color=white`,
    '-frames:v', '1', '-update', '1', png], { stdio: 'inherit' });
  return png;
}
