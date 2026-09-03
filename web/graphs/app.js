/* app.js — the two charts. Hand-rolled SVG on purpose: this box may be offline and a CDN chart library is an
   outward dependency the page does not need. Nothing here computes a number; both charts draw exactly what
   /api/tokens and /api/vitals return, and those are cc-graphs and cc-vitals respectively. */
'use strict';

const NS = 'http://www.w3.org/2000/svg';
const W = 1000, HT = 320, M = { l: 58, r: 14, t: 12, b: 26 };
const REFRESH = 60000;                       // the ledger ticks every 5 min and vitals every minute; 60 s is ample

const svgEl = (tag, at) => { const e = document.createElementNS(NS, tag); for (const k in at) if (at[k] != null) e.setAttribute(k, at[k]); return e; };
const el = (tag, cls, txt) => { const e = document.createElement(tag); if (cls) e.className = cls; if (txt != null) e.textContent = txt; return e; };

const fmtUsd = v => v >= 100 ? '$' + Math.round(v) : '$' + v.toFixed(2);
function fmtNum(v) {
  const a = Math.abs(v);
  if (a >= 1e9) return (v / 1e9).toFixed(a >= 1e10 ? 0 : 1) + 'B';
  if (a >= 1e6) return (v / 1e6).toFixed(a >= 1e7 ? 0 : 1) + 'M';
  if (a >= 1e3) return (v / 1e3).toFixed(a >= 1e4 ? 0 : 1) + 'k';
  return String(Math.round(v));
}
const fmtPct = v => v.toFixed(v >= 10 ? 0 : 1) + '%';
const clock = ms => new Date(ms).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
const dayName = ms => new Date(ms).toLocaleDateString([], { month: 'short', day: 'numeric' });
/* An axis over several days labelled with times of day alone reads as one evening — the date has to be on it. */
const axisLabel = (ms, spanSec) => spanSec <= 36 * 3600 ? clock(ms)
  : spanSec <= 10 * 86400 ? dayName(ms) + ' ' + clock(ms) : dayName(ms);

/* Round axis maxima to 1/2/5 x 10^k so the gridlines land on numbers a person reads without doing arithmetic. */
function niceMax(v) {
  if (!(v > 0)) return 1;
  const k = Math.pow(10, Math.floor(Math.log10(v))), m = v / k;
  return (m <= 1 ? 1 : m <= 2 ? 2 : m <= 2.5 ? 2.5 : m <= 5 ? 5 : 10) * k;
}

/* ---------------------------------------------------------------- one chart, both graphs use it
   cfg: {n, at(i)->ms, spanMs, dayLabels, series:[{key,label,colour,dash,values,band,alt,hidden,flag}],
         fmt, altFmt, yMax, stacked, partialLast, total} — values may hold nulls and a null BREAKS the line; it is
   never interpolated, because a gap in the recorder is a fact and joining across it would draw a minute that was
   never recorded. `band` is cc-vitals' per-minute MAX: the peak the mean hides, filled behind its own line. */
function draw(svg, tip, cfg) {
  while (svg.firstChild) svg.removeChild(svg.firstChild);
  const vis = cfg.series.filter(s => !s.hidden);
  const x = i => M.l + (cfg.n < 2 ? 0 : (i / (cfg.n - 1)) * (W - M.l - M.r));
  const at = cfg.at;

  let top = cfg.yMax;
  if (top == null) {
    let mx = 0;
    for (let i = 0; i < cfg.n; i++) {
      let acc = 0;
      for (const s of vis) { const v = s.values[i]; if (v == null) continue; if (cfg.stacked) acc += v; else mx = Math.max(mx, v); }
      if (cfg.stacked) mx = Math.max(mx, acc);
    }
    top = niceMax(mx);
  }
  const y = v => HT - M.b - Math.min(v, top) / top * (HT - M.b - M.t);

  for (let k = 0; k <= 4; k++) {
    const v = top * k / 4, yy = y(v);
    svg.appendChild(svgEl('line', { x1: M.l, x2: W - M.r, y1: yy, y2: yy, stroke: 'var(--grid)', 'stroke-width': 1 }));
    const t = svgEl('text', { x: M.l - 8, y: yy + 4, 'text-anchor': 'end' });
    t.textContent = cfg.fmt(v); svg.appendChild(t);
  }
  /* "Sep 1 16:00" is close to twice the width of "16:00", and at seven ticks the first two ran into each other
     on the 7 d view. The long form gets five. */
  const spanSec = cfg.n * (cfg.spanMs / 1000);
  const every = Math.max(1, Math.ceil(cfg.n / (spanSec > 36 * 3600 && spanSec <= 10 * 86400 ? 5 : 7)));
  for (let i = 0; i < cfg.n; i += every) {
    const t = svgEl('text', { x: x(i), y: HT - M.b + 15, 'text-anchor': i === 0 ? 'start' : 'middle' });
    t.textContent = axisLabel(at(i), spanSec);
    svg.appendChild(t);
  }

  /* The last bucket is not over and the tick that books its spend may not have run: it is shaded, not drawn as
     a cliff. */
  if (cfg.partialLast && cfg.n > 1) {
    svg.appendChild(svgEl('rect', { x: x(cfg.n - 1.5), y: M.t, width: x(cfg.n - 1) - x(cfg.n - 1.5) + 4,
      height: HT - M.b - M.t, fill: 'var(--ink2)', opacity: 0.07 }));
  }

  /* The band goes down first, behind every line: it is context for one series, never a series of its own. */
  for (const s of vis) {
    if (!s.band) continue;
    let up = '', down = '', open = false;
    for (let i = 0; i < cfg.n; i++) {
      const v = s.values[i], b = s.band[i];
      if (v == null || b == null) { open = false; continue; }
      up += (open ? 'L' : 'M') + x(i).toFixed(1) + ' ' + y(b).toFixed(1) + ' ';
      down = 'L' + x(i).toFixed(1) + ' ' + y(v).toFixed(1) + ' ' + down;
      open = true;
    }
    if (up) svg.appendChild(svgEl('path', { d: up + down + 'Z', fill: s.colour, opacity: 0.16, stroke: 'none' }));
  }

  const base = new Array(cfg.n).fill(0);
  for (const s of vis) {
    let d = '', area = '', open = false;
    const pts = [];
    for (let i = 0; i < cfg.n; i++) {
      const v = s.values[i];
      if (v == null) { open = false; pts.push(null); continue; }
      const top0 = cfg.stacked ? base[i] + v : v;
      pts.push(top0);
      d += (open ? 'L' : 'M') + x(i).toFixed(1) + ' ' + y(top0).toFixed(1) + ' ';
      open = true;
    }
    if (cfg.stacked) {
      /* ONE CLOSED SUBPATH PER RUN of drawn buckets. One polygon whose return leg 'L's straight across a gap
         closes the shape over it and fills a smooth wedge — on the 7 d view that drew a rising ramp over the six
         backfilled days the footnote had just called BLANK, which is the chart contradicting itself in the
         reader's favour. A gap has to break the fill exactly as it breaks the line. */
      for (let i = 0; i < cfg.n;) {
        if (pts[i] == null) { i++; continue; }
        let j = i;
        while (j + 1 < cfg.n && pts[j + 1] != null) j++;
        area = '';
        for (let k = i; k <= j; k++) area += (k === i ? 'M' : 'L') + x(k).toFixed(1) + ' ' + y(pts[k]).toFixed(1) + ' ';
        for (let k = j; k >= i; k--) area += 'L' + x(k).toFixed(1) + ' ' + y(base[k]).toFixed(1) + ' ';
        svg.appendChild(svgEl('path', { d: area + 'Z', fill: s.colour, opacity: 0.5, stroke: 'none' }));
        i = j + 1;
      }
      for (let i = 0; i < cfg.n; i++) if (pts[i] != null) base[i] = pts[i];
    }
    svg.appendChild(svgEl('path', { d, fill: 'none', stroke: s.colour, 'stroke-width': 2,
      'stroke-dasharray': s.dash === 'solid' ? null : s.dash, 'stroke-linejoin': 'round' }));
    /* A bucket alone between two gaps has no segment to be part of, and a stroked path with one point draws
       nothing at all — so it would vanish silently. It gets a dot instead. */
    for (let i = 0; i < cfg.n; i++) {
      if (pts[i] == null || (i > 0 && pts[i - 1] != null) || (i + 1 < cfg.n && pts[i + 1] != null)) continue;
      svg.appendChild(svgEl('circle', { cx: x(i).toFixed(1), cy: y(pts[i]).toFixed(1), r: 2, fill: s.colour }));
    }
  }

  const rule = svgEl('line', { y1: M.t, y2: HT - M.b, stroke: 'var(--ink2)', 'stroke-width': 1, opacity: 0 });
  svg.appendChild(rule);
  const hit = svgEl('rect', { x: M.l, y: M.t, width: W - M.l - M.r, height: HT - M.b - M.t, fill: 'transparent' });
  svg.appendChild(hit);

  const move = ev => {
    const b = svg.getBoundingClientRect();
    const px = (ev.clientX - b.left) / b.width * W;
    let i = Math.round((px - M.l) / (W - M.l - M.r) * (cfg.n - 1));
    i = Math.max(0, Math.min(cfg.n - 1, i));
    rule.setAttribute('x1', x(i)); rule.setAttribute('x2', x(i)); rule.setAttribute('opacity', 0.55);
    const rows = vis.map(s => ({ s, v: s.values[i] })).filter(r => r.v != null).sort((a, b2) => b2.v - a.v);
    const when = cfg.spanMs >= 86400000 ? dayName(at(i))
      : dayName(at(i)) + ' ' + clock(at(i)) + (cfg.spanMs > 60000 ? '–' + clock(at(i) + cfg.spanMs) : '');
    let html = '<div class="when">' + when + (cfg.partialLast && i === cfg.n - 1 ? ' · in progress' : '') + '</div><table>';
    for (const r of rows) {
      const alt = r.s.alt && r.s.alt[i] != null && cfg.altFmt ? ' <span style="color:var(--ink2)">(' + cfg.altFmt(r.s.alt[i], r.s) + ')</span>' : '';
      html += '<tr><td><span class="sw" style="background:' + r.s.colour + '"></span>' + r.s.label +
              '</td><td class="v">' + cfg.fmt(r.v) + alt + '</td></tr>';
    }
    if (!rows.length) html += '<tr><td style="color:var(--ink2)">no data</td></tr>';
    else if (cfg.total) html += '<tr><td style="color:var(--ink2)">total</td><td class="v">' +
      cfg.fmt(rows.reduce((a, r) => a + r.v, 0)) + '</td></tr>';
    tip.innerHTML = html + '</table>';
    tip.style.opacity = 1;
    const wrap = tip.parentElement.getBoundingClientRect();
    const left = ev.clientX - wrap.left + 14;
    tip.style.left = Math.min(left, wrap.width - tip.offsetWidth - 6) + 'px';
    tip.style.top = Math.max(4, ev.clientY - wrap.top - tip.offsetHeight - 10) + 'px';
  };
  hit.addEventListener('mousemove', move);
  hit.addEventListener('mouseleave', () => { tip.style.opacity = 0; rule.setAttribute('opacity', 0); });
}

/* ---------------------------------------------------------------- controls and legend */
function controls(host, groups, onPick) {
  const buttons = [];
  host.replaceChildren();
  for (const g of groups) {
    const box = el('div', 'grp');
    box.appendChild(el('span', 'lbl', g.label));
    for (const [val, txt] of g.options) {
      const b = el('button', 'opt', txt);
      b.type = 'button';
      b.onclick = () => { g.set(val); sync(); onPick(); };
      buttons.push([b, g, val]);
      box.appendChild(b);
    }
    host.appendChild(box);
  }
  // The pressed state is read back off the live setting, never tracked separately: the buttons and the state
  // cannot disagree, including when a setter changes more than the one field it was clicked for.
  function sync() { for (const [b, g, val] of buttons) b.setAttribute('aria-pressed', String(g.get() === val)); }
  sync();
}

function legend(host, series, redraw) {
  host.replaceChildren();
  for (const s of series) {
    const b = el('button');
    b.type = 'button';
    b.setAttribute('aria-pressed', String(!s.hidden));
    const key = el('span', 'key');
    key.style.borderTopColor = s.colour;
    key.style.borderTopStyle = s.dash === 'solid' ? 'solid' : 'dashed';
    b.append(key, el('span', null, s.label), el('span', 'num', s.legend || ''));
    if (s.flag) b.append(el('span', 'flag', ' ' + s.flag));
    b.onclick = () => { s.hidden = !s.hidden; redraw(); };
    host.appendChild(b);
  }
}

const get = async url => {
  const r = await fetch(url, { cache: 'no-store' });
  const j = await r.json().catch(() => ({ error: 'bad response (' + r.status + ')' }));
  if (!r.ok || j.error) throw new Error(j.error || 'request failed');
  return j;
};

/* ---------------------------------------------------------------- the token graph */
/* The chosen view lives in the query string, so a particular chart is a link — which is the whole point of the
   one URL that goes on the Slack Home tab. Anything unrecognised falls back to the default rather than erroring. */
const Q = new URLSearchParams(location.search);
const pick = (name, allowed, dflt) => { const v = Q.get(name); return allowed.includes(v) ? v : dflt; };
const pickNum = (name, allowed, dflt) => { const v = +Q.get(name); return allowed.includes(v) ? v : dflt; };
function saveQuery() {
  const q = new URLSearchParams({ hours: TOK.hours, by: TOK.by, metric: TOK.metric,
                                  draw: TOK.stacked ? 'stacked' : 'lines', vitals: VIT.hours });
  history.replaceState(null, '', location.pathname + '?' + q);
}

const TOK = {
  hours: pickNum('hours', [6, 24, 168, 720], 24),
  by: pick('by', ['lane', 'track', 'repo', 'model', 'kind'], 'lane'),
  metric: pick('metric', ['tokens', 'out', 'usd'], 'tokens'),
  stacked: pick('draw', ['stacked', 'lines'], 'stacked') === 'stacked',
  METRICS: { tokens: ['tokens', fmtNum], out: ['output tokens', fmtNum], usd: ['$ (estimate)', fmtUsd] },
  data: null, hidden: new Set(),
};
const MET_FIELD = { tokens: 'tokens', out: 'out', usd: 'usd' };

function tokensRender() {
  const d = TOK.data, [mlabel, fmt] = TOK.METRICS[TOK.metric], field = MET_FIELD[TOK.metric];
  const series = d.groups.map(g => ({
    key: g.key, label: g.label, colour: g.colour, dash: g.dash,
    values: g[field], hidden: TOK.hidden.has(g.key), legend: fmt(g.total[field]),
  }));
  draw(document.getElementById('tokens-svg'), document.getElementById('tokens-tip'),
       { n: d.n, at: i => (d.t0 + i * d.step) * 1000, spanMs: d.step * 1000,
         series, fmt, stacked: TOK.stacked, total: true, partialLast: d.partial });
  legend(document.getElementById('tokens-legend'), series, () => {
    TOK.hidden = new Set(series.filter(s => s.hidden).map(s => s.key));
    tokensRender();
  });
  document.getElementById('tokens-now').textContent =
    fmtNum(d.total.tokens) + ' tokens · ' + fmtUsd(d.total.usd) + ' est · ' + d.rows.toLocaleString() + ' ledger rows';

  const bucket = d.step >= 86400 ? (d.step / 86400) + ' day' : d.step >= 3600 ? (d.step / 3600) + ' h' : (d.step / 60) + ' min';
  const foot = document.getElementById('tokens-foot');
  foot.replaceChildren();
  const p1 = el('p');
  p1.innerHTML = '<b>' + mlabel + '</b>, ' + bucket + ' buckets, grouped by <b>' + d.by + '</b>. A point is ' + d.means + '.';
  foot.appendChild(p1);
  if (d.coarse.days.length) {
    const days = d.coarse.days.map(c => c.day);
    const which = days.length > 3 ? days[0] + ' … ' + days[days.length - 1] : days.join(', ');
    const p = el('p', 'flag');
    // Say the SIGNATURE, not the cause: one row per session-model is what the server detected, and a backfill is
    // only its usual explanation. Asserting the cause told the reader something the data does not carry.
    p.textContent = '⚠ ' + days.length + ' opening day(s) of the ledger — ' + which + ', ' + fmtUsd(d.coarse.usd) +
      ' — hold one row per session and model, so they carry no shape within the day and the chart is BLANK ' +
      'over them rather than zero. Usually the ledger\'s first tick, which backfilled what was already on ' +
      'disk. Pick 30 d for daily totals.';
    foot.appendChild(p);
  }
  if (d.folded) foot.appendChild(el('p', 'note', 'More than ' + d.max_groups + ' groups: the tail is folded into `other`.'));
  const det = el('details');
  det.appendChild(el('summary', null, 'what a line is, and what this excludes'));
  const lanes = el('p', 'note', 'Lanes: ' + Object.entries(d.lanes).map(([k, v]) => k + ' = ' + v).join(' · ') +
    '. `review` is a landing review (its own throwaway worktree), `worker` a track loop iteration, `session` an ' +
    'interactive transcript. Group by track for the individual process.');
  det.append(lanes, el('p', 'note', 'Excludes: ' + d.excludes + '.'),
    el('p', 'note', 'The shaded last bucket is in progress — its tick may not have run yet. ' +
      'Tokens are the truth; the dollar figure is cc-spend\'s estimate from its own rates table.'));
  foot.appendChild(det);
}

/* ---------------------------------------------------------------- the vitals graph (cc-vitals owns every number) */
const VIT = { hours: pickNum('vitals', [1, 6, 24, 72], 24), data: null, hidden: new Set() };
const VCOLS = 480;                           // ~2 px a column on a full-width card; below this nothing is reduced

/* cc-vitals' own column rule, from render_text: column i covers minutes [i*n/cols, (i+1)*n/cols) and is the MEAN
   of the ones that were recorded; a column with no recorded minute stays a gap. Applied only when there are more
   minutes than columns — narrow the window and the chart is minute-exact again. A band is reduced by MAX, not
   mean, because the whole point of the band is the peak a mean hides. */
function reduce(arr, n, cols, how) {
  const out = [];
  for (let i = 0; i < cols; i++) {
    const lo = Math.floor(i * n / cols), hi = Math.max(lo + 1, Math.floor((i + 1) * n / cols));
    let sum = 0, cnt = 0, mx = null;
    for (let j = lo; j < hi && j < n; j++) {
      const v = arr[j];
      if (v == null) continue;
      sum += v; cnt++; mx = mx == null ? v : Math.max(mx, v);
    }
    out.push(cnt ? (how === 'max' ? mx : sum / cnt) : null);
  }
  return out;
}

function vitalsRender() {
  const d = VIT.data;
  const cols = Math.min(d.n, VCOLS), thin = d.n > cols;
  const cut = (a, how) => (a && thin ? reduce(a, d.n, cols, how) : a);
  const series = d.series.map(s => ({
    key: s.key, label: s.label, colour: s.colour, dash: s.dash,
    values: cut(s.norm), band: cut(s.norm_max, 'max'), alt: cut(s.real),
    hidden: VIT.hidden.has(s.key), legend: (s.now && s.now.text) || '', cap: s.cap_text,
    flag: s.over ? '⚠ over 100%' : '',
  }));
  const per = d.n / cols * d.step;             // seconds one drawn column covers
  draw(document.getElementById('vitals-svg'), document.getElementById('vitals-tip'),
       { n: cols, at: i => (d.t0 + Math.floor(i * d.n / cols) * d.step) * 1000, spanMs: per * 1000,
         series, fmt: fmtPct, yMax: d.axis.max,
         altFmt: (v, s) => (+v).toFixed(2) + ' of ' + s.cap });
  legend(document.getElementById('vitals-legend'), series, () => {
    VIT.hidden = new Set(series.filter(s => s.hidden).map(s => s.key));
    vitalsRender();
  });
  /* Stale means THE RECORDER is behind — not that this JSON is old. `generated` is the second cc-vitals answered
     this request, so measuring against it reads ~0 every time and the warning would never fire. cc-vitals stamps
     a row at the START of the minute it covers, so the age of the data is measured from the END of the newest
     recorded minute: the minute in progress gives a negative age, which is not being behind, and clamps to 0. */
  let last = -1;
  for (let i = d.n - 1; i >= 0 && last < 0; i--) if (d.series.some(s => s.norm[i] != null)) last = i;
  const age = last < 0 ? null : Math.max(0, Date.now() / 1000 - (d.t0 + (last + 1) * d.step));
  document.getElementById('vitals-now').textContent =
    d.minutes + ' of ' + d.n + ' minutes recorded' + (d.gaps ? ' · ' + d.gaps + ' gap(s)' : '') +
    (last < 0 ? ' · ⚠ nothing recorded in this window'
     : age > d.stale_after ? ' · ⚠ recorder ' + Math.round(age / 60) + ' min behind' : '');

  const foot = document.getElementById('vitals-foot');
  foot.replaceChildren();
  foot.appendChild(el('p', null, d.axis.label + ' — ' + d.axis.note));
  const c = d.checkout || {}, dns = d.dns || {};
  const bits = [];
  for (const h in dns) bits.push(h + ' ' + (dns[h] == null ? 'no answer' : dns[h] + ' ms'));
  if (c.branch) bits.push('main checkout: ' + (c.branch !== c.default ? 'on ' + c.branch
    : (c.dirty || []).length ? (c.dirty.length + ' file(s) modified') : c.ahead ? c.ahead + ' ahead' : 'clean'));
  foot.appendChild(el('p', 'note', bits.join(' · ')));
  foot.appendChild(el('p', 'note', 'Every number here is cc-vitals\' — this page runs `cc-vitals series` and draws ' +
    'what it returns. A gap in the recorder breaks the line rather than being drawn through. ' +
    (thin ? d.n + ' minutes over ' + cols + ' columns, so a point is the mean of ' + Math.round(per / 60) +
      ' minutes (cc-vitals\' own column rule) and the shaded band behind RAM and temp is the peak that mean hides; ' +
      'narrow the window for minute-exact lines.'
          : 'One point per recorded minute; the shaded band behind RAM and temp is that minute\'s peak.')));
}

/* ---------------------------------------------------------------- load, wire up, refresh */
function fail(id, e) {
  const foot = document.getElementById(id + '-foot');
  foot.replaceChildren(el('p', 'err', 'could not load: ' + e.message));
}

async function loadTokens() {
  try {
    TOK.data = await get('/api/tokens?hours=' + TOK.hours + '&by=' + TOK.by);
    tokensRender();
  } catch (e) { fail('tokens', e); }
}
async function loadVitals() {
  try {
    VIT.data = await get('/api/vitals?hours=' + VIT.hours);
    vitalsRender();
  } catch (e) { fail('vitals', e); }
}

controls(document.getElementById('tokens-ctl'), [
  { label: 'window', options: [[6, '6 h'], [24, '24 h'], [168, '7 d'], [720, '30 d']],
    get: () => TOK.hours, set: v => { TOK.hours = v; } },
  { label: 'lines', options: [['lane', 'lane'], ['track', 'track'], ['repo', 'repo'], ['model', 'model'], ['kind', 'kind']],
    get: () => TOK.by, set: v => { TOK.by = v; TOK.hidden = new Set(); } },
  { label: 'metric', options: [['tokens', 'tokens'], ['out', 'output'], ['usd', '$ est']],
    get: () => TOK.metric, set: v => { TOK.metric = v; } },
  { label: 'draw', options: [[true, 'stacked'], [false, 'lines']],
    get: () => TOK.stacked, set: v => { TOK.stacked = v; } },
], () => { saveQuery(); loadTokens(); });

controls(document.getElementById('vitals-ctl'), [
  { label: 'window', options: [[1, '1 h'], [6, '6 h'], [24, '24 h'], [72, '72 h']],
    get: () => VIT.hours, set: v => { VIT.hours = v; } },
], () => { saveQuery(); loadVitals(); });

setInterval(() => { if (!document.hidden) { loadTokens(); loadVitals(); } }, REFRESH);
loadTokens();
loadVitals();
