// @ts-check
/** Dependency-free SVG charts. All functions return an SVG string; text is escaped; <title> provides hover tooltips. */
import { esc } from './dom.js';
import { formatINRCompact, formatNumber } from './format.js';

const W = 640, H = 320, M = { t: 16, r: 16, b: 44, l: 64 };

/** "Nice" tick values between 0 and max. @param {number} max @param {number} count */
export function niceTicks(max, count = 5) {
  if (!(max > 0)) return [0, 1];
  const raw = max / count, mag = 10 ** Math.floor(Math.log10(raw)), f = raw / mag;
  const step = (f <= 1 ? 1 : f <= 2 ? 2 : f <= 5 ? 5 : 10) * mag;
  const ticks = [];
  for (let v = 0; v <= max + step * 0.999; v += step) ticks.push(Number(v.toPrecision(12)));
  return ticks;
}

const svg = (inner, label) => `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(label)}" class="chart" preserveAspectRatio="xMidYMid meet">${inner}</svg>`;
const yAxis = (ticks, y, fmt) => ticks.map((t) => `<g><line class="grid" x1="${M.l}" x2="${W - M.r}" y1="${y(t)}" y2="${y(t)}"/><text class="tick" x="${M.l - 8}" y="${y(t) + 4}" text-anchor="end">${esc(fmt(t))}</text></g>`).join('');
const axisTitle = (x, y) => `${x ? `<text class="axis-title" x="${(M.l + W - M.r) / 2}" y="${H - 6}" text-anchor="middle">${esc(x)}</text>` : ''}${y ? `<text class="axis-title" transform="rotate(-90)" x="${-(M.t + H - M.b) / 2}" y="14" text-anchor="middle">${esc(y)}</text>` : ''}`;

/**
 * Vertical bars. @param {{labels: string[], values: number[], tooltips?: string[], yFormat?: (n:number)=>string, xTitle?: string, yTitle?: string, label: string, rotate?: boolean}} o
 */
export function barChart({ labels, values, tooltips, yFormat = formatNumber, xTitle = '', yTitle = '', label, rotate = false }) {
  if (!values.length) return '';
  const ticks = niceTicks(Math.max(...values)), top = ticks[ticks.length - 1] || 1;
  const x0 = M.l, x1 = W - M.r, y0 = H - M.b, y1 = M.t, bw = (x1 - x0) / values.length;
  const y = (v) => y0 - (v / top) * (y0 - y1);
  const bars = values.map((v, i) => `<rect class="bar" x="${(x0 + i * bw + bw * 0.12).toFixed(1)}" y="${y(v).toFixed(1)}" width="${(bw * 0.76).toFixed(1)}" height="${Math.max(0, y0 - y(v)).toFixed(1)}" rx="2"><title>${esc(tooltips?.[i] ?? `${labels[i]}: ${yFormat(v)}`)}</title></rect>`).join('');
  const step = Math.ceil(values.length / 10);
  const xl = labels.map((l, i) => (i % step ? '' : `<text class="tick" x="${(x0 + i * bw + bw / 2).toFixed(1)}" y="${y0 + 16}" text-anchor="${rotate ? 'end' : 'middle'}"${rotate ? ` transform="rotate(-30 ${(x0 + i * bw + bw / 2).toFixed(1)} ${y0 + 16})"` : ''}>${esc(l)}</text>`)).join('');
  return svg(`${yAxis(ticks, y, yFormat)}${bars}${xl}${axisTitle(xTitle, yTitle)}`, label);
}

/** Horizontal bars (rankings / breakdowns). @param {{items: {label: string, value: number, tooltip?: string}[], valueFormat?: (n:number)=>string, label: string}} o */
export function hBarChart({ items, valueFormat = formatNumber, label }) {
  if (!items.length) return '';
  const rowH = 26, labelW = 150, h = items.length * rowH + 12, max = Math.max(...items.map((i) => i.value)) || 1;
  const rows = items.map((it, i) => {
    const w = ((W - labelW - 80) * it.value) / max, y = 6 + i * rowH;
    return `<g><text class="tick" x="${labelW - 8}" y="${y + 16}" text-anchor="end">${esc(it.label)}</text><rect class="bar" x="${labelW}" y="${y + 3}" width="${Math.max(1, w).toFixed(1)}" height="${rowH - 8}" rx="2"><title>${esc(it.tooltip ?? `${it.label}: ${valueFormat(it.value)}`)}</title></rect><text class="tick" x="${(labelW + w + 6).toFixed(1)}" y="${y + 16}">${esc(valueFormat(it.value))}</text></g>`;
  }).join('');
  return `<svg viewBox="0 0 ${W} ${h}" role="img" aria-label="${esc(label)}" class="chart">${rows}</svg>`;
}

/** Line with optional shaded band. @param {{points: {x:number,y:number,lo?:number,hi?:number,tooltip?:string}[], yFormat?: (n:number)=>string, xTitle?: string, yTitle?: string, label: string}} o */
export function lineChart({ points, yFormat = formatINRCompact, xTitle = '', yTitle = '', label }) {
  if (!points.length) return '';
  const xs = points.map((p) => p.x), xmin = Math.min(...xs), xmax = Math.max(...xs);
  const ymax = Math.max(...points.map((p) => p.hi ?? p.y)), ticks = niceTicks(ymax), top = ticks[ticks.length - 1] || 1;
  const x = (v) => M.l + (xmax === xmin ? 0.5 : (v - xmin) / (xmax - xmin)) * (W - M.l - M.r), y = (v) => H - M.b - (v / top) * (H - M.b - M.t);
  const band = points[0].lo !== undefined ? `<path class="band" d="${points.map((p, i) => `${i ? 'L' : 'M'}${x(p.x).toFixed(1)},${y(p.hi).toFixed(1)}`).join('')}${[...points].reverse().map((p) => `L${x(p.x).toFixed(1)},${y(p.lo).toFixed(1)}`).join('')}Z"/>` : '';
  const line = `<path class="line" d="${points.map((p, i) => `${i ? 'L' : 'M'}${x(p.x).toFixed(1)},${y(p.y).toFixed(1)}`).join('')}"/>`;
  const dots = points.map((p) => `<circle class="dot" cx="${x(p.x).toFixed(1)}" cy="${y(p.y).toFixed(1)}" r="3.5"><title>${esc(p.tooltip ?? `${p.x}: ${yFormat(p.y)}`)}</title></circle>`).join('');
  const xl = points.filter((_, i) => i % Math.ceil(points.length / 10) === 0).map((p) => `<text class="tick" x="${x(p.x).toFixed(1)}" y="${H - M.b + 16}" text-anchor="middle">${esc(p.x)}</text>`).join('');
  return svg(`${yAxis(ticks, y, yFormat)}${band}${line}${dots}${xl}${axisTitle(xTitle, yTitle)}`, label);
}

/** Scatter. @param {{points: {x:number,y:number,tooltip?:string}[], xFormat?: (n:number)=>string, yFormat?: (n:number)=>string, xTitle?: string, yTitle?: string, identity?: boolean, label: string}} o */
export function scatterChart({ points, xFormat = formatNumber, yFormat = formatINRCompact, xTitle = '', yTitle = '', identity = false, label }) {
  if (!points.length) return '';
  const xt = niceTicks(Math.max(...points.map((p) => p.x))), yt = niceTicks(Math.max(...points.map((p) => p.y)));
  const xtop = xt[xt.length - 1] || 1, ytop = yt[yt.length - 1] || 1;
  const x = (v) => M.l + (v / xtop) * (W - M.l - M.r), y = (v) => H - M.b - (v / ytop) * (H - M.b - M.t);
  const xl = xt.map((t) => `<text class="tick" x="${x(t).toFixed(1)}" y="${H - M.b + 16}" text-anchor="middle">${esc(xFormat(t))}</text>`).join('');
  const idl = identity ? `<line class="identity" x1="${x(0)}" y1="${y(0)}" x2="${x(Math.min(xtop, ytop))}" y2="${y(Math.min(xtop, ytop))}"/>` : '';
  const dots = points.map((p) => `<circle class="pt" cx="${x(p.x).toFixed(1)}" cy="${y(p.y).toFixed(1)}" r="2.6"><title>${esc(p.tooltip ?? `${xFormat(p.x)}, ${yFormat(p.y)}`)}</title></circle>`).join('');
  return svg(`${yAxis(yt, y, yFormat)}${xl}${idl}${dots}${axisTitle(xTitle, yTitle)}`, label);
}
