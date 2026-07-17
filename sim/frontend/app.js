// ROOF·SIM front-end — vanilla-JS port of the design's canvas day-trading sim.
// Renders real (interpolated-to-second) Yahoo sessions loaded from the backend:
// candlestick + volume chart, synthetic order book, time & sales, positions/fills
// blotter, trend-line drawing tool, and full playback transport.

import { hashStr, mulberry32 } from './rng.js';
import { createDataSource } from './data-source.js';

const TICKS = 23400;                       // seconds in a 390-minute session
const INITIAL_CASH = 100000;               // paper starting cash
const BOOK_DEPTH = 10;                      // order-book levels per side
const IVALS = [
  { label: '5s', sec: 5 }, { label: '15s', sec: 15 }, { label: '1m', sec: 60 },
  { label: '5m', sec: 300 }, { label: '30m', sec: 1800 }, { label: '1h', sec: 3600 },
];
const SPEEDS = [1, 2, 5, 10, 30, 60];
const UP = '#16c784', DN = '#ea3943', NEUTRAL = '#8a97ab';

const state = {
  idx: 0, playing: false, speed: 10, ival: 15, ticker: 'AAPL', date: mostRecentWeekday(),
  qty: 100, loading: true, cash: null, posMap: {}, fills: [], sessions: null,
  lines: [], drawMode: false, sel: -1, draft: null,
  order: ['AAPL', 'MSFT', 'NVDA', 'TSLA', 'SPY'], names: {},
};

const source = createDataSource();
let view = null;   // { lo, hi, priceH, cw, N, endC, cs } — set by draw(), read by mouse handlers
let acc = 0;       // playback fractional-step accumulator

// ── element refs ────────────────────────────────────────────────────────────
const $ = (id) => document.getElementById(id);
const canvas = $('chart');

// ── number / time formatting (ported) ────────────────────────────────────────
function pad2(n) { return String(n).padStart(2, '0'); }
function fmtT(i) {
  const t = 9.5 * 3600 + i, h = Math.floor(t / 3600), m = Math.floor((t % 3600) / 60), s = t % 60;
  return pad2(h) + ':' + pad2(m) + ':' + pad2(s);
}
function fmt$(v) {
  return (v < 0 ? '-$' : '$') + Math.abs(v).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}
function fmtPnl(v) {
  return (v >= 0 ? '+' : '-') + '$' + Math.abs(v).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}
function pnlColor(v) { return v > 0.005 ? UP : v < -0.005 ? DN : NEUTRAL; }
function fmtSize(v) { return v >= 1000 ? (v / 1000).toFixed(v >= 10000 ? 0 : 1) + 'K' : String(v); }

// ── market data helpers (ported) ─────────────────────────────────────────────
function priceAt(t, i) {
  const s = state.sessions;
  return s ? s[t].prices[Math.max(0, Math.min(i, TICKS - 1))] : 0;
}
function quote(t, i) {
  const p = priceAt(t, i);
  const spread = Math.max(0.01, Math.round(p * 0.00008 * 100) / 100);
  const bid = Math.round((p - spread / 2) * 100) / 100;
  return { bid, ask: Math.round((bid + spread) * 100) / 100, spread, mid: p };
}
// Synthetic order book (Yahoo has no Level-2): deterministic per ticker+time+side.
function rawBook(side) {
  const { ticker, idx, sessions } = state;
  if (!sessions) return [];
  const q = quote(ticker, idx);
  const step = Math.max(0.01, Math.round(q.mid * 0.00006 * 100) / 100);
  const seedBase = hashStr(ticker + '|' + (idx >> 3) + '|' + side);
  const out = [];
  for (let k = 0; k < BOOK_DEPTH; k++) {
    const rnd = mulberry32(seedBase + k * 7919);
    const whale = rnd() < 0.12 ? 5 + rnd() * 8 : 1;
    const size = Math.round((120 + rnd() * 1800) * (1 + k * 0.35) * whale / 10) * 10;
    out.push({ price: side === 'ask' ? q.ask + step * k : q.bid - step * k, size });
  }
  return out;
}
function bookLevels(side) {
  const raw = rawBook(side);
  const maxS = Math.max(1, ...raw.map((l) => l.size));
  return raw.map((l) => ({ price: l.price.toFixed(2), size: l.size.toLocaleString(), pct: Math.round((l.size / maxS) * 88) }));
}
// Resting liquidity at a price level: stable per ticker+date+level (predictable
// S/R); round numbers attract bigger orders; rare whale walls.
function levelSize(price, idx) {
  const { ticker, date } = state;
  const cents = Math.round(price * 100);
  const seed = hashStr(ticker + '|' + date + '|' + cents);
  const rnd = mulberry32(seed);
  let base = 250 + rnd() * 1600;
  if (cents % 1000 === 0) base *= 5.5; else if (cents % 500 === 0) base *= 3; else if (cents % 100 === 0) base *= 1.8;
  if (rnd() < 0.08) base *= 5 + rnd() * 9;
  const wob = mulberry32(seed ^ hashStr('t' + (idx >> 7)))();
  return Math.round((base * (0.8 + wob * 0.4)) / 10) * 10;
}

// ── trading (ported) ─────────────────────────────────────────────────────────
function applyFill(side, qty) {
  const { ticker, idx, posMap, fills, sessions } = state;
  if (!sessions || qty < 1) return;
  const q = quote(ticker, idx);
  const price = side === 'BUY' ? q.ask : q.bid;
  const dir = side === 'BUY' ? 1 : -1;
  const pos = posMap[ticker] || { qty: 0, avg: 0, realized: 0 };
  let { qty: q0, avg, realized } = pos;
  if (q0 === 0 || Math.sign(q0) === dir) {
    avg = (avg * Math.abs(q0) + price * qty) / (Math.abs(q0) + qty); q0 += dir * qty;
  } else {
    const closed = Math.min(Math.abs(q0), qty);
    realized += closed * (price - avg) * Math.sign(q0);
    q0 += dir * qty;
    if (q0 !== 0 && Math.sign(q0) === dir) avg = price;
    if (q0 === 0) avg = 0;
  }
  state.cash -= dir * qty * price;
  state.posMap = { ...posMap, [ticker]: { qty: q0, avg, realized } };
  state.fills = [{ time: fmtT(idx), side, sym: ticker, qty, price }, ...fills].slice(0, 40);
  render();
}

// ── canvas drawing (ported) ──────────────────────────────────────────────────
function draw() {
  const cv = canvas, s = state.sessions;
  if (!cv || !s) return;
  const sess = s[state.ticker];
  if (!sess) return;
  const dpr = window.devicePixelRatio || 1;
  const W = cv.clientWidth, H = cv.clientHeight;
  if (W === 0 || H === 0) return;
  cv.width = W * dpr; cv.height = H * dpr;
  const ctx = cv.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.fillStyle = '#0a0e14'; ctx.fillRect(0, 0, W, H);
  const axW = 62, timeH = 22, profW = 64;
  const cw = W - axW, priceH = (H - timeH) * 0.74, volTop = priceH + 6, volH = H - timeH - volTop;
  const cs = state.ival, idx = state.idx;
  const endC = Math.floor(idx / cs);
  const N = Math.max(10, Math.min(Math.max(30, Math.floor(cw / 9)), Math.ceil(TICKS / cs)));
  const startC = endC - N + 1;
  const candles = [];
  let lo = Infinity, hi = -Infinity, maxV = 1;
  for (let c = Math.max(0, startC); c <= endC; c++) {
    const a = c * cs, b = Math.min(idx, a + cs - 1);
    let o = sess.prices[a], cl = sess.prices[b], h2 = -Infinity, l2 = Infinity, v = 0;
    for (let i = a; i <= b; i++) { const p = sess.prices[i]; if (p > h2) h2 = p; if (p < l2) l2 = p; v += sess.vols[i]; }
    candles.push({ c, o, c2: cl, h: h2, l: l2, v });
    if (l2 < lo) lo = l2; if (h2 > hi) hi = h2; if (v > maxV) maxV = v;
  }
  if (!candles.length) return;
  const pad = (hi - lo) * 0.08 + 0.01; lo -= pad; hi += pad;
  const y = (p) => priceH - ((p - lo) / (hi - lo)) * priceH;
  const x = (c) => cw - (endC - c + 0.5) * (cw / N);
  const bw = Math.max(2, (cw / N) * 0.62);
  ctx.strokeStyle = '#151c2a'; ctx.fillStyle = '#5a6a80'; ctx.font = '10px "IBM Plex Mono",monospace'; ctx.textBaseline = 'middle';
  for (let g = 0; g <= 5; g++) {
    const p = lo + ((hi - lo) * g) / 5, yy = y(p);
    ctx.beginPath(); ctx.moveTo(0, yy); ctx.lineTo(cw, yy); ctx.stroke();
    ctx.fillText(p.toFixed(2), cw + 6, yy);
  }
  ctx.textAlign = 'center';
  const every = Math.ceil(N / 7);
  candles.forEach((cd) => {
    if ((cd.c % every) === 0) {
      const lbl = fmtT(cd.c * cs).slice(0, 5);
      ctx.fillStyle = '#5a6a80'; ctx.fillText(lbl, x(cd.c), H - timeH / 2);
    }
  });
  ctx.textAlign = 'left';
  // volume profile (right-edge histogram over the day so far)
  const bins = 36, binC = new Float64Array(bins);
  for (let i = 0; i <= idx; i += 5) {
    const p = sess.prices[i];
    if (p >= lo && p <= hi) binC[Math.min(bins - 1, Math.floor(((p - lo) / (hi - lo)) * bins))] += sess.vols[i];
  }
  const mb = Math.max(...binC, 1);
  ctx.fillStyle = 'rgba(240,180,41,0.07)';
  for (let b = 0; b < bins; b++) {
    const w2 = (binC[b] / mb) * profW;
    ctx.fillRect(cw - w2, priceH - ((b + 1) / bins) * priceH, w2, priceH / bins - 1);
  }
  // candles + volume bars
  candles.forEach((cd) => {
    const col = cd.c2 >= cd.o ? UP : DN, xx = x(cd.c);
    ctx.strokeStyle = col; ctx.fillStyle = col;
    ctx.beginPath(); ctx.moveTo(xx, y(cd.h)); ctx.lineTo(xx, y(cd.l)); ctx.stroke();
    const yo = y(cd.o), yc = y(cd.c2);
    ctx.fillRect(xx - bw / 2, Math.min(yo, yc), bw, Math.max(1, Math.abs(yc - yo)));
    ctx.globalAlpha = 0.45;
    ctx.fillRect(xx - bw / 2, volTop + volH - (cd.v / maxV) * volH, bw, (cd.v / maxV) * volH);
    ctx.globalAlpha = 1;
  });
  // prev close reference line
  const last = sess.prices[idx];
  if (sess.prevClose >= lo && sess.prevClose <= hi) {
    ctx.strokeStyle = '#3d4a5e'; ctx.setLineDash([2, 4]);
    ctx.beginPath(); ctx.moveTo(0, y(sess.prevClose)); ctx.lineTo(cw, y(sess.prevClose)); ctx.stroke();
    ctx.setLineDash([]);
  }
  // resting BUY/SELL liquidity across the visible range (walls = S/R lines)
  ctx.font = '9px "IBM Plex Mono",monospace'; ctx.textAlign = 'right';
  const rawStep = (hi - lo) / 26, mag = Math.pow(10, Math.floor(Math.log10(rawStep)));
  const lvlStep = [1, 2, 5, 10].map((m) => m * mag).find((s2) => s2 >= rawStep) || 10 * mag;
  const levels = [];
  for (let p = Math.ceil(lo / lvlStep) * lvlStep; p <= hi; p += lvlStep) levels.push({ p, size: levelSize(p, idx) });
  const maxLvl = Math.max(1, ...levels.map((l) => l.size));
  for (const l of levels) {
    const sell = l.p >= last, col = sell ? DN : UP, yy = y(l.p);
    const bw2 = 5 + (l.size / maxLvl) * 52;
    const wall = l.size > maxLvl * 0.55;
    if (wall) {
      ctx.globalAlpha = 0.14; ctx.strokeStyle = col;
      ctx.beginPath(); ctx.moveTo(0, yy); ctx.lineTo(cw, yy); ctx.stroke();
    }
    ctx.globalAlpha = wall ? 0.42 : 0.24; ctx.fillStyle = col;
    ctx.fillRect(cw - bw2, yy - 2.5, bw2, 5);
    ctx.globalAlpha = wall ? 1 : 0.75;
    ctx.fillText(fmtSize(l.size), cw - bw2 - 4, yy);
    ctx.globalAlpha = 1;
  }
  ctx.textAlign = 'left'; ctx.font = '10px "IBM Plex Mono",monospace';
  // last-price line + axis tag
  const lc = last >= sess.prevClose ? UP : DN;
  ctx.strokeStyle = lc; ctx.setLineDash([4, 3]);
  ctx.beginPath(); ctx.moveTo(0, y(last)); ctx.lineTo(cw, y(last)); ctx.stroke();
  ctx.setLineDash([]);
  ctx.fillStyle = lc; ctx.fillRect(cw, y(last) - 8, axW, 16);
  ctx.fillStyle = '#0a0e14'; ctx.fillText(last.toFixed(2), cw + 6, y(last));
  // save transform for mouse handlers, then draw user trend lines
  view = { lo, hi, priceH, cw, N, endC, cs };
  const lx = (sec) => cw - (endC - sec / cs + 0.5) * (cw / N);
  ctx.save(); ctx.beginPath(); ctx.rect(0, 0, cw, priceH); ctx.clip();
  const drawLine = (ln, seld) => {
    const x1 = lx(ln.a.sec), y1 = y(ln.a.price), x2 = lx(ln.b.sec), y2 = y(ln.b.price);
    ctx.strokeStyle = seld ? '#ffd166' : '#f0b429'; ctx.lineWidth = seld ? 2 : 1.25;
    ctx.beginPath(); ctx.moveTo(x1, y1); ctx.lineTo(x2, y2); ctx.stroke();
    if (seld) {
      ctx.fillStyle = '#ffd166';
      [[x1, y1], [x2, y2]].forEach(([px, py]) => { ctx.beginPath(); ctx.arc(px, py, 4, 0, 7); ctx.fill(); });
    }
    ctx.lineWidth = 1;
  };
  state.lines.forEach((ln, i) => drawLine(ln, i === state.sel));
  if (state.draft) drawLine(state.draft, true);
  ctx.restore();
  // fill markers for the active ticker
  state.fills.forEach((f) => {
    if (f.sym !== state.ticker) return;
    const sec = f.time.split(':').reduce((a2, b2) => a2 * 60 + +b2, 0) - 9.5 * 3600;
    const c = Math.floor(sec / cs);
    if (c < Math.max(0, startC) || c > endC) return;
    ctx.fillStyle = f.side === 'BUY' ? UP : DN;
    const yy = y(f.price), xx = x(c);
    ctx.beginPath();
    if (f.side === 'BUY') { ctx.moveTo(xx, yy + 14); ctx.lineTo(xx - 5, yy + 22); ctx.lineTo(xx + 5, yy + 22); }
    else { ctx.moveTo(xx, yy - 14); ctx.lineTo(xx - 5, yy - 22); ctx.lineTo(xx + 5, yy - 22); }
    ctx.fill();
  });
}

// ── mouse → data mapping (ported) ────────────────────────────────────────────
function px2data(e) {
  const cv = canvas;
  if (!cv || !view) return null;
  const r = cv.getBoundingClientRect();
  const px = e.clientX - r.left, py = e.clientY - r.top;
  const c = view.endC + 0.5 - (view.cw - px) / (view.cw / view.N);
  return { sec: c * view.cs, price: view.lo + (1 - py / view.priceH) * (view.hi - view.lo), x: px, y: py };
}
function hitLine(pt) {
  if (!view || !pt) return -1;
  const lx = (sec) => view.cw - (view.endC - sec / view.cs + 0.5) * (view.cw / view.N);
  const py = (p) => view.priceH - ((p - view.lo) / (view.hi - view.lo)) * view.priceH;
  let best = -1, bestD = 7;
  state.lines.forEach((ln, i) => {
    const x1 = lx(ln.a.sec), y1 = py(ln.a.price), x2 = lx(ln.b.sec), y2 = py(ln.b.price);
    const dx = x2 - x1, dy = y2 - y1, len2 = dx * dx + dy * dy || 1;
    const t = Math.max(0, Math.min(1, ((pt.x - x1) * dx + (pt.y - y1) * dy) / len2));
    const d = Math.hypot(pt.x - (x1 + t * dx), pt.y - (y1 + t * dy));
    if (d < bestD) { bestD = d; best = i; }
  });
  return best;
}

// ── DOM rendering ─────────────────────────────────────────────────────────────
function render() {
  const st = state, s = st.sessions;
  const cash = st.cash === null ? INITIAL_CASH : st.cash;
  const sess = s ? s[st.ticker] : null;
  const q = s ? quote(st.ticker, st.idx) : { bid: 0, ask: 0, spread: 0, mid: 0 };
  const last = sess ? sess.prices[st.idx] : 0;
  const chgAbs = sess ? last - sess.prevClose : 0;
  const chgP = sess ? (chgAbs / sess.prevClose) * 100 : 0;

  // header tabs
  document.querySelectorAll('#tabs .tab').forEach((el) => {
    const t = el.dataset.ticker;
    el.classList.toggle('active', t === st.ticker);
    const chgEl = el.querySelector('.tab-chg');
    if (s && s[t]) {
      const p = priceAt(t, st.idx), pc = s[t].prevClose, d = ((p - pc) / pc) * 100;
      chgEl.textContent = (d >= 0 ? '+' : '') + d.toFixed(2) + '%';
      chgEl.style.color = pnlColor(d);
    } else { chgEl.textContent = '—'; chgEl.style.color = NEUTRAL; }
  });

  // equity + positions
  let equity = cash, dayPnl = 0;
  const posRows = [];
  if (s) {
    for (const t of st.order) {
      const pos = st.posMap[t];
      if (!pos) continue;
      const lp = priceAt(t, st.idx);
      equity += pos.qty * lp;
      const upnl = pos.qty * (lp - pos.avg);
      dayPnl += pos.realized + upnl;
      if (pos.qty !== 0 || Math.abs(pos.realized) > 0.004) posRows.push({
        sym: t, qty: String(pos.qty), qtyColor: pos.qty > 0 ? UP : pos.qty < 0 ? DN : NEUTRAL,
        avg: pos.qty !== 0 ? pos.avg.toFixed(2) : '—', last: lp.toFixed(2),
        upnl: pos.qty !== 0 ? fmtPnl(upnl) : '—', upnlColor: pnlColor(pos.qty !== 0 ? upnl : 0),
        rpnl: fmtPnl(pos.realized), rpnlColor: pnlColor(pos.realized),
      });
    }
  }

  $('cash').textContent = fmt$(cash);
  $('equity').textContent = fmt$(equity);
  const pnlEl = $('daypnl'); pnlEl.textContent = fmtPnl(dayPnl); pnlEl.style.color = pnlColor(dayPnl);

  // chart head
  $('active-sym').textContent = st.ticker;
  $('active-name').textContent = sess ? sess.name : '';
  const lastEl = $('last'); lastEl.textContent = last ? last.toFixed(2) : '—'; lastEl.style.color = pnlColor(chgAbs);
  const lchg = $('last-chg');
  lchg.textContent = sess ? (chgAbs >= 0 ? '+' : '') + chgAbs.toFixed(2) + ' (' + (chgP >= 0 ? '+' : '') + chgP.toFixed(2) + '%)' : '';
  lchg.style.color = pnlColor(chgAbs);
  document.querySelectorAll('#intervals .ival-btn').forEach((el) => el.classList.toggle('active', +el.dataset.sec === st.ival));
  $('draw-btn').classList.toggle('active', st.drawMode);
  $('del-btn').classList.toggle('hidden', st.sel < 0);
  $('clear-btn').classList.toggle('hidden', st.lines.length === 0);
  $('loading').classList.toggle('hidden', !st.loading);
  canvas.style.cursor = st.drawMode ? 'crosshair' : 'default';

  // order book
  $('spread').textContent = 'SPRD ' + q.spread.toFixed(2);
  $('asks').innerHTML = bookLevels('ask').reverse().map((a) =>
    `<div class="book-row ask"><div class="book-bar ask" style="width:${a.pct}%"></div><span class="price">${a.price}</span><span class="size">${a.size}</span></div>`).join('');
  $('bids').innerHTML = bookLevels('bid').map((b) =>
    `<div class="book-row bid"><div class="book-bar bid" style="width:${b.pct}%"></div><span class="price">${b.price}</span><span class="size">${b.size}</span></div>`).join('');
  $('bid').textContent = q.bid.toFixed(2);
  $('ask').textContent = q.ask.toFixed(2);

  // order entry
  $('notional').textContent = '≈ ' + fmt$(st.qty * q.mid);
  $('buy').textContent = 'BUY ' + q.ask.toFixed(2);
  $('sell').textContent = 'SELL ' + q.bid.toFixed(2);

  // tape
  const tape = [];
  if (sess) {
    for (let i = st.idx; i >= Math.max(0, st.idx - 25); i--) {
      const p = sess.prices[i], prev = sess.prices[Math.max(0, i - 1)];
      tape.push(`<div class="tape-row"><span class="t">${fmtT(i)}</span><span class="p" style="color:${p > prev ? UP : p < prev ? DN : NEUTRAL}">${p.toFixed(2)}</span><span class="s">${Math.round(sess.vols[i]).toLocaleString()}</span></div>`);
    }
  }
  $('tape').innerHTML = tape.join('');

  // positions + fills
  $('positions').innerHTML = posRows.map((p) =>
    `<div class="pos-row pos-grid"><span class="sym">${p.sym}</span><span class="r" style="color:${p.qtyColor}">${p.qty}</span><span class="r avg">${p.avg}</span><span class="r last">${p.last}</span><span class="r" style="color:${p.upnlColor}">${p.upnl}</span><span class="r" style="color:${p.rpnlColor}">${p.rpnl}</span></div>`).join('');
  const noPos = $('no-positions');
  if (posRows.length === 0) { noPos.textContent = `Flat — no open positions. You start with ${fmt$(INITIAL_CASH)} in paper cash.`; noPos.classList.remove('hidden'); }
  else noPos.classList.add('hidden');
  $('fills').innerHTML = st.fills.map((f) =>
    `<div class="fill-row"><span class="t">${f.time}</span><span class="side" style="color:${f.side === 'BUY' ? UP : DN}">${f.side}</span><span class="sym">${f.sym}</span><span class="qty">${f.qty}</span><span class="price">${f.price.toFixed(2)}</span></div>`).join('');

  // playback
  const scrub = $('scrub'); if (+scrub.value !== st.idx) scrub.value = st.idx;
  $('clock').textContent = fmtT(st.idx).slice(0, 8);
  $('play-state').textContent = st.playing ? st.speed + '× LIVE' : 'PAUSED';
  $('play').textContent = st.playing ? '❚❚' : '▶';
  document.querySelectorAll('#speeds .speed-btn').forEach((el) => el.classList.toggle('active', +el.dataset.speed === st.speed));

  draw();
}

// ── session loading ───────────────────────────────────────────────────────────
async function loadDate(date) {
  state.loading = true; hideError(); render();
  try {
    const sessions = await source.loadAll(date);
    state.sessions = sessions;
    state.date = date;
    state.idx = 0; state.playing = false; acc = 0;
    if (state.cash === null) state.cash = INITIAL_CASH;
    if (!sessions[state.ticker]) state.ticker = Object.keys(sessions)[0];
    state.loading = false;
    render();
  } catch (e) {
    state.loading = false;
    showError('Could not load session for ' + date + ':\n' + e.message);
  }
}
function showError(msg) {
  const el = $('chart-error'); el.textContent = msg; el.classList.remove('hidden');
  $('loading').classList.add('hidden');
}
function hideError() { $('chart-error').classList.add('hidden'); }

// ── playback loop ─────────────────────────────────────────────────────────────
function loop() {
  if (!state.playing || !state.sessions) return;
  acc += state.speed * 0.1;
  const step = Math.floor(acc);
  if (step < 1) return;
  acc -= step;
  const next = Math.min(state.idx + step, TICKS - 1);
  state.idx = next;
  state.playing = next < TICKS - 1 && state.playing;
  render();
}

// ── static UI construction + event wiring ─────────────────────────────────────
function buildStaticButtons() {
  const tabsEl = $('tabs'), ivEl = $('intervals'), spEl = $('speeds');
  tabsEl.innerHTML = ''; ivEl.innerHTML = ''; spEl.innerHTML = '';
  state.order.forEach((t) => {
    const el = document.createElement('div');
    el.className = 'tab'; el.dataset.ticker = t;
    el.innerHTML = `<div class="tab-sym">${t}</div><div class="tab-chg">—</div>`;
    el.onclick = () => { state.ticker = t; state.sel = -1; render(); };
    tabsEl.appendChild(el);
  });
  IVALS.forEach((iv) => {
    const b = document.createElement('button');
    b.className = 'ival-btn'; b.dataset.sec = iv.sec; b.textContent = iv.label;
    b.onclick = () => { state.ival = iv.sec; render(); };
    ivEl.appendChild(b);
  });
  SPEEDS.forEach((sp) => {
    const b = document.createElement('button');
    b.className = 'speed-btn'; b.dataset.speed = sp; b.textContent = sp + '×';
    b.onclick = () => { state.speed = sp; render(); };
    spEl.appendChild(b);
  });
}

function bindEvents() {
  $('date').addEventListener('change', (e) => { if (e.target.value) loadDate(e.target.value); });
  $('qty').addEventListener('input', (e) => { state.qty = Math.max(1, Math.round(+e.target.value || 1)); render(); });
  $('buy').addEventListener('click', () => applyFill('BUY', state.qty));
  $('sell').addEventListener('click', () => applyFill('SELL', state.qty));

  $('draw-btn').addEventListener('click', () => { state.drawMode = !state.drawMode; state.sel = -1; render(); });
  $('del-btn').addEventListener('click', () => { state.lines = state.lines.filter((_, i) => i !== state.sel); state.sel = -1; render(); });
  $('clear-btn').addEventListener('click', () => { state.lines = []; state.sel = -1; state.drawMode = false; render(); });

  canvas.addEventListener('mousedown', (e) => {
    const pt = px2data(e);
    if (!pt) return;
    if (state.drawMode) state.draft = { a: { sec: pt.sec, price: pt.price }, b: { sec: pt.sec, price: pt.price } };
    else state.sel = hitLine(pt);
    render();
  });
  canvas.addEventListener('mousemove', (e) => {
    if (!state.draft) return;
    const pt = px2data(e);
    if (pt) { state.draft = { a: state.draft.a, b: { sec: pt.sec, price: pt.price } }; render(); }
  });
  const finishLine = () => {
    const d = state.draft;
    if (!d) return;
    const moved = Math.abs(d.a.sec - d.b.sec) > 1 || Math.abs(d.a.price - d.b.price) > 0.01;
    const oldLen = state.lines.length;
    if (moved) { state.lines = [...state.lines, d]; state.sel = oldLen; } else state.sel = -1;
    state.draft = null; state.drawMode = false; render();
  };
  canvas.addEventListener('mouseup', finishLine);
  canvas.addEventListener('mouseleave', finishLine);

  $('jump-open').addEventListener('click', () => { state.idx = 0; state.playing = false; render(); });
  $('step-back').addEventListener('click', () => { state.idx = Math.max(0, state.idx - 1); state.playing = false; render(); });
  $('play').addEventListener('click', () => { state.playing = !state.playing; if (state.idx >= TICKS - 1) state.idx = 0; acc = 0; render(); });
  $('step-fwd').addEventListener('click', () => { state.idx = Math.min(TICKS - 1, state.idx + 1); state.playing = false; render(); });
  $('jump-close').addEventListener('click', () => { state.idx = TICKS - 1; state.playing = false; render(); });
  $('scrub').addEventListener('input', (e) => { state.idx = Math.max(0, Math.min(TICKS - 1, +e.target.value)); render(); });

  window.addEventListener('resize', render);
  window.addEventListener('keydown', (e) => {
    const typing = /INPUT|SELECT|TEXTAREA/.test(document.activeElement.tagName);
    if (typing) return;
    if ((e.key === 'Delete' || e.key === 'Backspace') && state.sel >= 0) {
      e.preventDefault();
      state.lines = state.lines.filter((_, i) => i !== state.sel); state.sel = -1; render();
    } else if (e.key === ' ') {
      e.preventDefault();
      state.playing = !state.playing; if (state.idx >= TICKS - 1) state.idx = 0; acc = 0; render();
    } else if (e.key === 'ArrowLeft') {
      e.preventDefault(); state.idx = Math.max(0, state.idx - 1); state.playing = false; render();
    } else if (e.key === 'ArrowRight') {
      e.preventDefault(); state.idx = Math.min(TICKS - 1, state.idx + 1); state.playing = false; render();
    }
  });
}

function mostRecentWeekday() {
  // Fallback default only; the real default comes from /api/dates when available.
  const d = new Date();
  let day = d.getDay();
  const back = day === 0 ? 2 : day === 6 ? 1 : (day === 1 ? 3 : 1); // skip to a prior weekday
  d.setDate(d.getDate() - back);
  return d.toISOString().slice(0, 10);
}

// ── boot ──────────────────────────────────────────────────────────────────────
async function init() {
  buildStaticButtons();
  bindEvents();
  try {
    const names = await source.tickers();
    state.names = names;
    state.order = Object.keys(names);
    if (!state.order.includes(state.ticker)) state.ticker = state.order[0];
    buildStaticButtons(); // rebuild tabs with the authoritative ticker list
  } catch (_) { /* keep defaults */ }

  const dates = await source.availableDates().catch(() => []);
  if (dates.length) state.date = dates[dates.length - 1];
  const dateEl = $('date');
  dateEl.value = state.date;
  dateEl.max = new Date().toISOString().slice(0, 10);

  render();
  await loadDate(state.date);
  setInterval(loop, 100);
}

init();
