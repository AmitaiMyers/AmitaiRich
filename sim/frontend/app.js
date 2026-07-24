// ROOF·SIM front-end — canvas day-trading sim with TWO data modes:
//   • stock  : real Yahoo 1m bars interpolated to seconds; order book synthesized.
//   • crypto : real Binance recordings — every value (price, volume, bid/ask, full
//              L2 depth, liquidity walls) is REAL. Branch on the loaded session.
// Features: candlestick+volume chart, order book, time & sales, positions/fills
// blotter, bracket/stop-loss (OCO) orders, trend-line tool, full playback.

import { hashStr, mulberry32 } from './rng.js';
import { createDataSource } from './data-source.js';
import { bollinger, obv, adx } from './indicators.js';

// Technical indicators (computed on candles at the selected interval). Params
// match the Yahoo settings requested: Bollinger(14,2), ADX(14). Toggle in the UI.
const BB_PERIOD = 14, BB_K = 2, ADX_PERIOD = 14;
const IND_WARMUP = BB_PERIOD + ADX_PERIOD + 6;   // extra candles built for indicator warmup

const DEFAULT_LEN = 23400;                 // stock session length (390 min × 60s)
const INITIAL_CASH = 100000;
const BOOK_DEPTH = 10;                      // synthetic (stock) book levels/side
const CRYPTO_BOOK_ROWS = 11;               // real (crypto) ladder rows/side shown
const EPS = 1e-9;
const IVALS = [
  { label: '5s', sec: 5 }, { label: '15s', sec: 15 }, { label: '1m', sec: 60 },
  { label: '5m', sec: 300 }, { label: '30m', sec: 1800 }, { label: '1h', sec: 3600 },
];
const SPEEDS = [1, 2, 5, 10, 30, 60];
const UP = '#16c784', DN = '#ea3943', NEUTRAL = '#8a97ab';

const state = {
  mode: 'stock', recid: null, recordings: [],
  idx: 0, playing: false, speed: 10, ival: 15, ticker: 'AAPL', date: mostRecentWeekday(),
  qty: 100, loading: true, cash: null, posMap: {}, fills: [], sessions: null,
  lines: [], drawMode: false, sel: -1, draft: null,
  orders: [], orderSeq: 0,
  ind: { bb: true, vol: true, adx: false, obv: false },   // enabled indicators
  order: ['AAPL', 'MSFT', 'NVDA', 'TSLA', 'SPY'], names: {},
};
const INDICATORS = [
  { key: 'bb', label: 'BB' }, { key: 'vol', label: 'VOL' },
  { key: 'adx', label: 'ADX' }, { key: 'obv', label: 'OBV' },
];

const source = createDataSource();
let view = null;
let acc = 0;
let clockBase = 9.5 * 3600;   // seconds-of-day the session clock starts at

const $ = (id) => document.getElementById(id);
const canvas = $('chart');

// ── mode / session helpers ────────────────────────────────────────────────────
function isCrypto() { return state.mode === 'crypto'; }
function activeSess() { return state.sessions ? state.sessions[state.ticker] : null; }
function LEN() { const s = activeSess(); return s && s.prices ? s.prices.length : DEFAULT_LEN; }

// ── formatting ────────────────────────────────────────────────────────────────
function pad2(n) { return String(n).padStart(2, '0'); }
function fmtT(i) {
  const t = (clockBase + i) % 86400, h = Math.floor(t / 3600), m = Math.floor((t % 3600) / 60), s = t % 60;
  return pad2(h) + ':' + pad2(m) + ':' + pad2(s);
}
function fmt$(v) {
  return (v < 0 ? '-$' : '$') + Math.abs(v).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}
function fmtPnl(v) {
  return (v >= 0 ? '+' : '-') + '$' + Math.abs(v).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}
function pnlColor(v) { return v > 0.005 ? UP : v < -0.005 ? DN : NEUTRAL; }
function round2(v) { return Math.round(v * 100) / 100; }
// instrument price: decimals scale with magnitude (BTC 2dp, SOL 3dp, XRP 5dp)
function fmtPx(p) { const a = Math.abs(p); return p.toFixed(a >= 100 ? 2 : a >= 1 ? 3 : 5); }
// order quantity: shares (int) for stock, fractional for crypto
function fmtQty(q) {
  if (!isCrypto()) return String(Math.round(q));
  const a = Math.abs(q);
  return q.toFixed(a >= 1 ? 3 : a >= 0.01 ? 4 : 6);
}
// volume / book size
function fmtVol(v) {
  if (isCrypto()) { const a = Math.abs(v); return a >= 1000 ? (v / 1000).toFixed(1) + 'K' : a >= 1 ? v.toFixed(2) : v.toFixed(4); }
  return v >= 1000 ? (v / 1000).toFixed(v >= 10000 ? 0 : 1) + 'K' : String(Math.round(v));
}

// ── market data helpers ───────────────────────────────────────────────────────
function priceAt(t, i) {
  const s = state.sessions;
  if (!s || !s[t]) return 0;
  const n = s[t].prices.length;
  return s[t].prices[Math.max(0, Math.min(i, n - 1))];
}
function quote(t, i) {
  const s = state.sessions;
  if (!s || !s[t]) return { bid: 0, ask: 0, spread: 0, mid: 0 };
  if (isCrypto() && s[t].bid) {
    const sess = s[t], j = Math.max(0, Math.min(i, sess.prices.length - 1));
    const bid = sess.bid[j], ask = sess.ask[j];
    return { bid, ask, spread: round2(ask - bid), mid: sess.prices[j] };
  }
  const p = priceAt(t, i);
  const spread = Math.max(0.01, Math.round(p * 0.00008 * 100) / 100);
  const bid = Math.round((p - spread / 2) * 100) / 100;
  return { bid, ask: Math.round((bid + spread) * 100) / 100, spread, mid: p };
}
// Synthetic order book (STOCK only — Yahoo has no Level-2).
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
function stockBookLevels(side) {
  const raw = rawBook(side);
  const maxS = Math.max(1, ...raw.map((l) => l.size));
  return raw.map((l) => ({ price: fmtPx(l.price), size: l.size.toLocaleString(), pct: Math.round((l.size / maxS) * 88) }));
}
// Real order book (CRYPTO): read the recorded L2 snapshot at this second.
function cryptoBookSnap(idx) {
  const sess = activeSess();
  const j = Math.max(0, Math.min(idx, sess.book.length - 1));
  return sess.book[j];
}
function cryptoBookLevels(side, rows) {
  const snap = cryptoBookSnap(state.idx);
  const raw = (side === 'ask' ? snap.a : snap.b).slice(0, rows);
  const maxS = Math.max(EPS, ...raw.map((l) => l[1]));
  return raw.map((l) => ({ price: fmtPx(l[0]), size: fmtVol(l[1]), pct: Math.round((l[1] / maxS) * 88) }));
}
// Synthetic resting liquidity (STOCK only).
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

// ── trading ───────────────────────────────────────────────────────────────────
function bookTrade(sym, side, qty, price, idx, tag) {
  const posMap = state.posMap;
  const dir = side === 'BUY' ? 1 : -1;
  const pos = posMap[sym] || { qty: 0, avg: 0, realized: 0 };
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
  state.posMap = { ...posMap, [sym]: { qty: q0, avg, realized } };
  state.fills = [{ time: fmtT(idx), side, sym, qty, price, tag: tag || null }, ...state.fills].slice(0, 40);
}

function applyFill(side, qty) {
  const { ticker, idx, sessions } = state;
  if (!sessions || qty <= EPS) return;
  const q = quote(ticker, idx);
  const price = side === 'BUY' ? q.ask : q.bid;
  bookTrade(ticker, side, qty, price, idx, null);
  syncOrders(ticker);
  render();
}

// ── bracket / stop-loss engine (works in both modes) ──────────────────────────
function suggestedLevels(ticker, idx, long) {
  const last = priceAt(ticker, idx);
  return long
    ? { stop: round2(last * 0.99), target: round2(last * 1.02) }
    : { stop: round2(last * 1.01), target: round2(last * 0.98) };
}
function syncOrders(sym) {
  const pos = state.posMap[sym];
  const held = pos ? pos.qty : 0;
  state.orders = state.orders.filter((o) => {
    if (o.sym !== sym) return true;
    const valid = (o.side === 'SELL' && held > EPS) || (o.side === 'BUY' && held < -EPS);
    if (!valid) return false;
    o.qty = Math.min(o.qty, Math.abs(held));
    return o.qty > EPS;
  });
}
function fireOrder(o, idx) {
  const pos = state.posMap[o.sym];
  const held = pos ? pos.qty : 0;
  const exitQty = Math.min(o.qty, Math.abs(held));
  state.orders = state.orders.filter((x) => x.group !== o.group);
  if (exitQty > EPS) bookTrade(o.sym, o.side, exitQty, o.level, idx, o.tag);
  syncOrders(o.sym);
}
function scanTriggers(fromSec, toSec) {
  const s = state.sessions;
  for (let i = fromSec; i <= toSec; i++) {
    if (!state.orders.length) break;
    const firing = state.orders.filter((o) => {
      const arr = s[o.sym].prices, p = arr[Math.min(i, arr.length - 1)];
      return o.dir > 0 ? p >= o.level : p <= o.level;
    });
    for (const o of firing) if (state.orders.includes(o)) fireOrder(o, i);
  }
}
function advanceTo(newIdx, allowTriggers) {
  const max = LEN() - 1;
  newIdx = Math.max(0, Math.min(max, newIdx));
  const oldIdx = state.idx;
  if (allowTriggers && newIdx > oldIdx && state.sessions && state.orders.length) scanTriggers(oldIdx + 1, newIdx);
  state.idx = newIdx;
}
function attachBracket() {
  const { ticker, idx, sessions } = state;
  const hint = $('bracket-hint');
  if (!sessions) return;
  const pos = state.posMap[ticker];
  if (!pos || Math.abs(pos.qty) <= EPS) {
    hint.textContent = 'No position in ' + ticker + ' to protect.'; hint.className = 'bracket-hint err'; return;
  }
  const long = pos.qty > 0, last = priceAt(ticker, idx), sug = suggestedLevels(ticker, idx, long);
  const stopRaw = $('stop-price').value.trim(), tgtRaw = $('target-price').value.trim();
  let stop = stopRaw ? parseFloat(stopRaw) : null;
  let tgt = tgtRaw ? parseFloat(tgtRaw) : null;
  if (stop === null && tgt === null) { stop = sug.stop; tgt = sug.target; }
  const errs = [];
  if (stop !== null) {
    if (isNaN(stop)) errs.push('stop is not a number');
    else if (long && stop >= last) errs.push('long stop must be below ' + fmtPx(last));
    else if (!long && stop <= last) errs.push('short stop must be above ' + fmtPx(last));
  }
  if (tgt !== null) {
    if (isNaN(tgt)) errs.push('target is not a number');
    else if (long && tgt <= last) errs.push('long target must be above ' + fmtPx(last));
    else if (!long && tgt >= last) errs.push('short target must be below ' + fmtPx(last));
  }
  if (errs.length) { hint.textContent = errs.join('; '); hint.className = 'bracket-hint err'; return; }
  const side = long ? 'SELL' : 'BUY', group = ++state.orderSeq, qty = Math.abs(pos.qty);
  state.orders = state.orders.filter((o) => o.sym !== ticker);
  if (stop !== null) state.orders.push({ id: ++state.orderSeq, sym: ticker, kind: 'STOP', tag: 'STP', side, dir: long ? -1 : 1, level: stop, qty, group });
  if (tgt !== null) state.orders.push({ id: ++state.orderSeq, sym: ticker, kind: 'TARGET', tag: 'TGT', side, dir: long ? 1 : -1, level: tgt, qty, group });
  hint.textContent = 'Attached: ' + [stop !== null ? 'stop ' + fmtPx(stop) : null, tgt !== null ? 'target ' + fmtPx(tgt) : null].filter(Boolean).join(' / ');
  hint.className = 'bracket-hint ok';
  $('stop-price').value = ''; $('target-price').value = '';
  render();
}

// ── canvas drawing ────────────────────────────────────────────────────────────
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
  const cw = W - axW;
  const cs = state.ival, idx = state.idx, N_TICKS = LEN();
  const endC = Math.floor(idx / cs);
  const N = Math.max(10, Math.min(Math.max(30, Math.floor(cw / 9)), Math.ceil(N_TICKS / cs)));
  const startC = endC - N + 1;
  // lower indicator panels (VOL/ADX/OBV) shrink the price panel; BB is an overlay
  const lowers = [];
  if (state.ind.vol) lowers.push('VOL');
  if (state.ind.adx) lowers.push('ADX');
  if (state.ind.obv) lowers.push('OBV');
  const availH = H - timeH;
  const priceH = availH * (1 - Math.min(0.5, 0.17 * lowers.length));
  const stripH = lowers.length ? (availH - priceH) / lowers.length : 0;
  // build candles WITH warmup (extra left candles) so indicators aren't blank at the edge
  const firstC = Math.max(0, startC - IND_WARMUP);
  const candles = [];
  for (let c = firstC; c <= endC; c++) {
    const a = c * cs, b = Math.min(idx, a + cs - 1);
    let o = sess.prices[a], cl = sess.prices[b], h2 = -Infinity, l2 = Infinity, v = 0;
    for (let i = a; i <= b; i++) { const p = sess.prices[i]; if (p > h2) h2 = p; if (p < l2) l2 = p; v += sess.vols[i]; }
    candles.push({ c, o, c2: cl, h: h2, l: l2, v });
  }
  if (!candles.length) return;
  // price scale over the VISIBLE candles only (warmup candles excluded)
  let lo = Infinity, hi = -Infinity, maxV = 1;
  for (const cd of candles) if (cd.c >= startC) { if (cd.l < lo) lo = cd.l; if (cd.h > hi) hi = cd.h; if (cd.v > maxV) maxV = cd.v; }
  if (!isFinite(lo)) { const cd = candles[candles.length - 1]; lo = cd.l; hi = cd.h; }
  const pad = (hi - lo) * 0.08 + 0.01; lo -= pad; hi += pad;
  const y = (p) => priceH - ((p - lo) / (hi - lo)) * priceH;
  const x = (c) => cw - (endC - c + 0.5) * (cw / N);
  const bw = Math.max(2, (cw / N) * 0.62);
  ctx.strokeStyle = '#151c2a'; ctx.fillStyle = '#5a6a80'; ctx.font = '10px "IBM Plex Mono",monospace'; ctx.textBaseline = 'middle';
  for (let g = 0; g <= 5; g++) {
    const p = lo + ((hi - lo) * g) / 5, yy = y(p);
    ctx.beginPath(); ctx.moveTo(0, yy); ctx.lineTo(cw, yy); ctx.stroke();
    ctx.fillText(fmtPx(p), cw + 6, yy);
  }
  ctx.textAlign = 'center';
  const every = Math.ceil(N / 7);
  candles.forEach((cd) => {
    if (cd.c >= startC && (cd.c % every) === 0) { ctx.fillStyle = '#5a6a80'; ctx.fillText(fmtT(cd.c * cs).slice(0, 5), x(cd.c), H - timeH / 2); }
  });
  ctx.textAlign = 'left';
  // volume profile
  const bins = 36, binC = new Float64Array(bins);
  for (let i = 0; i <= idx; i += 5) {
    const p = sess.prices[i];
    if (p >= lo && p <= hi) binC[Math.min(bins - 1, Math.floor(((p - lo) / (hi - lo)) * bins))] += sess.vols[i];
  }
  const mb = Math.max(...binC, 1);
  ctx.fillStyle = 'rgba(240,180,41,0.07)';
  for (let b = 0; b < bins; b++) { const w2 = (binC[b] / mb) * profW; ctx.fillRect(cw - w2, priceH - ((b + 1) / bins) * priceH, w2, priceH / bins - 1); }
  // candles (clipped to the price panel; volume now lives in its own strip)
  ctx.save(); ctx.beginPath(); ctx.rect(0, 0, cw, priceH); ctx.clip();
  candles.forEach((cd) => {
    if (cd.c < startC) return;
    const col = cd.c2 >= cd.o ? UP : DN, xx = x(cd.c);
    ctx.strokeStyle = col; ctx.fillStyle = col;
    ctx.beginPath(); ctx.moveTo(xx, y(cd.h)); ctx.lineTo(xx, y(cd.l)); ctx.stroke();
    const yo = y(cd.o), yc = y(cd.c2);
    ctx.fillRect(xx - bw / 2, Math.min(yo, yc), bw, Math.max(1, Math.abs(yc - yo)));
  });
  ctx.restore();
  if (state.ind.bb) drawBollinger(ctx, candles, startC, x, y, cw, priceH);
  const last = sess.prices[idx];
  if (sess.prevClose >= lo && sess.prevClose <= hi) {
    ctx.strokeStyle = '#3d4a5e'; ctx.setLineDash([2, 4]);
    ctx.beginPath(); ctx.moveTo(0, y(sess.prevClose)); ctx.lineTo(cw, y(sess.prevClose)); ctx.stroke(); ctx.setLineDash([]);
  }
  // resting liquidity walls
  drawWalls(ctx, sess, idx, lo, hi, cw, last, y);
  // last-price line + tag
  ctx.textAlign = 'left'; ctx.font = '10px "IBM Plex Mono",monospace';
  const lc = last >= sess.prevClose ? UP : DN;
  ctx.strokeStyle = lc; ctx.setLineDash([4, 3]); ctx.beginPath(); ctx.moveTo(0, y(last)); ctx.lineTo(cw, y(last)); ctx.stroke(); ctx.setLineDash([]);
  ctx.fillStyle = lc; ctx.fillRect(cw, y(last) - 8, axW, 16);
  ctx.fillStyle = '#0a0e14'; ctx.fillText(fmtPx(last), cw + 6, y(last));
  // working stop/target levels (active ticker)
  ctx.font = '9px "IBM Plex Mono",monospace'; ctx.textAlign = 'left';
  state.orders.forEach((o) => {
    if (o.sym !== state.ticker || o.level < lo || o.level > hi) return;
    const col = o.kind === 'STOP' ? DN : UP, yy = y(o.level);
    ctx.strokeStyle = col; ctx.setLineDash([6, 4]); ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(0, yy); ctx.lineTo(cw, yy); ctx.stroke(); ctx.setLineDash([]);
    ctx.fillStyle = col; ctx.fillText(o.kind + ' ' + fmtPx(o.level), 4, yy - 4);
  });
  ctx.font = '10px "IBM Plex Mono",monospace';
  // save transform, draw user trend lines
  view = { lo, hi, priceH, cw, N, endC, cs };
  const lx = (sec) => cw - (endC - sec / cs + 0.5) * (cw / N);
  ctx.save(); ctx.beginPath(); ctx.rect(0, 0, cw, priceH); ctx.clip();
  const drawLine = (ln, seld) => {
    const x1 = lx(ln.a.sec), y1 = y(ln.a.price), x2 = lx(ln.b.sec), y2 = y(ln.b.price);
    ctx.strokeStyle = seld ? '#ffd166' : '#f0b429'; ctx.lineWidth = seld ? 2 : 1.25;
    ctx.beginPath(); ctx.moveTo(x1, y1); ctx.lineTo(x2, y2); ctx.stroke();
    if (seld) { ctx.fillStyle = '#ffd166'; [[x1, y1], [x2, y2]].forEach(([px, py]) => { ctx.beginPath(); ctx.arc(px, py, 4, 0, 7); ctx.fill(); }); }
    ctx.lineWidth = 1;
  };
  state.lines.forEach((ln, i) => drawLine(ln, i === state.sel));
  if (state.draft) drawLine(state.draft, true);
  ctx.restore();
  // fill markers
  state.fills.forEach((f) => {
    if (f.sym !== state.ticker) return;
    const sec = f.time.split(':').reduce((a2, b2) => a2 * 60 + +b2, 0) - clockBase;
    const c = Math.floor(sec / cs);
    if (c < Math.max(0, startC) || c > endC) return;
    ctx.fillStyle = f.side === 'BUY' ? UP : DN;
    const yy = y(f.price), xx = x(c);
    ctx.beginPath();
    if (f.side === 'BUY') { ctx.moveTo(xx, yy + 14); ctx.lineTo(xx - 5, yy + 22); ctx.lineTo(xx + 5, yy + 22); }
    else { ctx.moveTo(xx, yy - 14); ctx.lineTo(xx - 5, yy - 22); ctx.lineTo(xx + 5, yy - 22); }
    ctx.fill();
  });
  // lower indicator strips (VOL / ADX / OBV)
  drawLowerPanels(ctx, candles, startC, x, cw, priceH, stripH, lowers, maxV, bw);
}

// ── indicator rendering ───────────────────────────────────────────────────────
function lastNonNull(arr) { for (let i = arr.length - 1; i >= 0; i--) if (arr[i] != null) return arr[i]; return null; }
function plotSeries(ctx, candles, startC, arr, xf, yf, color, w) {
  ctx.strokeStyle = color; ctx.lineWidth = w; ctx.beginPath();
  let started = false;
  for (let i = 0; i < candles.length; i++) {
    if (candles[i].c < startC) continue;
    const v = arr[i];
    if (v == null) { started = false; continue; }
    const px = xf(candles[i].c), py = yf(v);
    if (!started) { ctx.moveTo(px, py); started = true; } else ctx.lineTo(px, py);
  }
  ctx.stroke(); ctx.lineWidth = 1;
}

// Bollinger Bands overlay on the price panel.
function drawBollinger(ctx, candles, startC, x, y, cw, priceH) {
  const closes = candles.map((c) => c.c2);
  const bb = bollinger(closes, BB_PERIOD, BB_K);
  ctx.save(); ctx.beginPath(); ctx.rect(0, 0, cw, priceH); ctx.clip();
  plotSeries(ctx, candles, startC, bb.up, x, y, 'rgba(79,140,255,0.85)', 1);
  plotSeries(ctx, candles, startC, bb.lo, x, y, 'rgba(79,140,255,0.85)', 1);
  plotSeries(ctx, candles, startC, bb.mid, x, y, 'rgba(79,140,255,0.5)', 1);
  ctx.restore();
  ctx.fillStyle = '#4f8cff'; ctx.font = '9px "IBM Plex Mono",monospace'; ctx.textAlign = 'left'; ctx.textBaseline = 'top';
  ctx.fillText(`BB ${BB_PERIOD},${BB_K}`, 4, 4);
  ctx.textBaseline = 'middle'; ctx.font = '10px "IBM Plex Mono",monospace';
}

function drawLowerPanels(ctx, candles, startC, x, cw, priceH, stripH, lowers, maxV, bw) {
  if (!lowers.length) return;
  const closes = candles.map((c) => c.c2), highs = candles.map((c) => c.h), lows = candles.map((c) => c.l), vols = candles.map((c) => c.v);
  const A = state.ind.adx ? adx(highs, lows, closes, ADX_PERIOD) : null;
  const O = state.ind.obv ? obv(closes, vols) : null;
  ctx.textBaseline = 'top';
  lowers.forEach((name, k) => {
    const top = priceH + k * stripH, h = stripH;
    ctx.strokeStyle = '#232d3d'; ctx.beginPath(); ctx.moveTo(0, top); ctx.lineTo(cw, top); ctx.stroke();
    if (name === 'VOL') drawVolStrip(ctx, candles, startC, x, top, h, bw, maxV);
    else if (name === 'ADX') drawIndStrip(ctx, candles, startC, A.adx, x, top, h, '#f0b429', 'ADX ' + ADX_PERIOD, 40, 25);
    else if (name === 'OBV') drawIndStrip(ctx, candles, startC, O, x, top, h, '#4f8cff', 'OBV', null, null);
  });
  ctx.textBaseline = 'middle';
}

function drawVolStrip(ctx, candles, startC, x, top, h, bw, maxV) {
  ctx.save(); ctx.beginPath(); ctx.rect(0, top, 1e5, h); ctx.clip();
  for (const cd of candles) {
    if (cd.c < startC) continue;
    const bh = (cd.v / maxV) * (h - 5), col = cd.c2 >= cd.o ? UP : DN;
    ctx.globalAlpha = 0.55; ctx.fillStyle = col; ctx.fillRect(x(cd.c) - bw / 2, top + h - bh, bw, bh); ctx.globalAlpha = 1;
  }
  ctx.restore();
  ctx.fillStyle = '#5a6a80'; ctx.font = '9px "IBM Plex Mono",monospace'; ctx.textAlign = 'left'; ctx.fillText('VOL', 4, top + 3);
  ctx.font = '10px "IBM Plex Mono",monospace';
}

// Generic line strip for ADX/OBV. `fixedMax` fixes the top of scale; `thresh`
// draws a dashed reference line (e.g. ADX 25). Auto-scales otherwise.
function drawIndStrip(ctx, candles, startC, arr, x, top, h, color, label, fixedMax, thresh) {
  let mn = Infinity, mx = -Infinity;
  for (let i = 0; i < candles.length; i++) if (candles[i].c >= startC && arr[i] != null) { if (arr[i] < mn) mn = arr[i]; if (arr[i] > mx) mx = arr[i]; }
  if (!isFinite(mn)) { mn = 0; mx = 1; }
  if (fixedMax != null) { mn = 0; mx = Math.max(fixedMax, mx); }
  if (mx === mn) mx = mn + 1;
  const yv = (v) => top + h - ((v - mn) / (mx - mn)) * (h - 6) - 3;
  ctx.save(); ctx.beginPath(); ctx.rect(0, top, 1e5, h); ctx.clip();
  if (thresh != null) { ctx.strokeStyle = '#232d3d'; ctx.setLineDash([2, 3]); ctx.beginPath(); ctx.moveTo(0, yv(thresh)); ctx.lineTo(1e5, yv(thresh)); ctx.stroke(); ctx.setLineDash([]); }
  plotSeries(ctx, candles, startC, arr, x, yv, color, 1.25);
  ctx.restore();
  const cur = lastNonNull(arr);
  ctx.fillStyle = '#5a6a80'; ctx.font = '9px "IBM Plex Mono",monospace'; ctx.textAlign = 'left';
  ctx.fillText(label + (cur != null ? '  ' + (Math.abs(cur) >= 1000 ? fmtVol(cur) : cur.toFixed(1)) : ''), 4, top + 3);
  ctx.font = '10px "IBM Plex Mono",monospace';
}

// resting-liquidity walls: REAL recorded L2 depth for crypto, synthetic for stock
function drawWalls(ctx, sess, idx, lo, hi, cw, last, y) {
  ctx.textAlign = 'right';
  if (isCrypto()) {
    if (!sess.book) { ctx.textAlign = 'left'; return; }
    const snap = sess.book[Math.min(idx, sess.book.length - 1)];
    const levels = [];
    for (const [p, q] of snap.b) if (p >= lo && p <= hi) levels.push({ p, size: q, bid: true });
    for (const [p, q] of snap.a) if (p >= lo && p <= hi) levels.push({ p, size: q, bid: false });
    const maxLvl = Math.max(EPS, ...levels.map((l) => l.size));
    ctx.font = '9px "IBM Plex Mono",monospace';
    for (const l of levels) {
      const col = l.bid ? UP : DN, yy = y(l.p), bw2 = 4 + (l.size / maxLvl) * 54, wall = l.size > maxLvl * 0.5;
      if (wall) { ctx.globalAlpha = 0.13; ctx.strokeStyle = col; ctx.beginPath(); ctx.moveTo(0, yy); ctx.lineTo(cw, yy); ctx.stroke(); }
      ctx.globalAlpha = wall ? 0.5 : 0.26; ctx.fillStyle = col; ctx.fillRect(cw - bw2, yy - 2, bw2, 4);
      ctx.globalAlpha = 1;
    }
    ctx.font = '10px "IBM Plex Mono",monospace'; ctx.textAlign = 'left';
    return;
  }
  // stock: synthetic S/R walls across the visible range
  ctx.font = '9px "IBM Plex Mono",monospace';
  const rawStep = (hi - lo) / 26, mag = Math.pow(10, Math.floor(Math.log10(rawStep)));
  const lvlStep = [1, 2, 5, 10].map((m) => m * mag).find((s2) => s2 >= rawStep) || 10 * mag;
  const levels = [];
  for (let p = Math.ceil(lo / lvlStep) * lvlStep; p <= hi; p += lvlStep) levels.push({ p, size: levelSize(p, idx) });
  const maxLvl = Math.max(1, ...levels.map((l) => l.size));
  for (const l of levels) {
    const sell = l.p >= last, col = sell ? DN : UP, yy = y(l.p), bw2 = 5 + (l.size / maxLvl) * 52, wall = l.size > maxLvl * 0.55;
    if (wall) { ctx.globalAlpha = 0.14; ctx.strokeStyle = col; ctx.beginPath(); ctx.moveTo(0, yy); ctx.lineTo(cw, yy); ctx.stroke(); }
    ctx.globalAlpha = wall ? 0.42 : 0.24; ctx.fillStyle = col; ctx.fillRect(cw - bw2, yy - 2.5, bw2, 5);
    ctx.globalAlpha = wall ? 1 : 0.75; ctx.fillText(fmtSizeStock(l.size), cw - bw2 - 4, yy); ctx.globalAlpha = 1;
  }
  ctx.font = '10px "IBM Plex Mono",monospace'; ctx.textAlign = 'left';
}
function fmtSizeStock(v) { return v >= 1000 ? (v / 1000).toFixed(v >= 10000 ? 0 : 1) + 'K' : String(v); }

// ── mouse → data mapping ──────────────────────────────────────────────────────
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

  // header mode toggle + pickers
  $('mode-stock').classList.toggle('active', !isCrypto());
  $('mode-crypto').classList.toggle('active', isCrypto());
  $('date').classList.toggle('hidden', isCrypto());
  $('recording').classList.toggle('hidden', !isCrypto());

  document.querySelectorAll('#tabs .tab').forEach((el) => {
    const t = el.dataset.ticker;
    el.classList.toggle('active', t === st.ticker);
    const chgEl = el.querySelector('.tab-chg');
    if (s && s[t]) {
      const p = priceAt(t, st.idx), pc = s[t].prevClose, d = ((p - pc) / pc) * 100;
      chgEl.textContent = (d >= 0 ? '+' : '') + d.toFixed(2) + '%'; chgEl.style.color = pnlColor(d);
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
      if (Math.abs(pos.qty) > EPS || Math.abs(pos.realized) > 0.004) posRows.push({
        sym: t, qty: fmtQty(pos.qty), qtyColor: pos.qty > EPS ? UP : pos.qty < -EPS ? DN : NEUTRAL,
        avg: Math.abs(pos.qty) > EPS ? fmtPx(pos.avg) : '—', last: fmtPx(lp),
        upnl: Math.abs(pos.qty) > EPS ? fmtPnl(upnl) : '—', upnlColor: pnlColor(Math.abs(pos.qty) > EPS ? upnl : 0),
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
  const lastEl = $('last'); lastEl.textContent = last ? fmtPx(last) : '—'; lastEl.style.color = pnlColor(chgAbs);
  const lchg = $('last-chg');
  lchg.textContent = sess ? (chgAbs >= 0 ? '+' : '') + fmtPx(chgAbs) + ' (' + (chgP >= 0 ? '+' : '') + chgP.toFixed(2) + '%)' : '';
  lchg.style.color = pnlColor(chgAbs);
  document.querySelectorAll('#intervals .ival-btn').forEach((el) => el.classList.toggle('active', +el.dataset.sec === st.ival));
  document.querySelectorAll('#ind-toggles .ind-btn').forEach((el) => el.classList.toggle('active', !!st.ind[el.dataset.ind]));
  $('draw-btn').classList.toggle('active', st.drawMode);
  $('del-btn').classList.toggle('hidden', st.sel < 0);
  $('clear-btn').classList.toggle('hidden', st.lines.length === 0);
  $('loading').classList.toggle('hidden', !st.loading);
  canvas.style.cursor = st.drawMode ? 'crosshair' : 'default';

  // order book (real for crypto, synthetic for stock). Guard the transient where
  // mode is crypto but sessions aren't the crypto sessions yet (still loading).
  $('spread').textContent = 'SPRD ' + fmtPx(q.spread);
  const bookOk = sess && (!isCrypto() || sess.book);
  const asks = bookOk ? (isCrypto() ? cryptoBookLevels('ask', CRYPTO_BOOK_ROWS) : stockBookLevels('ask')) : [];
  const bids = bookOk ? (isCrypto() ? cryptoBookLevels('bid', CRYPTO_BOOK_ROWS) : stockBookLevels('bid')) : [];
  $('asks').innerHTML = asks.reverse().map((a) =>
    `<div class="book-row ask"><div class="book-bar ask" style="width:${a.pct}%"></div><span class="price">${a.price}</span><span class="size">${a.size}</span></div>`).join('');
  $('bids').innerHTML = bids.map((b) =>
    `<div class="book-row bid"><div class="book-bar bid" style="width:${b.pct}%"></div><span class="price">${b.price}</span><span class="size">${b.size}</span></div>`).join('');
  $('bid').textContent = fmtPx(q.bid);
  $('ask').textContent = fmtPx(q.ask);

  // order entry
  $('notional').textContent = '≈ ' + fmt$(st.qty * q.mid);
  $('buy').textContent = 'BUY ' + fmtPx(q.ask);
  $('sell').textContent = 'SELL ' + fmtPx(q.bid);

  // bracket placeholders + working orders
  const posActive = s ? st.posMap[st.ticker] : null;
  if (posActive && Math.abs(posActive.qty) > EPS) {
    const sug = suggestedLevels(st.ticker, st.idx, posActive.qty > 0);
    $('stop-price').placeholder = fmtPx(sug.stop); $('target-price').placeholder = fmtPx(sug.target);
  } else { $('stop-price').placeholder = '—'; $('target-price').placeholder = '—'; }
  const wo = st.orders.filter((o) => o.sym === st.ticker);
  $('working').innerHTML = wo.length
    ? '<div class="wo-head">WORKING ORDERS</div>' + wo.map((o) =>
        `<div class="wo-row"><span class="wo-kind" style="color:${o.kind === 'STOP' ? DN : UP}">${o.kind}</span><span class="wo-level">${fmtPx(o.level)}</span><span class="wo-qty">×${fmtQty(o.qty)}</span><button class="wo-cancel" data-id="${o.id}" title="Cancel order">✕</button></div>`).join('')
    : '';

  // tape
  const tape = [];
  if (sess) {
    for (let i = st.idx; i >= Math.max(0, st.idx - 25); i--) {
      const p = sess.prices[i], prev = sess.prices[Math.max(0, i - 1)];
      tape.push(`<div class="tape-row"><span class="t">${fmtT(i)}</span><span class="p" style="color:${p > prev ? UP : p < prev ? DN : NEUTRAL}">${fmtPx(p)}</span><span class="s">${fmtVol(sess.vols[i])}</span></div>`);
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
    `<div class="fill-row"><span class="t">${f.time}</span><span class="side" style="color:${f.side === 'BUY' ? UP : DN}">${f.side}${f.tag ? '·' + f.tag : ''}</span><span class="sym">${f.sym}</span><span class="qty">${fmtQty(f.qty)}</span><span class="price">${fmtPx(f.price)}</span></div>`).join('');

  // playback
  const scrub = $('scrub'); const max = LEN() - 1;
  if (+scrub.max !== max) scrub.max = max;
  if (+scrub.value !== st.idx) scrub.value = st.idx;
  $('time-start').textContent = fmtT(0).slice(0, 5);
  $('time-end').textContent = fmtT(max).slice(0, 5);
  $('clock').textContent = fmtT(st.idx).slice(0, 8);
  $('play-state').textContent = st.playing ? st.speed + '× LIVE' : 'PAUSED';
  $('play').textContent = st.playing ? '❚❚' : '▶';
  document.querySelectorAll('#speeds .speed-btn').forEach((el) => el.classList.toggle('active', +el.dataset.speed === st.speed));

  draw();
}

// ── session loading ───────────────────────────────────────────────────────────
function setClockBase() {
  const sess = activeSess();
  if (isCrypto() && sess && sess.start) {
    const d = new Date(sess.start);
    clockBase = d.getUTCHours() * 3600 + d.getUTCMinutes() * 60 + d.getUTCSeconds();
  } else clockBase = 9.5 * 3600;
}
function setQtyInputMode() {
  const q = $('qty');
  if (isCrypto()) { q.step = '0.001'; q.min = '0'; } else { q.step = '10'; q.min = '1'; }
  q.value = String(state.qty);
}
function buildTabs() {
  const el = $('tabs'); el.innerHTML = '';
  state.order.forEach((t) => {
    const d = document.createElement('div');
    d.className = 'tab'; d.dataset.ticker = t;
    d.innerHTML = `<div class="tab-sym">${t}</div><div class="tab-chg">—</div>`;
    d.onclick = () => { state.ticker = t; state.sel = -1; render(); };
    el.appendChild(d);
  });
}

async function loadDate(date) {
  state.loading = true; hideError(); render();
  try {
    const sessions = await source.loadAll(date);
    state.sessions = sessions; state.mode = 'stock'; state.date = date;
    state.order = Object.keys(sessions);
    state.idx = 0; state.playing = false; acc = 0; state.orders = [];
    if (state.cash === null) state.cash = INITIAL_CASH;
    if (!sessions[state.ticker]) state.ticker = state.order[0];
    state.qty = 100;
    setClockBase(); setQtyInputMode(); buildTabs();
    state.loading = false; render();
  } catch (e) { state.loading = false; showError('Could not load session for ' + date + ':\n' + e.message); }
}

async function loadRecording(recid) {
  state.loading = true; hideError(); render();
  try {
    const { sessions } = await source.loadCryptoRecording(recid);
    state.sessions = sessions; state.mode = 'crypto'; state.recid = recid;
    state.order = Object.keys(sessions);
    state.idx = 0; state.playing = false; acc = 0; state.orders = [];
    if (state.cash === null) state.cash = INITIAL_CASH;
    if (!sessions[state.ticker]) state.ticker = state.order[0];
    state.qty = 0.01;
    setClockBase(); setQtyInputMode(); buildTabs();
    state.loading = false; render();
  } catch (e) { state.loading = false; showError('Could not load recording ' + recid + ':\n' + e.message); }
}

function showError(msg) { const el = $('chart-error'); el.textContent = msg; el.classList.remove('hidden'); $('loading').classList.add('hidden'); }
function hideError() { $('chart-error').classList.add('hidden'); }

// ── playback loop ─────────────────────────────────────────────────────────────
function loop() {
  if (!state.playing || !state.sessions) return;
  acc += state.speed * 0.1;
  const step = Math.floor(acc);
  if (step < 1) return;
  acc -= step;
  const max = LEN() - 1, next = Math.min(state.idx + step, max);
  advanceTo(next, true);
  state.playing = next < max && state.playing;
  render();
}

// ── static UI + events ────────────────────────────────────────────────────────
function buildTransportButtons() {
  const indEl = $('ind-toggles');
  indEl.innerHTML = '';
  INDICATORS.forEach((ind) => {
    const b = document.createElement('button');
    b.className = 'ind-btn'; b.dataset.ind = ind.key; b.textContent = ind.label;
    b.title = 'Toggle ' + ind.label;
    b.onclick = () => { state.ind[ind.key] = !state.ind[ind.key]; render(); };
    indEl.appendChild(b);
  });
  const ivEl = $('intervals'), spEl = $('speeds');
  ivEl.innerHTML = ''; spEl.innerHTML = '';
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

function populateRecordings() {
  const sel = $('recording');
  sel.innerHTML = state.recordings.map((r) =>
    `<option value="${r.recid}">${r.symbols.length} sym · ${Math.round((r.length || 0) / 60)}m · ${r.recid}</option>`).join('');
  if (state.recid) sel.value = state.recid;
}

async function switchMode(mode) {
  if (mode === state.mode && state.sessions) return;
  if (mode === 'crypto') {
    if (!state.recordings.length) { showError('No crypto recordings yet.\nRecord one:  python -m sim.crypto_record --minutes 3'); state.mode = 'crypto'; render(); return; }
    await loadRecording(state.recid || state.recordings[0].recid);
  } else {
    if (!state.names || !Object.keys(state.names).length) { try { state.names = await source.tickers(); } catch (_) {} }
    state.ticker = 'AAPL';
    await loadDate(state.date);
  }
}

function bindEvents() {
  $('mode-stock').addEventListener('click', () => switchMode('stock'));
  $('mode-crypto').addEventListener('click', () => switchMode('crypto'));
  $('date').addEventListener('change', (e) => { if (e.target.value) loadDate(e.target.value); });
  $('recording').addEventListener('change', (e) => { if (e.target.value) loadRecording(e.target.value); });
  $('qty').addEventListener('input', (e) => {
    const v = +e.target.value || 0;
    state.qty = isCrypto() ? Math.max(0, v) : Math.max(1, Math.round(v));
    render();
  });
  $('buy').addEventListener('click', () => applyFill('BUY', state.qty));
  $('sell').addEventListener('click', () => applyFill('SELL', state.qty));

  $('draw-btn').addEventListener('click', () => { state.drawMode = !state.drawMode; state.sel = -1; render(); });
  $('del-btn').addEventListener('click', () => { state.lines = state.lines.filter((_, i) => i !== state.sel); state.sel = -1; render(); });
  $('clear-btn').addEventListener('click', () => { state.lines = []; state.sel = -1; state.drawMode = false; render(); });

  canvas.addEventListener('mousedown', (e) => {
    const pt = px2data(e); if (!pt) return;
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
    const d = state.draft; if (!d) return;
    const moved = Math.abs(d.a.sec - d.b.sec) > 1 || Math.abs(d.a.price - d.b.price) > 0.01;
    const oldLen = state.lines.length;
    if (moved) { state.lines = [...state.lines, d]; state.sel = oldLen; } else state.sel = -1;
    state.draft = null; state.drawMode = false; render();
  };
  canvas.addEventListener('mouseup', finishLine);
  canvas.addEventListener('mouseleave', finishLine);

  $('attach-bracket').addEventListener('click', attachBracket);
  ['stop-price', 'target-price'].forEach((id) => $(id).addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); attachBracket(); } }));
  $('working').addEventListener('click', (e) => {
    const btn = e.target.closest('.wo-cancel'); if (!btn) return;
    state.orders = state.orders.filter((o) => o.id !== +btn.dataset.id); render();
  });

  $('jump-open').addEventListener('click', () => { advanceTo(0, false); state.playing = false; render(); });
  $('step-back').addEventListener('click', () => { advanceTo(state.idx - 1, false); state.playing = false; render(); });
  $('play').addEventListener('click', () => { state.playing = !state.playing; if (state.idx >= LEN() - 1) advanceTo(0, false); acc = 0; render(); });
  $('step-fwd').addEventListener('click', () => { advanceTo(state.idx + 1, true); state.playing = false; render(); });
  $('jump-close').addEventListener('click', () => { advanceTo(LEN() - 1, true); state.playing = false; render(); });
  $('scrub').addEventListener('input', (e) => { advanceTo(+e.target.value, false); render(); });

  window.addEventListener('resize', render);
  window.addEventListener('keydown', (e) => {
    if (/INPUT|SELECT|TEXTAREA/.test(document.activeElement.tagName)) return;
    if ((e.key === 'Delete' || e.key === 'Backspace') && state.sel >= 0) {
      e.preventDefault(); state.lines = state.lines.filter((_, i) => i !== state.sel); state.sel = -1; render();
    } else if (e.key === ' ') {
      e.preventDefault(); state.playing = !state.playing; if (state.idx >= LEN() - 1) advanceTo(0, false); acc = 0; render();
    } else if (e.key === 'ArrowLeft') { e.preventDefault(); advanceTo(state.idx - 1, false); state.playing = false; render(); }
    else if (e.key === 'ArrowRight') { e.preventDefault(); advanceTo(state.idx + 1, true); state.playing = false; render(); }
  });
}

function mostRecentWeekday() {
  const d = new Date();
  const day = d.getDay();
  const back = day === 0 ? 2 : day === 6 ? 1 : (day === 1 ? 3 : 1);
  d.setDate(d.getDate() - back);
  return d.toISOString().slice(0, 10);
}

// ── boot ──────────────────────────────────────────────────────────────────────
async function initStock() {
  try {
    const names = await source.tickers();
    state.names = names; state.order = Object.keys(names);
    if (!state.order.includes(state.ticker)) state.ticker = state.order[0];
  } catch (_) { /* keep defaults */ }
  const dates = await source.availableDates().catch(() => []);
  if (dates.length) state.date = dates[dates.length - 1];
  $('date').value = state.date;
  $('date').max = new Date().toISOString().slice(0, 10);
  await loadDate(state.date);
}

async function init() {
  buildTransportButtons();
  buildTabs();
  bindEvents();
  try { state.recordings = await source.cryptoRecordings(); } catch (_) { state.recordings = []; }
  populateRecordings();
  render();
  // loadRecording / loadDate set state.mode themselves once their sessions are in,
  // so we never render a crypto layout against not-yet-loaded sessions.
  if (state.recordings.length) await loadRecording(state.recordings[0].recid);
  else await initStock();
  setInterval(loop, 100);
}

init();
