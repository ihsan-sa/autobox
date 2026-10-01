/* measure.mjs (the demo-video skill) — measures a rendered film's motion, so "no stutter" is a number, not a feeling.

    import { frameDiffs, stutters } from '<skill>/motion/measure.mjs';
    const d = frameDiffs('film.mp4');            // d[i]: mean change from frame i-1 to frame i, 0..255, at 320x180 grey
    const s = stutters(d);                        // frames that froze in the middle of a move

A stutter is a frame that repeats its neighbour while the frames either side of it move: the jank a 25 fps source
resampled to 30 makes every 6th frame, or a capture that missed a frame. A hold (a run of still frames) is not one. */
import { execFileSync } from 'node:child_process';

const FFMPEG = process.env.FFMPEG || '/usr/bin/ffmpeg';

/** Per-frame change of `mp4`: d[0] = 0, d[i] = mean absolute difference of frame i from frame i-1, in grey levels. */
export function frameDiffs(mp4, { w = 320, h = 180 } = {}) {
  const raw = execFileSync(FFMPEG, ['-hide_banner', '-loglevel', 'error', '-i', mp4, '-vf', `scale=${w}:${h}:flags=area,format=gray`,
    '-f', 'rawvideo', '-'], { maxBuffer: 1 << 30 });
  const n = Math.floor(raw.length / (w * h)), d = [0];
  for (let i = 1; i < n; i++) {
    let s = 0;
    const a = (i - 1) * w * h, b = i * w * h;
    for (let k = 0; k < w * h; k++) s += Math.abs(raw[b + k] - raw[a + k]);
    d.push(s / (w * h));
  }
  return d;
}

/** Indices of frozen frames inside motion: up to `run` still frames (change <= `still`) with real motion (> `moving`)
 *  on both sides. Encoder noise sits under 0.05 grey levels a frame, so a repeated frame reads as about 0. */
export function stutters(d, { still = 0.05, moving = 0.25, run = 2 } = {}) {
  const out = [];
  for (let i = 1; i < d.length - 1; i++) {
    if (d[i] > still || d[i - 1] <= moving) continue;
    let j = i;
    while (j < d.length && d[j] <= still) j++;
    if (j - i <= run && j < d.length && d[j] > moving) for (let k = i; k < j; k++) out.push(k);
    i = j;
  }
  return out;
}
