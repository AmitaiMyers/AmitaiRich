// The backtest engine — a line-by-line port of engine.py (one account, many stocks).
//
// Day order (identical to Python): next-open fills (sells, then buys) -> intrabar
// stops -> BUY decisions at the close (ranked by score) -> SELL decisions at the
// close -> final-bar liquidation -> mark to market. See engine.py for the rationale.

export const DEFAULT_CONFIG = Object.freeze({
  startingCapital: 100000,
  maxPositions: 1,
  sizingMode: 'risk_based',     // 'risk_based' | 'all_in' | 'fixed_fraction'
  riskPct: 0.01,
  fixedFraction: 0.95,
  leverage: 1.0,
  costBps: 0,
  fillMode: 'close',            // 'close' | 'next_open'
  stopMode: 'tightest',         // 'tightest' | 'widest'
  skipUnprotectable: false,
});

/** Pick the tightest (highest) or widest (lowest) candidate strictly below entry. */
export function selectStop(candidates, entryPrice, stopMode) {
  const belowEntry = candidates.filter((level) => level < entryPrice);
  if (!belowEntry.length) {
    throw new Error(`No stop candidate is below the entry price ${entryPrice.toFixed(4)}`);
  }
  if (stopMode === 'tightest') return Math.max(...belowEntry);
  if (stopMode === 'widest') return Math.min(...belowEntry);
  throw new Error(`stopMode must be 'tightest' or 'widest', got ${stopMode}`);
}

const hasStop = (s) => s.stopLevels.length > 0 || s.stopAtr !== null;

function stopCandidates(signals, i, fillPrice) {
  const levels = signals.stopLevels.map((level) => level[i]);
  if (signals.stopAtr !== null) levels.push(fillPrice - signals.stopAtrMult * signals.stopAtr[i]);
  return levels;
}

export function stopPriceAt(signals, i, fillPrice, stopMode) {
  if (!hasStop(signals)) return null;
  return selectStop(stopCandidates(signals, i, fillPrice), fillPrice, stopMode);
}

/** Discretionary SELL at bar i's close for an open position? */
export function exitHit(signals, i, closeToday, highestHigh, barsHeld) {
  if (signals.exit[i]) return true;
  if (signals.trailAtr !== null && closeToday < highestHigh - signals.trailMult * signals.trailAtr[i]) return true;
  if (signals.maxHold !== null && barsHeld >= signals.maxHold) return true;
  return false;
}

/** CPython's float floor division (a // b), which can differ from Math.floor(a / b)
 *  when the quotient rounds up to an integer. */
export function pyFloorDiv(a, b) {
  let mod = a % b;
  let div = (a - mod) / b;
  if (mod && (b < 0) !== (mod < 0)) { mod += b; div -= 1; }
  if (!div) return 0;
  let floored = Math.floor(div);
  if (div - floored > 0.5) floored += 1;
  return floored;
}

function validate(config) {
  const allowed = { sizingMode: ['risk_based', 'all_in', 'fixed_fraction'], fillMode: ['close', 'next_open'],
                    stopMode: ['tightest', 'widest'] };
  for (const [key, values] of Object.entries(allowed)) {
    if (!values.includes(config[key])) throw new Error(`${key} must be one of ${values.join('/')}`);
  }
  if (config.maxPositions < 1) throw new Error('maxPositions must be >= 1');
  if (config.startingCapital <= 0) throw new Error('startingCapital must be > 0');
  if (config.leverage < 1) throw new Error('leverage must be >= 1');
}

/** Align every stock onto one calendar of day numbers ([ticker][day] arrays). */
function buildBook(frames, buy, sell) {
  const tickers = Object.keys(frames);
  if (!tickers.length) throw new Error('The engine needs at least one price frame.');
  const daySet = new Set();
  for (const t of tickers) for (const d of frames[t].dates) daySet.add(d);
  const calendar = Int32Array.from([...daySet].sort((a, b) => a - b));
  const dayIndex = new Map(Array.from(calendar, (d, k) => [d, k]));
  const nDays = calendar.length;
  const warmup = Math.max(buy.warmup, sell.warmup);

  const book = { tickers, calendar, stocks: [] };
  for (const t of tickers) {
    const bars = frames[t];
    const cols = Int32Array.from(bars.dates, (d) => dayIndex.get(d));
    const barOfDay = new Int32Array(nDays).fill(-1);
    cols.forEach((col, bar) => { barOfDay[col] = bar; });
    const buySignals = buy.signals(bars);
    const sellSignals = sell === buy ? buySignals : sell.signals(bars);
    const tradable = Uint8Array.from(buySignals.entry);
    tradable.fill(0, 0, Math.min(warmup, tradable.length));
    if (bars.close.length <= warmup + 1) tradable.fill(0);
    book.stocks.push({ ticker: t, bars, cols, barOfDay, buySignals, sellSignals, tradable,
                       lastDay: cols[cols.length - 1] });
  }
  return book;
}

function entryEpisodes(book) {
  let total = 0;
  for (const s of book.stocks) {
    const e = s.tradable;
    for (let i = 0; i < e.length; i++) if (e[i] && (i === 0 || !e[i - 1])) total += 1;
  }
  return total;
}

/**
 * Backtest `frames` ({ticker: bars}) through one account.
 * bars = {dates: day numbers, open, high, low, close}. `regimeOk` (optional) is a
 * per-calendar-day boolean array; when given, risk-off days block entries and exit holdings.
 */
export function runEngine(frames, buy, sell, options = {}, regimeOk = null) {
  const config = { ...DEFAULT_CONFIG, ...options };
  validate(config);
  const book = buildBook(frames, buy, sell);
  const { calendar, stocks } = book;
  const nDays = calendar.length;
  const cost = config.costBps / 10000;
  const lastClose = new Float64Array(stocks.length).fill(Number.NaN);

  let cash = config.startingCapital;
  const held = new Map();          // stock index -> position (insertion order = fill order)
  const pendingBuys = new Map();   // stock index -> decision day
  const pendingSells = new Set();
  const trades = [];
  const equity = new Float64Array(nDays);
  const cashSeries = new Float64Array(nDays);

  const bar = (k, day) => stocks[k].barOfDay[day];
  const hasBar = (k, day) => stocks[k].barOfDay[day] >= 0;
  const price = (k, day, field) => stocks[k].bars[field][bar(k, day)];

  // Same summation order as Python: cash + (0 + h1 + h2 + ...).
  const equityNow = () => {
    let holdings = 0;
    for (const [k, p] of held) holdings += p.shares * lastClose[k];
    return cash + holdings;
  };
  const buyingPower = (eq) => cash + eq * (config.leverage - 1.0);

  function size(eq, fill, stop) {
    let budget = buyingPower(eq);
    if (config.sizingMode === 'fixed_fraction') budget *= config.fixedFraction;
    const maxAffordable = pyFloorDiv(budget / (1.0 + cost), fill);
    if (config.sizingMode !== 'risk_based') return Math.trunc(maxAffordable);
    if (stop === null) throw new Error('risk_based sizing requires a stop loss; use all_in for this strategy.');
    const riskPerShare = fill - stop;
    if (riskPerShare <= 0) throw new Error(`Non-positive risk per share (${riskPerShare})`);
    return Math.trunc(Math.min((eq * config.riskPct) / riskPerShare, maxAffordable));
  }

  function initialStop(k, decisionBar, fill) {
    const s = stocks[k].buySignals;
    if (config.skipUnprotectable && hasStop(s) && !stopCandidates(s, decisionBar, fill).some((l) => l < fill)) {
      return undefined; // unprotectable entry: skipped
    }
    return stopPriceAt(s, decisionBar, fill, config.stopMode);
  }

  function open(k, day, decisionDay, fill, eq) {
    const stop = initialStop(k, bar(k, decisionDay), fill);
    if (stop === undefined) return false;
    const shares = size(eq, fill, stop);
    if (shares <= 0) return false;
    const notional = shares * fill;
    const entryCost = notional * cost;
    if (notional + entryCost > buyingPower(eq) + 1e-9) throw new Error('Insufficient buying power');
    cash -= notional + entryCost;
    held.set(k, { fillDay: day, entryPrice: fill, stop, shares, entryCost,
                  highestHigh: price(k, day, 'high'), barsHeld: 0, openedAtClose: false });
    return true;
  }

  function close(k, day, fill, reason) {
    const p = held.get(k);
    held.delete(k);
    const proceeds = p.shares * fill;
    const exitCost = proceeds * cost;
    cash += proceeds - exitCost;
    trades.push({ ticker: stocks[k].ticker, entryDay: calendar[p.fillDay], entryPrice: p.entryPrice,
                  stopPrice: p.stop, shares: p.shares, exitDay: calendar[day], exitPrice: fill,
                  exitReason: reason, barsHeld: p.barsHeld, costs: p.entryCost + exitCost,
                  ret: fill / p.entryPrice - 1, pnl: p.shares * (fill - p.entryPrice) - p.entryCost - exitCost });
  }

  for (let day = 0; day < nDays; day++) {
    // Age held positions; remember the previous close for next-open sizing.
    for (const [k, p] of held) {
      p.openedAtClose = false;
      if (hasBar(k, day) && day > p.fillDay) {
        p.barsHeld += 1;
        p.highestHigh = Math.max(p.highestHigh, price(k, day, 'high'));
      }
    }

    if (config.fillMode === 'next_open') {
      for (const k of [...pendingSells].sort((a, b) => a - b)) {
        if (!hasBar(k, day)) continue;
        pendingSells.delete(k);
        close(k, day, price(k, day, 'open'), 'signal');
      }
      const eq = equityNow(); // marked at the previous closes, like Python's _equity(day - 1)
      for (const [k, decisionDay] of [...pendingBuys]) {
        if (!hasBar(k, day)) continue;
        pendingBuys.delete(k);
        open(k, day, decisionDay, price(k, day, 'open'), eq);
      }
    }

    for (const [k, p] of [...held]) {
      if (p.stop === null || !hasBar(k, day)) continue;
      if (price(k, day, 'low') <= p.stop) {
        pendingSells.delete(k);
        close(k, day, Math.min(p.stop, price(k, day, 'open')), 'stop');
      }
    }

    for (let k = 0; k < stocks.length; k++) if (hasBar(k, day)) lastClose[k] = price(k, day, 'close');

    const riskOn = regimeOk === null || regimeOk[day];
    if (!riskOn) {
      for (const k of [...held.keys()]) {
        if (!hasBar(k, day)) continue;
        pendingSells.delete(k);
        close(k, day, price(k, day, 'close'), 'regime');
      }
    }

    // BUY decisions at the close.
    let freeSlots = config.maxPositions - held.size - pendingBuys.size;
    if (riskOn && freeSlots > 0) {
      const candidates = [];
      for (let k = 0; k < stocks.length; k++) {
        const b = bar(k, day);
        if (b >= 0 && stocks[k].tradable[b] && !held.has(k) && !pendingBuys.has(k)) candidates.push(k);
      }
      const score = (k) => {
        const v = stocks[k].buySignals.score[bar(k, day)];
        return Number.isNaN(v) ? -Infinity : v;
      };
      candidates.sort((a, b) => score(b) - score(a) || a - b); // stable: ties keep universe order
      const eq = equityNow();
      for (const k of candidates) {
        if (freeSlots <= 0) break;
        if (config.fillMode === 'next_open') {
          pendingBuys.set(k, day);
          freeSlots -= 1;
        } else if (open(k, day, day, price(k, day, 'close'), eq)) {
          held.get(k).openedAtClose = true;
          freeSlots -= 1;
        }
      }
    }

    // SELL decisions at the close.
    for (const [k, p] of [...held]) {
      if (p.openedAtClose || pendingSells.has(k) || !hasBar(k, day)) continue;
      if (!exitHit(stocks[k].sellSignals, bar(k, day), price(k, day, 'close'), p.highestHigh, p.barsHeld)) continue;
      if (config.fillMode === 'close') close(k, day, price(k, day, 'close'), 'signal');
      else pendingSells.add(k);
    }

    // A stock's final bar liquidates its position; pending buys on it are dropped.
    for (const k of [...held.keys()]) {
      if (stocks[k].lastDay === day) { pendingSells.delete(k); close(k, day, price(k, day, 'close'), 'final'); }
    }
    for (const k of [...pendingBuys.keys()]) if (stocks[k].lastDay === day) pendingBuys.delete(k);

    cashSeries[day] = cash;
    equity[day] = equityNow();
  }
  return { calendar, equity, cash: cashSeries, trades, nEntrySignals: entryEpisodes(book) };
}

// ---------------------------------------------------------------------------
// Metrics (analytics.py) and benchmarks (portfolio.py)
// ---------------------------------------------------------------------------

export function maxDrawdown(equity) {
  let peak = -Infinity, worst = 0;
  for (const v of equity) { peak = Math.max(peak, v); worst = Math.min(worst, v / peak - 1); }
  return equity.length < 2 ? 0 : worst;
}

export function cagr(equity, periodsPerYear = 252) {
  if (equity.length < 2) return 0;
  const growth = equity[equity.length - 1] / equity[0];
  const years = equity.length / periodsPerYear;
  return years <= 0 || growth <= 0 ? 0 : growth ** (1 / years) - 1;
}

export function sharpe(equity, periodsPerYear = 252) {
  const returns = [];
  for (let i = 1; i < equity.length; i++) returns.push(equity[i] / equity[i - 1] - 1);
  if (returns.length < 2) return 0;
  const mean = returns.reduce((a, b) => a + b, 0) / returns.length;
  const variance = returns.reduce((a, r) => a + (r - mean) ** 2, 0) / (returns.length - 1);
  return variance === 0 ? 0 : Math.sqrt(periodsPerYear) * mean / Math.sqrt(variance);
}

export function metrics(equity, trades = []) {
  const growth = cagr(equity), dd = maxDrawdown(equity);
  return {
    totalReturn: equity[equity.length - 1] / equity[0] - 1,
    cagr: growth, maxDD: dd, sharpe: sharpe(equity), calmar: dd < 0 ? growth / Math.abs(dd) : 0,
    finalEquity: equity[equity.length - 1], trades: trades.length,
    winRate: trades.length ? trades.filter((t) => t.pnl > 0).length / trades.length : 0,
    avgHold: trades.length ? trades.reduce((a, t) => a + t.barsHeld, 0) / trades.length : 0,
  };
}

/** Equal-weight buy-and-hold on the engine calendar; a sleeve stays cash until its stock lists. */
export function buyAndHold(frames, calendar, startingCapital, costBps = 0) {
  const tickers = Object.keys(frames);
  const perStock = startingCapital / tickers.length;
  const cost = costBps / 10000;
  const out = new Float64Array(calendar.length);
  const lots = tickers.map((t) => {
    const bars = frames[t];
    const shares = Math.floor((perStock / (1 + cost)) / bars.close[0]);
    return { bars, shares, firstDay: bars.dates[0], spent: shares * bars.close[0] * (1 + cost), cursor: -1 };
  });
  for (let day = 0; day < calendar.length; day++) {
    let value = startingCapital;
    for (const lot of lots) {
      if (calendar[day] < lot.firstDay) continue;
      while (lot.cursor + 1 < lot.bars.dates.length && lot.bars.dates[lot.cursor + 1] <= calendar[day]) lot.cursor += 1;
      value += lot.shares * lot.bars.close[lot.cursor] - lot.spent;
    }
    out[day] = value;
  }
  return out;
}
