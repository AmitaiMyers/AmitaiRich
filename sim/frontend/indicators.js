// Technical indicators computed on the candle series (arrays aligned by candle
// index). Pure functions; a value is null until enough history exists (warmup).
// These mirror the Python indicators used by the training agent so the chart and
// the agent see the same math.

// Bollinger Bands: SMA(period) middle, ±k·population-stdev bands.
export function bollinger(closes, period, k) {
  const n = closes.length, mid = Array(n).fill(null), up = Array(n).fill(null), lo = Array(n).fill(null);
  for (let i = period - 1; i < n; i++) {
    let sum = 0;
    for (let j = i - period + 1; j <= i; j++) sum += closes[j];
    const m = sum / period;
    let v = 0;
    for (let j = i - period + 1; j <= i; j++) { const d = closes[j] - m; v += d * d; }
    const sd = Math.sqrt(v / period);
    mid[i] = m; up[i] = m + k * sd; lo[i] = m - k * sd;
  }
  return { mid, up, lo };
}

// On-Balance Volume: running sum of volume signed by close-to-close direction.
export function obv(closes, vols) {
  const n = closes.length, out = new Array(n).fill(0);
  for (let i = 1; i < n; i++) {
    const d = closes[i] - closes[i - 1];
    out[i] = out[i - 1] + (d > 0 ? vols[i] : d < 0 ? -vols[i] : 0);
  }
  return out;
}

// Wilder's ADX with +DI / -DI (period for both DI and ADX smoothing).
export function adx(highs, lows, closes, period) {
  const n = closes.length;
  const plusDI = Array(n).fill(null), minusDI = Array(n).fill(null), adxArr = Array(n).fill(null);
  if (n <= period + 1) return { adx: adxArr, plusDI, minusDI };
  const tr = new Array(n).fill(0), pDM = new Array(n).fill(0), mDM = new Array(n).fill(0);
  for (let i = 1; i < n; i++) {
    const up = highs[i] - highs[i - 1], dn = lows[i - 1] - lows[i];
    pDM[i] = up > dn && up > 0 ? up : 0;
    mDM[i] = dn > up && dn > 0 ? dn : 0;
    tr[i] = Math.max(highs[i] - lows[i], Math.abs(highs[i] - closes[i - 1]), Math.abs(lows[i] - closes[i - 1]));
  }
  // Wilder-smoothed TR / +DM / -DM, then DI and DX
  const dx = Array(n).fill(null);
  let trS = 0, pS = 0, mS = 0;
  for (let i = 1; i <= period; i++) { trS += tr[i]; pS += pDM[i]; mS += mDM[i]; }
  for (let i = period; i < n; i++) {
    if (i > period) { trS = trS - trS / period + tr[i]; pS = pS - pS / period + pDM[i]; mS = mS - mS / period + mDM[i]; }
    const pdi = trS ? 100 * pS / trS : 0, mdi = trS ? 100 * mS / trS : 0;
    plusDI[i] = pdi; minusDI[i] = mdi;
    const denom = pdi + mdi;
    dx[i] = denom ? 100 * Math.abs(pdi - mdi) / denom : 0;
  }
  // ADX = Wilder-smoothed DX
  let started = false, adxPrev = 0, count = 0, sum = 0;
  for (let i = period; i < n; i++) {
    if (dx[i] == null) continue;
    if (!started) { sum += dx[i]; count++; if (count === period) { adxPrev = sum / period; adxArr[i] = adxPrev; started = true; } }
    else { adxPrev = (adxPrev * (period - 1) + dx[i]) / period; adxArr[i] = adxPrev; }
  }
  return { adx: adxArr, plusDI, minusDI };
}
