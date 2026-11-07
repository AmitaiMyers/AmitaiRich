// ROOF·SIM Agent Lab — GUI for training, validating, and reporting DQN models.
// Talks to /api/agent/*: launch runs, poll live progress from train_log.csv, and
// render the report (training curves, validation metrics, day-by-day tape, equity).

const $ = (id) => document.getElementById(id);
const UP = '#16c784', DN = '#ea3943', CYAN = '#4f8cff', GOLD = '#f0b429', DIM = '#5a6a80';

let selected = null;      // currently viewed run name
let pollTimer = null;

// ── helpers ───────────────────────────────────────────────────────────────────
async function api(path, opts) {
  const res = await fetch(path, opts);
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || body.error || ('HTTP ' + res.status));
  }
  return res.json();
}
const pct = (x) => (x >= 0 ? '+' : '') + (x * 100).toFixed(2) + '%';
const pctColor = (x) => (x > 1e-9 ? UP : x < -1e-9 ? DN : DIM);
const num = (v) => (v === '' || v == null ? null : +v);

function statusBadge(status) {
  const map = { running: ['LIVE', GOLD], done: ['DONE', UP], failed: ['FAILED', DN], unknown: ['?', DIM] };
  const [txt, col] = map[status] || map.unknown;
  return `<span class="badge" style="color:${col};border-color:${col}">${txt}</span>`;
}

// ── options + dataset ───────────────────────────────────────────────────────────
async function loadOptions() {
  const opt = await api('/api/agent/options');
  $('f-indicators').innerHTML = opt.indicator_groups.map((g) =>
    `<label class="chk"><input type="checkbox" value="${g}" checked> ${g}</label>`).join('');
  $('f-arch').value = opt.archs.includes('mlp') ? 'mlp' : opt.archs[0];
  renderDataset(opt.dataset);
}

function renderDataset(ds) {
  const el = $('dataset-status'), btn = $('build-dataset');
  if (ds.building) {
    el.innerHTML = `<span style="color:${GOLD}">building…</span> ` +
      `<div class="mini-log">${(ds.log_tail || '').split('\n').slice(-3).join('<br>')}</div>`;
    btn.classList.add('hidden');
  } else if (ds.exists && ds.meta) {
    el.innerHTML = `<span style="color:${UP}">ready</span> · ${ds.meta.n_train_tickers} tickers · ` +
      `${ds.meta.n_features} features<br><span class="lab-muted">${ds.meta.scope} ${ds.meta.start}→${ds.meta.end}</span>`;
    btn.textContent = 'Rebuild dataset'; btn.classList.remove('hidden');
  } else {
    el.innerHTML = `<span style="color:${DN}">not built</span> — build it before training.`;
    btn.textContent = 'Build dataset'; btn.classList.remove('hidden');
  }
}

// ── runs list ───────────────────────────────────────────────────────────────────
async function loadRuns() {
  const runs = await api('/api/agent/runs');
  $('runs-count').textContent = runs.length ? `(${runs.length})` : '';
  $('runs-list').innerHTML = runs.length ? runs.map((r) => `
    <div class="run-item ${r.name === selected ? 'active' : ''}" data-name="${r.name}">
      <div class="run-top"><span class="run-name">${r.name}</span>${statusBadge(r.status)}</div>
      <div class="run-sub">${r.arch || '—'} · ${r.episode}/${r.total_episodes || '?'} ep</div>
      <div class="run-bar"><div class="run-bar-fill" style="width:${Math.round((r.progress || 0) * 100)}%"></div></div>
    </div>`).join('') : '<div class="lab-muted">No runs yet.</div>';
  document.querySelectorAll('.run-item').forEach((el) =>
    el.addEventListener('click', () => selectRun(el.dataset.name)));
  return runs;
}

// ── run report view ─────────────────────────────────────────────────────────────
async function selectRun(name) {
  selected = name;
  await refreshView();
  await loadRuns();
}

async function refreshView() {
  if (!selected) return;
  let run;
  try { run = await api('/api/agent/run/' + encodeURIComponent(selected)); }
  catch (e) { $('run-view').innerHTML = `<div class="lab-empty">${e.message}</div>`; return; }
  renderRun(run);
  // live polling while running
  clearInterval(pollTimer); pollTimer = null;
  if (run.status === 'running') {
    pollTimer = setInterval(async () => { await refreshView(); await loadRuns(); }, 1800);
  }
}

function bestValFromLog(log) {
  const vals = log.map((r) => num(r.val_mean_return)).filter((v) => v != null);
  return vals.length ? Math.max(...vals) : null;
}

function renderRun(run) {
  const cfg = run.config || (run.launch && run.launch.params) || {};
  const indicators = cfg.indicators || (run.launch && run.launch.params && run.launch.params.indicators) || 'all';
  const bestVal = (cfg.best_metric != null) ? cfg.best_metric : bestValFromLog(run.train_log);
  const lastVal = run.train_log.map((r) => num(r.val_mean_return)).filter((v) => v != null).slice(-1)[0];

  $('run-view').innerHTML = `
    <div class="rv-head">
      <div><span class="rv-title">${run.name}</span> ${statusBadge(run.status)}</div>
      <div class="rv-actions">
        ${run.status === 'running' ? '<button id="stop-run" class="lab-btn danger sm">■ stop</button>' : ''}
      </div>
    </div>
    <div class="rv-progress"><div class="run-bar big"><div class="run-bar-fill" style="width:${Math.round((run.progress || 0) * 100)}%"></div></div>
      <span class="lab-muted">${run.episode}/${run.total_episodes || '?'} episodes</span></div>

    <div class="cards">
      ${card('Arch', (cfg.arch || '—') + (cfg.window > 1 ? ` · w${cfg.window}` : ''))}
      ${card('Indicators', Array.isArray(indicators) ? indicators.join(', ') : indicators)}
      ${card('Best val return', bestVal != null ? pct(bestVal) : '—', bestVal != null ? pctColor(bestVal) : null)}
      ${card('Latest val', lastVal != null ? pct(lastVal) : '—', lastVal != null ? pctColor(lastVal) : null)}
    </div>

    <div class="rv-grid">
      <div class="lab-card"><div class="lab-h">TRAINING — RETURN</div><canvas id="chart-return" class="rv-canvas"></canvas></div>
      <div class="lab-card"><div class="lab-h">TRAINING — LOSS</div><canvas id="chart-loss" class="rv-canvas"></canvas></div>
    </div>

    ${run.tape ? `<div class="lab-card"><div class="lab-h">VALIDATION EQUITY CURVE (${run.tape[0] ? run.tape[0].ticker : ''})</div>
      <canvas id="chart-equity" class="rv-canvas wide"></canvas></div>` : ''}

    ${run.tape ? `<div class="lab-card"><div class="lab-h">DAY-BY-DAY TAPE — BUY/SELL DECISIONS</div>
      <div id="tape-wrap" class="tape-table"></div></div>` : ''}

    <div class="lab-card"><div class="lab-h">REPORT</div>
      <div class="report-md">${run.report_md ? renderMd(run.report_md) : '<span class="lab-muted">Report is written when training + validation finish.</span>'}</div></div>

    ${run.console_tail ? `<div class="lab-card"><div class="lab-h">CONSOLE</div><pre class="console">${escapeHtml(run.console_tail)}</pre></div>` : ''}
  `;

  if ($('stop-run')) $('stop-run').addEventListener('click', async () => {
    await api('/api/agent/run/' + encodeURIComponent(run.name) + '/stop', { method: 'POST' });
    await refreshView();
  });

  drawReturnChart($('chart-return'), run.train_log);
  drawLossChart($('chart-loss'), run.train_log);
  if (run.tape) { drawEquityChart($('chart-equity'), run.tape); renderTape(run.tape); }
}

function card(label, value, color) {
  return `<div class="metric"><div class="metric-label">${label}</div>` +
    `<div class="metric-value" style="${color ? 'color:' + color : ''}">${value}</div></div>`;
}

// ── tape table ──────────────────────────────────────────────────────────────────
function renderTape(tape) {
  const events = tape.filter((r) => r.event);
  const rows = (events.length ? events : tape).slice(0, 400);
  $('tape-wrap').innerHTML = `
    <div class="tape-row th"><span>DATE</span><span>PRICE</span><span>SIGNAL</span><span>POSITION</span><span>EQUITY</span></div>
    ${rows.map((r) => {
      const sig = r.action === 'BUY' ? `<span style="color:${UP};font-weight:600">BUY</span>`
        : r.action === 'SELL' ? `<span style="color:${DN};font-weight:600">SELL</span>`
        : `<span class="lab-muted">hold</span>`;
      const pos = r.position === 'LONG' ? `<span style="color:${UP}">● LONG</span>` : `<span class="lab-muted">· flat</span>`;
      return `<div class="tape-row"><span class="lab-muted">${r.date}</span><span>${(+r.price).toFixed(2)}</span>` +
        `<span>${sig}</span><span>${pos}</span><span>${(+r.equity).toLocaleString('en-US', { maximumFractionDigits: 0 })}</span></div>`;
    }).join('')}
    <div class="lab-muted tape-note">${events.length} BUY/SELL events of ${tape.length} sessions</div>`;
}

// ── canvas charts ───────────────────────────────────────────────────────────────
function setupCanvas(cv, h = 190) {
  const dpr = window.devicePixelRatio || 1;
  const W = cv.clientWidth || 560;
  cv.width = W * dpr; cv.height = h * dpr; cv.style.height = h + 'px';
  const ctx = cv.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, W, h);
  return { ctx, W, H: h };
}

function drawAxes(ctx, W, H, pad, lo, hi, baseline) {
  ctx.strokeStyle = '#1c2430'; ctx.fillStyle = DIM; ctx.font = '10px "IBM Plex Mono",monospace';
  ctx.textBaseline = 'middle'; ctx.lineWidth = 1;
  for (let g = 0; g <= 4; g++) {
    const y = pad.t + (H - pad.t - pad.b) * g / 4;
    const val = hi - (hi - lo) * g / 4;
    ctx.beginPath(); ctx.moveTo(pad.l, y); ctx.lineTo(W - pad.r, y); ctx.stroke();
    ctx.fillText(fmtAxis(val), 4, y);
  }
  if (baseline != null && baseline >= lo && baseline <= hi) {
    const y = pad.t + (H - pad.t - pad.b) * (hi - baseline) / (hi - lo);
    ctx.strokeStyle = '#3d4a5e'; ctx.setLineDash([2, 4]);
    ctx.beginPath(); ctx.moveTo(pad.l, y); ctx.lineTo(W - pad.r, y); ctx.stroke(); ctx.setLineDash([]);
  }
}
function fmtAxis(v) { return Math.abs(v) >= 1000 ? (v / 1000).toFixed(0) + 'k' : v.toFixed(2); }

function plotLine(ctx, pts, W, H, pad, lo, hi, xmax, color, width, dots) {
  const X = (x) => pad.l + (W - pad.l - pad.r) * (xmax <= 1 ? 0.5 : x / xmax);
  const Y = (y) => pad.t + (H - pad.t - pad.b) * (hi === lo ? 0.5 : (hi - y) / (hi - lo));
  ctx.strokeStyle = color; ctx.fillStyle = color; ctx.lineWidth = width;
  ctx.beginPath(); let started = false;
  for (const [x, y] of pts) {
    const px = X(x), py = Y(y);
    if (!started) { ctx.moveTo(px, py); started = true; } else ctx.lineTo(px, py);
  }
  ctx.stroke();
  if (dots) for (const [x, y] of pts) { ctx.beginPath(); ctx.arc(X(x), Y(y), 2.2, 0, 7); ctx.fill(); }
}

function drawReturnChart(cv, log) {
  const { ctx, W, H } = setupCanvas(cv);
  const pad = { l: 42, r: 8, t: 8, b: 16 };
  if (!log.length) { emptyChart(ctx, W, H); return; }
  const epRet = log.map((r, i) => [i + 1, num(r.episode_return)]).filter((p) => p[1] != null);
  const valRet = log.map((r, i) => [i + 1, num(r.val_mean_return)]).filter((p) => p[1] != null);
  const all = epRet.concat(valRet).map((p) => p[1]);
  let lo = Math.min(0, ...all), hi = Math.max(0, ...all); if (hi === lo) hi = lo + 0.01;
  const pad2 = (hi - lo) * 0.1; lo -= pad2; hi += pad2;
  const xmax = log.length;
  drawAxes(ctx, W, H, pad, lo, hi, 0);
  plotLine(ctx, epRet, W, H, pad, lo, hi, xmax, 'rgba(138,151,171,0.55)', 1);   // per-episode return
  plotLine(ctx, valRet, W, H, pad, lo, hi, xmax, CYAN, 1.6, true);              // validation return
  legend(ctx, W, [['episode', 'rgba(138,151,171,0.8)'], ['validation', CYAN]]);
}

function drawLossChart(cv, log) {
  const { ctx, W, H } = setupCanvas(cv);
  const pad = { l: 42, r: 8, t: 8, b: 16 };
  const loss = log.map((r, i) => [i + 1, num(r.avg_loss)]).filter((p) => p[1] != null);
  if (!loss.length) { emptyChart(ctx, W, H, 'waiting for training…'); return; }
  const vals = loss.map((p) => p[1]);
  let lo = Math.min(...vals), hi = Math.max(...vals); if (hi === lo) hi = lo + 1e-6;
  const pad2 = (hi - lo) * 0.1; lo -= pad2; hi += pad2;
  drawAxes(ctx, W, H, pad, lo, hi, null);
  plotLine(ctx, loss, W, H, pad, lo, hi, log.length, GOLD, 1.4);
}

function drawEquityChart(cv, tape) {
  const { ctx, W, H } = setupCanvas(cv, 200);
  const pad = { l: 52, r: 8, t: 8, b: 16 };
  const eq = tape.map((r, i) => [i, +r.equity]);
  const vals = eq.map((p) => p[1]).concat([100000]);
  let lo = Math.min(...vals), hi = Math.max(...vals); if (hi === lo) hi = lo + 1;
  const pad2 = (hi - lo) * 0.08; lo -= pad2; hi += pad2;
  drawAxes(ctx, W, H, pad, lo, hi, 100000);
  const last = eq.length ? eq[eq.length - 1][1] : 100000;
  plotLine(ctx, eq, W, H, pad, lo, hi, eq.length - 1 || 1, last >= 100000 ? UP : DN, 1.6);
}

function emptyChart(ctx, W, H, msg) {
  ctx.fillStyle = DIM; ctx.font = '11px "IBM Plex Mono",monospace'; ctx.textAlign = 'center';
  ctx.fillText(msg || 'no data yet', W / 2, H / 2); ctx.textAlign = 'left';
}
function legend(ctx, W, items) {
  ctx.font = '10px "IBM Plex Mono",monospace'; ctx.textBaseline = 'middle';
  let x = W - 8;
  for (const [label, color] of items.reverse()) {
    const w = ctx.measureText(label).width;
    ctx.fillStyle = color; ctx.fillText(label, x - w, 12); x -= w + 8;
    ctx.fillRect(x - 10, 9, 7, 3); x -= 16;
  }
}

// ── minimal markdown ────────────────────────────────────────────────────────────
function escapeHtml(s) { return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); }
function renderMd(md) {
  const lines = md.split('\n'); let html = '', inCode = false;
  for (const ln of lines) {
    if (ln.trim() === '```') { inCode = !inCode; html += inCode ? '<pre class="console">' : '</pre>'; continue; }
    if (inCode) { html += escapeHtml(ln) + '\n'; continue; }
    if (ln.startsWith('## ')) html += `<h4>${escapeHtml(ln.slice(3))}</h4>`;
    else if (ln.startsWith('# ')) html += `<h3>${escapeHtml(ln.slice(2))}</h3>`;
    else if (ln.trim() === '') continue;
    else {
      let t = escapeHtml(ln).replace(/\*\*(.+?)\*\*/g, '<b>$1</b>').replace(/`(.+?)`/g, '<code>$1</code>');
      html += ln.startsWith('- ') ? `<div class="md-li">• ${t.slice(2)}</div>` : `<div>${t}</div>`;
    }
  }
  return html;
}

// ── form + dataset actions ──────────────────────────────────────────────────────
function bind() {
  $('run-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const indicators = [...document.querySelectorAll('#f-indicators input:checked')].map((c) => c.value);
    const msg = $('form-msg');
    if (!indicators.length) { msg.textContent = 'Pick at least one indicator.'; msg.className = 'lab-msg err'; return; }
    const payload = {
      name: $('f-name').value.trim(), indicators, arch: $('f-arch').value,
      window: +$('f-window').value, episodes: +$('f-episodes').value, batch_size: +$('f-batch').value,
      d_model: +$('f-dmodel').value, seq_layers: +$('f-layers').value,
    };
    try {
      const r = await api('/api/agent/train', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
      msg.textContent = 'Started: ' + r.name; msg.className = 'lab-msg ok';
      await loadRuns(); await selectRun(r.name);
    } catch (err) { msg.textContent = err.message; msg.className = 'lab-msg err'; }
  });

  $('f-arch').addEventListener('change', () => {
    if ($('f-arch').value !== 'mlp' && +$('f-window').value < 2) $('f-window').value = 30;
  });

  $('build-dataset').addEventListener('click', async () => {
    try { await api('/api/agent/dataset', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
      $('dataset-status').innerHTML = `<span style="color:${GOLD}">build started…</span>`;
      setTimeout(pollDataset, 1500);
    } catch (e) { $('dataset-status').textContent = e.message; }
  });
}

async function pollDataset() {
  const ds = await api('/api/agent/dataset');
  renderDataset(ds);
  if (ds.building) setTimeout(pollDataset, 2500);
}

// ── boot ────────────────────────────────────────────────────────────────────────
async function init() {
  bind();
  try { await loadOptions(); } catch (e) { $('dataset-status').textContent = e.message; }
  await loadRuns();
  // keep the runs list fresh even without a selection
  setInterval(async () => { if (!pollTimer) await loadRuns(); }, 4000);
}
init();
