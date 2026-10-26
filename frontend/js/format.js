// @ts-check
/** Indian-rupee formatting helpers. Machine values are plain numeric INR; formatting happens only for display. */

const inr = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 });
const num = new Intl.NumberFormat('en-IN', { maximumFractionDigits: 0 });
const num1 = new Intl.NumberFormat('en-IN', { maximumFractionDigits: 1 });

/** @param {number} value @returns {string} e.g. 345000 -> "₹3,45,000" */
export function formatINR(value) {
  if (typeof value !== 'number' || !Number.isFinite(value)) throw new TypeError('formatINR expects a finite number');
  return inr.format(value).replace(/\u00a0/g, '');
}

/** Compact axis label: 85000 -> "₹85K", 345000 -> "₹3.5L", 12500000 -> "₹1.25Cr". */
export function formatINRCompact(value) {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '–';
  const abs = Math.abs(value), sign = value < 0 ? '-' : '';
  const trim = (n, d) => Number(n.toFixed(d)).toString();
  if (abs >= 1e7) return `${sign}₹${trim(abs / 1e7, 2)}Cr`;
  if (abs >= 1e5) return `${sign}₹${trim(abs / 1e5, 1)}L`;
  if (abs >= 1e3) return `${sign}₹${trim(abs / 1e3, 0)}K`;
  return `${sign}₹${trim(abs, 0)}`;
}

/** @param {number} v */ export const formatNumber = (v) => (Number.isFinite(v) ? num.format(v) : '–');
/** @param {number} v */ export const formatNumber1 = (v) => (Number.isFinite(v) ? num1.format(v) : '–');
/** @param {number} v fraction 0..1 */ export const formatPercent = (v, d = 1) => (Number.isFinite(v) ? `${(v * 100).toFixed(d)}%` : '–');

/** Signed rupee effect: +₹1,20,000 / −₹35,000 */
export function formatSignedINR(value) {
  const s = formatINR(Math.abs(value));
  return value > 0 ? `+${s}` : value < 0 ? `−${s}` : s;
}
