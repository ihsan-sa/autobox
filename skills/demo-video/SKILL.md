---
name: demo-video
description: Make a short, scripted demo video of a project from fake data, headless - a web UI filmed in Chromium with a drawn cursor and a camera that zooms and swoops, and a real terminal (tmux and bash in a sandboxed made-up workspace) recorded and replayed sharply at 1080p. Use it whenever someone asks for a demo video, product video, screencast, walkthrough clip, GIF of an app or terminal, or a README or social clip of a project. Never records a real screen, a real account or a real person's data.
---

# Demo video

A film is a script, not a recording session. You seed fake data, start a throwaway server or workspace, and write
the moves; the kit films them frame by frame and encodes each beat as a clip, the clips cut together into one MP4.
The page runs on a virtual clock that moves one frame at a time (30 fps, or 60 with `fps: 60`), so every CSS
animation, transition, rAF loop, timer, scroll and typed key moves exactly one frame's worth a frame, and the film
comes out the same however loaded the box is; a loaded box only makes the render slower. Each frame is captured at
2x, and the camera, the cursor and the click ring are drawn over it afterwards, so a zoom has real detail and the
cursor moves on every frame. Nothing real may be in frame: every beat checks the visible text against a list of denied words
(the host name, the user, the git identity, real project names) and fails when one shows.

## The pace

- About 20 s a film and never over 30 (`checkLength` fails a longer one; `DEMO_LONG=1` lets one through on purpose).
- Three to five beats, each one idea, cut hard into the next (`stitch` with no fade). Crossfade only into an end card.
- Show the thing working in the first 2 s. No title card up front.
- Hold a result at least 0.8 s (`d.show()`, which refuses less). That is a floor for a result, not the pace: the
  moves between results are quick, a cursor move 0.2-0.5 s, typing about 30 keys a second.
- One camera move a beat, zoom 1.5-2.2x (`d.camera`), eased in and out over 0.4-0.7 s. Zoom onto the result, not
  onto the cursor's travel. A swoop between two far places is `dip: 0.3`.
- Captions are optional. When the pictures say it, leave them out; when a beat needs one, keep it to one short line.
- 1920x1080 H.264, yuv420p, faststart, 30 fps (60 with `fps: 60`). A page laid out for 1280x720 is filmed at a
  1920x1080 viewport with `zoom: 1.5`.

## Files

- `film.mjs`: `director(page, {frames, deny, zoom, fps = 30, scale = 2})`, made before the page's first `goto` so
  its clock is in before the page's scripts, gives `beat`, `moveTo`, `click`, `type`, `press`, `scrollTo`, `drag`,
  `camera`, `show`, `hold`, `wait`, `cut`/`roll` (take a slow stretch out), `stop`, `beats()`. Film time passes only
  inside those calls and the kit's `sleep`, one captured frame per 1/fps; outside a beat they run in real time.
  - A page call that takes page time (typing inside the page, a terminal replay, an animation you await) goes
    through `await d.wait(page.evaluate(...))`, which films until it settles. Awaited bare, the clock would sit
    still; after 1.5 s the kit runs it anyway and warns at the beat's end, and that stretch's length then depends
    on the box.
  - `beat()` takes no frame until the first call that takes time, so `d.camera(view, {ms: 0})` right after it is in
    force from the beat's first frame. `camera` never moves the page, so boxes, the cursor and clicks stay in the
    same pixels whatever it does.
  - The cursor moves like a hand: slow off, quick in the middle, settling, along a slight arc, and a far reach takes
    longer than a near one (`reachMs`). `page.mouse.down()` from the script also spreads the click ring.
  - Then `await encodeClip` per beat: a compositor page draws each frame with the camera, cursor and ring, and
    ffmpeg encodes that image sequence once at `-framerate`, near lossless, with the caption strip when there is
    one. `stitch` is the one final encode. Also `encodeFrames` (stills with their own durations, resampled onto
    exact frames), `checkLength`, `toGif` and `contactSheet`.
- `camera.mjs`: the camera's maths (`cameraAt`, `viewFor`), pure, shared by the director, the selfcheck and the
  composition: the centre eases along a line, the scale in log space, `dip` pulls back mid-move.
- `term.mjs`: `recordTerminal({out, home, user, host, bins, script, deny})` runs tmux and bash for real in a
  bubblewrap sandbox: your made-up home at /home/<user>, a made-up host name, a passwd that knows only that user, a
  clean environment. The script types (`run`, `type`, `keys`), splits panes (`split`) and drops `mark`s. Then
  `terminalPage(cast, {dir, width, height, font})` writes a page that replays it with xterm.js; in it
  `player.seek(mark)`, `player.play(from, to, {speed, idle})` and `player.rect(mark, pane)` for the camera.
- `record.py`: the pty recorder behind `recordTerminal` (asciicast v2, with marks).
- `deps.mjs`: playwright-core and @xterm/xterm (`PINS`), installed once into ~/.cache/demo-video
  (`DEMO_NODE_MODULES` to use another node_modules), and the Chromium in ~/.cache/ms-playwright (`CHROME` to name
  another), which films the page and composites the frames.
- `selfcheck.mjs`: `node selfcheck.mjs` checks the kit without a browser; `--film` also films a moving page (a
  moving element and the cursor must advance on every output frame, timestamps must be exact, a zoom must not pop)
  and a tiny sandboxed terminal. `director()` runs the plain selfcheck first, once per render, and refuses to film
  if it fails; nothing in it depends on the box's load.

## How to make one

1. Write the story in beats: what the viewer should see working, one idea each, 3-5 beats.
2. Make the fake world: seed data, a throwaway server on a free port, or a home directory for the terminal. Made-up
   people, domains and projects only.
3. Build the denied list from the real machine at run time (host, user, git name and e-mail, real project names), so
   no real value is ever written into the script.
4. Film: a 1920x1080 context, `director`, one `beat` per idea, `show()` on each result, `camera` onto it.
5. Encode, stitch, `checkLength`, and make a `contactSheet`. Look at the sheet before you call it done: it shows
   the pace, the framing and anything in frame that should not be.

## Needs

Node 18+, ffmpeg, python3, and for terminals tmux and bwrap. The first run installs the node modules (network once).
