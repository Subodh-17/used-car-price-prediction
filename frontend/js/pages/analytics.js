// @ts-check
import { api } from '../api.js';
import { barChart, hBarChart, lineChart, scatterChart } from '../charts.js';
import { html, mount, raw } from '../dom.js';
import { formatINR, formatINRCompact, formatNumber } from '../format.js';
import { errorBox, header, skeleton } from './_shared.js';

/** '(10000, 25000]' -> '10–25k'; the last bucket was clipped at 250k so it reads '150k+'. */
export function kmLabel(bucket) {
  const m = /\(?\s*(-?\d+(?:\.\d+)?),\s*(\d+(?:\.\d+)?)\s*\]/.exec(bucket);
  if (!m) return bucket;
  const lo = Math.max(0, Number(m[1])), hi = Number(m[2]);
  return hi >= 250000 ? `${Math.round(lo / 1000)}k+` : lo === 0 ? `0–${Math.round(hi / 1000)}k` : `${Math.round(lo / 1000)}–${Math.round(hi / 1000)}k`;
}
const fig = (title, chart, caption) => html`<figure><h2>${title}</h2>${raw(chart)}<figcaption>${caption}</figcaption></figure>`;

export async function render(root) {
  mount(root, html`${header('Analytics', 'Charts are computed from the cleaned training dataset and the held-out test set. This is a historical dataset snapshot — not a live market feed.')}
    <div id="body" class="bento"><div class="card s12">${skeleton(200)}</div></div>`);
  const body = root.querySelector('#body');
  async function load() {
    mount(body, html`<div class="card s12">${skeleton(200)}</div>`);
    let a;
    try { a = await api.analytics(); } catch (e) { mount(body, html`<div class="card s12">${errorBox(e, 'retry')}</div>`); body.querySelector('#retry')?.addEventListener('click', load); return; }
    if (!a.n_rows) return mount(body, html`<div class="card s12 empty">No analytics available.</div>`);
    const h = a.price_histogram, lbl = h.counts.map((_, i) => formatINRCompact(h.edges[i]));
    const tx = a.transmission_breakdown, fu = a.fuel_breakdown;
    mount(body, html`
      <div class="card s7">${fig('Price distribution', barChart({ labels: lbl, values: h.counts, label: 'Histogram of listing prices', xTitle: 'Price (INR)', yTitle: 'Listings', tooltips: h.counts.map((c, i) => `${formatINR(h.edges[i])} – ${formatINR(h.edges[i + 1])}: ${formatNumber(c)} listings`) }),
        `${formatNumber(a.n_rows)} cleaned listings; prices above the 99th percentile (${formatINR(h.clipped_at_p99_inr)}) are grouped into the last bar.`)}</div>
      <div class="card s5">${fig('Fuel type', hBarChart({ items: fu.map((f) => ({ label: f.name, value: f.count })), label: 'Listings by fuel type' }), 'Number of listings.')}
        <hr style="border:0;border-top:1px solid var(--border);margin:14px 0">${fig('Transmission', hBarChart({ items: tx.map((f) => ({ label: f.name, value: f.count })), label: 'Listings by transmission' }), '“Unknown” = transmission not stated in the source data.')}</div>
      <div class="card s6">${fig('Vehicle age vs price', lineChart({ points: a.age_vs_price.map((p) => ({ x: p.age, y: p.median, lo: p.q1, hi: p.q3, tooltip: `Age ${p.age}: median ${formatINR(p.median)} (IQR ${formatINR(p.q1)}–${formatINR(p.q3)}, n=${p.n})` })), label: 'Median price by vehicle age', xTitle: 'Vehicle age (years, at valuation year)', yTitle: 'Median price' }), 'Line = median; band = interquartile range. Ages ≥25 grouped.')}</div>
      <div class="card s6">${fig('Kilometres driven vs price', barChart({ labels: a.km_vs_price.map((k) => kmLabel(k.bucket)), values: a.km_vs_price.map((k) => k.median), yFormat: formatINRCompact, label: 'Median price by kilometres bucket', xTitle: 'Kilometres driven', yTitle: 'Median price', tooltips: a.km_vs_price.map((k) => `${kmLabel(k.bucket)} km: median ${formatINR(k.median)} (n=${k.n})`) }), 'Median price per distance bucket.')}</div>
      <div class="card s6">${fig('Brand price comparison', hBarChart({ items: a.brand_median_price.slice(0, 16).map((b) => ({ label: b.make, value: b.median, tooltip: `${b.make}: median ${formatINR(b.median)} (n=${b.n})` })), valueFormat: formatINRCompact, label: 'Median price by manufacturer' }), 'Manufacturers with ≥30 listings; top 16 by median price.')}</div>
      <div class="card s6">${fig('Kilometres vs price (sample)', scatterChart({ points: a.km_price_scatter.map((p) => ({ x: p.km, y: p.price, tooltip: `${formatNumber(p.km)} km · ${formatINR(p.price)} · ${p.fuel}` })), xFormat: (v) => `${Math.round(v / 1000)}k`, label: 'Scatter of kilometres vs price', xTitle: 'Kilometres driven', yTitle: 'Price' }), 'Random sample of 1,200 listings.')}</div>
      <div class="card s7">${fig('Actual vs predicted (held-out test set)', scatterChart({ points: a.actual_vs_predicted_test.filter((p) => p.actual < 4e6).map((p) => ({ x: p.actual, y: p.predicted, tooltip: `Actual ${formatINR(p.actual)} · predicted ${formatINR(p.predicted)}` })), xFormat: formatINRCompact, identity: true, label: 'Actual versus predicted price on the test set', xTitle: 'Actual price', yTitle: 'Predicted price' }), 'Dashed line = perfect prediction. Sample of 800 test cars under ₹40L (luxury cars are omitted from the plot for readability, not from the metrics).')}</div>
      <div class="card s5"><h2>Model comparison</h2><div class="table-wrap"><table><thead><tr><th>Model</th><th>CV MAE</th><th>Test MAE</th><th>Test R²</th></tr></thead><tbody>
        ${a.model_comparison.map((m) => html`<tr><td>${m.model.replaceAll('_', ' ')}</td><td class="num">${formatINR(m.cv_mae_inr)}</td><td class="num">${m.test_mae_inr != null ? formatINR(m.test_mae_inr) : '—'}</td><td class="num">${m.test_r2 != null ? m.test_r2.toFixed(3) : '—'}</td></tr>`)}</tbody></table></div>
        <p class="small muted">Selection used cross-validated (CV) MAE on the development set only; the test set was evaluated once afterwards.</p></div>`);
  }
  await load();
}
