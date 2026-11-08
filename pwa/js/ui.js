// Small DOM + formatting helpers shared by every view. Text is always set via
// textContent (never innerHTML) so symbols typed by the user cannot inject markup.

export function h(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === null || value === undefined || value === false) continue;
    if (key === 'class') node.className = value;
    else if (key === 'text') node.textContent = value;
    else if (key.startsWith('on')) node.addEventListener(key.slice(2), value);
    else if (key === 'dataset') Object.assign(node.dataset, value);
    else node.setAttribute(key, value === true ? '' : value);
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

export const pct = (x, digits = 1) => (x === null || Number.isNaN(x) ? '—' : `${x > 0 ? '+' : ''}${x.toFixed(digits)}%`);
export const pctOf = (fraction, digits = 1) => pct(fraction * 100, digits);
export const num = (x, digits = 2) => (x === null || Number.isNaN(x) ? '—' : x.toLocaleString(undefined, {
  minimumFractionDigits: digits, maximumFractionDigits: digits }));
export const money = (x) => (x === null || Number.isNaN(x) ? '—' : x.toLocaleString(undefined, {
  style: 'currency', currency: 'USD', maximumFractionDigits: 0 }));
export const signClass = (x) => (x > 0 ? 'up' : x < 0 ? 'down' : '');

export function kpi(label, value, sub = null, cls = '') {
  return h('div', { class: 'card kpi' }, h('div', { class: 'k', text: label }),
    h('div', { class: `v ${cls}`, text: value }), sub ? h('div', { class: 's', text: sub }) : null);
}

/** A table from column specs [{label, value(row) -> string|Node, num?, cls?(row)}]. */
export function table(columns, rows, { onRow = null, rowClass = null } = {}) {
  const head = h('tr', {}, columns.map((c) => h('th', { class: c.num ? 'num' : null, text: c.label })));
  const body = rows.map((row) => h('tr', {
    class: [onRow ? 'link' : '', rowClass ? rowClass(row) : ''].join(' ').trim() || null,
    onclick: onRow ? () => onRow(row) : null,
  }, columns.map((c) => {
    const value = c.value(row);
    return h('td', { class: [c.num ? 'num' : '', c.cls ? c.cls(row) : ''].join(' ').trim() || null },
      value instanceof Node ? value : String(value));
  })));
  return h('div', { class: 'table-wrap' }, h('table', {}, h('thead', {}, head), h('tbody', {}, body)));
}

export function showBanner(message, kind = 'warn') {
  const banner = document.getElementById('banner');
  banner.textContent = message;
  banner.className = `banner ${kind === 'error' ? 'error' : ''}`;
  banner.hidden = !message;
}

export function downloadText(filename, text, type = 'text/csv') {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const link = h('a', { href: url, download: filename });
  document.body.append(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

/** localStorage that reports (instead of hiding) when the browser blocks storage. */
export const store = {
  read(key, fallback) {
    let raw;
    try { raw = localStorage.getItem(key); } catch (error) {
      showBanner('Browser storage is blocked here — your positions cannot be saved on this device.');
      return fallback;
    }
    return raw === null ? fallback : JSON.parse(raw);
  },
  write(key, value) {
    try { localStorage.setItem(key, JSON.stringify(value)); } catch (error) {
      showBanner('Could not save to browser storage — changes will be lost when you close the app.');
    }
  },
};
