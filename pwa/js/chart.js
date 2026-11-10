// A small dependency-free canvas chart: optional OHLC candles plus line series on a shared
// day axis, optional log scale, BUY/SELL markers, crosshair tooltip, crisp on HiDPI screens,
// redrawn on resize and theme change. Candles are merged (e.g. into weekly/monthly bars) when
// there are more than fit the width, so long ranges stay readable.

import { dayToIso } from './data.js';
import { h } from './ui.js';

const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

/**
 * series: [{name, days: Int32Array, values: Float64Array, color: css var, width?, dash?}]
 * markers: [{day, value, kind: 'buy'|'sell'}]
 * candles: {name, days, open, high, low, close} (optional; drawn under the series)
 */
export function lineChart({ series, candles = null, markers = [], log = false, format = (v) => v.toFixed(2), tall = false }) {
  const canvas = h('canvas');
  const tip = h('div', { class: 'tip', hidden: true });
  const wrap = h('div', { class: `chart${tall ? ' tall' : ''}` }, canvas, tip);
  const legend = h('div', { class: 'legend' },
    candles ? h('span', {}, h('i', { style: `background:${css('--up')}` }), h('i', { style: `background:${css('--down')}` }), candles.name) : null,
    series.map((s) => h('span', {}, h('i', { style: `background:${css(s.color)}` }), s.name)));
  let hoverX = null;

  const allDays = series.flatMap((s) => [s.days[0], s.days[s.days.length - 1]]);
  if (candles) allDays.push(candles.days[0], candles.days[candles.days.length - 1]);
  const minDay = Math.min(...allDays), maxDay = Math.max(...allDays);
  let lo = Infinity, hi = -Infinity;
  const include = (v) => { if (Number.isFinite(v) && (!log || v > 0)) { lo = Math.min(lo, v); hi = Math.max(hi, v); } };
  for (const s of series) for (const v of s.values) include(v);
  if (candles) for (let i = 0; i < candles.days.length; i++) { include(candles.low[i]); include(candles.high[i]); }
  if (!Number.isFinite(lo)) { lo = 0; hi = 1; }
  if (lo === hi) { lo -= 1; hi += 1; }
  const tf = log ? Math.log : (v) => v;
  const [tlo, thi] = [tf(lo), tf(hi)];
  const pad = { l: 8, r: 64, t: 10, b: 24 };

  function draw() {
    const ratio = window.devicePixelRatio || 1;
    const width = canvas.clientWidth, height = canvas.clientHeight;
    if (!width || !height) return;
    canvas.width = Math.round(width * ratio); canvas.height = Math.round(height * ratio);
    const ctx = canvas.getContext('2d');
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    ctx.clearRect(0, 0, width, height);
    const plotW = width - pad.l - pad.r, plotH = height - pad.t - pad.b;
    const x = (day) => pad.l + ((day - minDay) / Math.max(1, maxDay - minDay)) * plotW;
    const y = (v) => pad.t + (1 - (tf(v) - tlo) / (thi - tlo)) * plotH;

    // Grid + y labels.
    ctx.font = '11px system-ui, sans-serif';
    ctx.fillStyle = css('--muted'); ctx.strokeStyle = css('--border'); ctx.lineWidth = 1;
    for (let k = 0; k <= 4; k++) {
      const value = log ? Math.exp(tlo + ((thi - tlo) * k) / 4) : lo + ((hi - lo) * k) / 4;
      const yy = Math.round(y(value)) + 0.5;
      ctx.beginPath(); ctx.moveTo(pad.l, yy); ctx.lineTo(pad.l + plotW, yy); ctx.stroke();
      ctx.fillText(format(value), pad.l + plotW + 6, yy + 4);
    }
    // X labels: ~6 evenly spaced dates.
    for (let k = 0; k <= 5; k++) {
      const day = minDay + ((maxDay - minDay) * k) / 5;
      const label = maxDay - minDay > 6 * 365 ? dayToIso(day).slice(0, 4) : dayToIso(day).slice(0, 7);
      const xx = x(day);
      ctx.fillText(label, Math.min(Math.max(xx - 14, pad.l), pad.l + plotW - 30), height - 6);
    }
    if (candles) drawCandles(ctx, candles, x, y, plotW);
    // Series.
    for (const s of series) {
      ctx.strokeStyle = css(s.color); ctx.lineWidth = s.width || 1.6; ctx.setLineDash(s.dash || []);
      ctx.beginPath();
      let started = false;
      for (let i = 0; i < s.values.length; i++) {
        const v = s.values[i];
        if (!Number.isFinite(v) || (log && v <= 0)) { started = false; continue; }
        const px = x(s.days[i]), py = y(v);
        if (started) ctx.lineTo(px, py); else { ctx.moveTo(px, py); started = true; }
      }
      ctx.stroke();
    }
    ctx.setLineDash([]);
    // Markers: ▲ buy (green), ▼ sell (red).
    for (const m of markers) {
      const px = x(m.day), py = y(m.value);
      ctx.fillStyle = css(m.kind === 'buy' ? '--up' : '--down');
      ctx.beginPath();
      if (m.kind === 'buy') { ctx.moveTo(px, py + 3); ctx.lineTo(px - 5, py + 11); ctx.lineTo(px + 5, py + 11); }
      else { ctx.moveTo(px, py - 3); ctx.lineTo(px - 5, py - 11); ctx.lineTo(px + 5, py - 11); }
      ctx.fill();
    }
    // Crosshair + tooltip.
    if (hoverX !== null) {
      const day = minDay + ((hoverX - pad.l) / plotW) * (maxDay - minDay);
      ctx.strokeStyle = css('--muted'); ctx.setLineDash([3, 3]);
      ctx.beginPath(); ctx.moveTo(hoverX + 0.5, pad.t); ctx.lineTo(hoverX + 0.5, pad.t + plotH); ctx.stroke();
      ctx.setLineDash([]);
      tip.replaceChildren(h('div', { class: 'muted', text: dayToIso(Math.round(day)) }),
        candles ? candleTip(candles, nearest(candles.days, day), format) : null,
        ...series.map((s) => {
          const i = nearest(s.days, day);
          return h('div', {}, h('span', { style: `color:${css(s.color)}`, text: '● ' }), `${s.name}: ${format(s.values[i])}`);
        }));
      tip.hidden = false;
      tip.style.left = `${Math.min(hoverX + 12, width - tip.offsetWidth - 4)}px`;
      tip.style.top = '8px';
    } else tip.hidden = true;
  }

  canvas.addEventListener('pointermove', (event) => {
    const rect = canvas.getBoundingClientRect();
    hoverX = Math.min(Math.max(event.clientX - rect.left, pad.l), rect.width - pad.r);
    draw();
  });
  canvas.addEventListener('pointerleave', () => { hoverX = null; draw(); });
  new ResizeObserver(draw).observe(canvas);
  window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', draw);
  return h('div', {}, wrap, legend);
}

/** Merge consecutive bars into one candle per `size` bars (open of first, close of last, extreme high/low). */
function mergeCandles(c, size) {
  const out = { days: [], open: [], high: [], low: [], close: [] };
  for (let start = 0; start < c.days.length; start += size) {
    const end = Math.min(start + size, c.days.length);
    let high = -Infinity, low = Infinity;
    for (let i = start; i < end; i++) { high = Math.max(high, c.high[i]); low = Math.min(low, c.low[i]); }
    out.days.push((c.days[start] + c.days[end - 1]) / 2);
    out.open.push(c.open[start]); out.close.push(c.close[end - 1]); out.high.push(high); out.low.push(low);
  }
  return out;
}

function drawCandles(ctx, candles, x, y, plotW) {
  const maxCandles = Math.max(10, Math.floor(plotW / 4));          // >= ~4 px per candle
  const c = mergeCandles(candles, Math.max(1, Math.ceil(candles.days.length / maxCandles)));
  const step = plotW / c.days.length;
  const body = Math.max(1, Math.min(9, step * 0.7));
  for (let i = 0; i < c.days.length; i++) {
    const up = c.close[i] >= c.open[i];
    ctx.strokeStyle = ctx.fillStyle = css(up ? '--up' : '--down');
    const px = Math.round(x(c.days[i])) + 0.5;
    ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(px, y(c.high[i])); ctx.lineTo(px, y(c.low[i])); ctx.stroke();
    const top = y(Math.max(c.open[i], c.close[i])), bottom = y(Math.min(c.open[i], c.close[i]));
    ctx.fillRect(px - body / 2, top, body, Math.max(1, bottom - top));
  }
}

function candleTip(c, i, format) {
  return h('div', {}, `${c.name}: O ${format(c.open[i])} H ${format(c.high[i])} L ${format(c.low[i])} C ${format(c.close[i])}`);
}

function nearest(days, day) {
  let lo = 0, hi = days.length - 1;
  while (lo < hi) { const mid = (lo + hi) >> 1; if (days[mid] < day) lo = mid + 1; else hi = mid; }
  return lo > 0 && Math.abs(days[lo - 1] - day) < Math.abs(days[lo] - day) ? lo - 1 : lo;
}
