// @ts-check
/** Tiny escaping html`` template helper: every interpolated value is escaped unless wrapped with raw(). */

const ESC = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
/** @param {unknown} s */
export const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ESC[c]);
/** @param {string} s */
export const raw = (s) => ({ __raw: s });

/** @param {TemplateStringsArray} strings @param {...any} vals @returns {{__raw: string}} */
export function html(strings, ...vals) {
  let out = '';
  strings.forEach((s, i) => {
    out += s;
    if (i < vals.length) out += render(vals[i]);
  });
  return raw(out);
}
function render(v) {
  if (v === null || v === undefined || v === false) return '';
  if (Array.isArray(v)) return v.map(render).join('');
  if (typeof v === 'object' && '__raw' in v) return v.__raw;
  return esc(v);
}
/** @param {Element} el @param {{__raw: string}} tpl */
export function mount(el, tpl) { el.innerHTML = tpl.__raw; }
