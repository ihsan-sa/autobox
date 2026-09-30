---
name: demo-video
description: Make a short, scripted demo video of a project from fake data, headless - a web UI filmed in Chromium with a drawn cursor and a camera that zooms and swoops, and a real terminal (tmux and bash in a sandboxed made-up workspace) recorded and replayed sharply at 1080p. Use it whenever someone asks for a demo video, product video, screencast, walkthrough clip, GIF of an app or terminal, or a README or social clip of a project. Never records a real screen, a real account or a real person's data.
---

# Demo video

A film is a script, not a recording session. You seed fake data, start a throwaway server or workspace, and write
the moves; the kit films them with Chromium's screencast and encodes each beat as a clip, the clips cut together
into one MP4. The page is filmed with the camera at rest: a camera move is kept as a cue, and a clip with one is
rendered by Remotion, which frames every output frame from the cues, so a move stays smooth when headless Chromium
delivers 10-15 frames a second. Nothing real may be in frame: every beat checks the visible text against a list of denied words
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
- 1920x1080 H.264, yuv420p, faststart. A page laid out for 1280x720 is filmed at a 1920x1080 viewport with `zoom: 1.5`.

## Files

- `film.mjs`: `director(page, {frames, deny, zoom})` gives `beat`, `moveTo`, `click`, `type`, `press`,
  `scrollTo`, `drag`, `camera`, `show`, `hold`, `cut`/`roll` (take a slow stretch out), `stop`, `beats()`. `camera`
  never moves the page, so boxes, the cursor and clicks stay in the same pixels whatever it does; it records a cue
  and waits out the move. Then `await encodeClip` per beat (Remotion for a beat whose camera moves, then ffmpeg for
  the caption strip, only when the beat has a caption), `stitch`, `checkLength`, `toGif` and `contactSheet`.
- `camera.mjs`: the camera's maths (`cameraAt`, `viewFor`), pure, shared by the director, the selfcheck and the
  composition: the centre eases along a line, the scale in log space, `dip` pulls back mid-move.
- `remotion/index.jsx`: the Film composition, 30 fps at the page's size. For each output frame it shows the latest
  captured frame at or before it, moved by the camera at that exact time. Captures are at CSS pixels (the screencast
  ignores `deviceScaleFactor`), so a zoom enlarges them.
- `term.mjs`: `recordTerminal({out, home, user, host, bins, script, deny})` runs tmux and bash for real in a
  bubblewrap sandbox: your made-up home at /home/<user>, a made-up host name, a passwd that knows only that user, a
  clean environment. The script types (`run`, `type`, `keys`), splits panes (`split`) and drops `mark`s. Then
  `terminalPage(cast, {dir, width, height, font})` writes a page that replays it with xterm.js; in it
  `player.seek(mark)`, `player.play(from, to, {speed, idle})` and `player.rect(mark, pane)` for the camera.
- `record.py`: the pty recorder behind `recordTerminal` (asciicast v2, with marks).
- `deps.mjs`: playwright-core, @xterm/xterm, Remotion and React (`PINS`), installed once into ~/.cache/demo-video
  (`DEMO_NODE_MODULES` to use another node_modules), and the Chromium in ~/.cache/ms-playwright (`CHROME` to name
  another), which films the page and renders the Remotion composition.
- `selfcheck.mjs`: `node selfcheck.mjs` checks the kit without a browser or Remotion; `--film` also records and
  films a tiny terminal, renders its camera move and checks the result. `director()` runs the plain selfcheck
  first, once per render, and refuses to film if it fails.

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
