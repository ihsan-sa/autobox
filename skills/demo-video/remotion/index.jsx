/* The Remotion project of the demo-video skill: one composition, Film, that plays a clip's captured frames at their
real timing and moves the camera over them frame by frame (the maths is ../camera.mjs, shared with the director).
film.mjs bundles this entry and renders it with renderMedia; its props say the size, the frames and the cues. */
import React from 'react';
import { AbsoluteFill, Composition, Img, registerRoot, useCurrentFrame, useVideoConfig } from 'remotion';
import { cameraAt, transformOf } from '../camera.mjs';

export const FPS = 30;

/** The latest captured frame at or before `t` ms (frames sorted by t). */
const shown = (frames, t) => {
  let lo = 0, hi = frames.length - 1;
  while (lo < hi) { const mid = (lo + hi + 1) >> 1; if (frames[mid].t <= t) lo = mid; else hi = mid - 1; }
  return frames[lo];
};

/** props: width, height (the rest frame, in px), frames [{src, t}], cues (camera.mjs), from (the view it opens in),
 *  bg (what shows round the page when the camera pulls back past it). */
const Film = ({ width, height, frames, cues, from, bg }) => {
  const { fps } = useVideoConfig();
  const t = (useCurrentFrame() * 1000) / fps, size = { w: width, h: height };
  const { tx, ty, s } = transformOf(cameraAt(t, cues, size, from || undefined), size);
  return (
    <AbsoluteFill style={{ background: bg, overflow: 'hidden' }}>
      <Img src={shown(frames, t).src} style={{ position: 'absolute', left: 0, top: 0, width, height,
        transformOrigin: '0 0', transform: `translate(${tx}px, ${ty}px) scale(${s})` }} />
    </AbsoluteFill>
  );
};

const Root = () => (
  <Composition id="Film" component={Film} fps={FPS} width={1920} height={1080} durationInFrames={1}
    defaultProps={{ width: 1920, height: 1080, frames: [{ src: '', t: 0 }], cues: [], from: null, bg: '#ffffff', ms: 1000 }}
    calculateMetadata={({ props }) => ({ width: props.width, height: props.height,
      durationInFrames: Math.max(1, Math.round((props.ms * FPS) / 1000)) })} />
);

registerRoot(Root);
