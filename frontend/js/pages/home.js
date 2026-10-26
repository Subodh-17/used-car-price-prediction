// @ts-check
import { api } from '../api.js';
import { html, mount } from '../dom.js';
import { formatINR, formatNumber, formatPercent } from '../format.js';
import { errorBox, skeleton } from './_shared.js';

const FEATURE_LABELS = { make: 'Make', model: 'Model', variant: 'Variant', fuel: 'Fuel type', transmission: 'Transmission', seller_type: 'Seller type', city: 'City',
  body_type: 'Body type', km_driven: 'Kilometres driven', owner_count: 'Ownership', engine_cc: 'Engine size', max_power_bhp: 'Power', mileage: 'Mileage', seats: 'Seats', vehicle_age: 'Vehicle age', year: 'Year', snapshot_year: 'Snapshot' };

export async function render(root) {
  mount(root, html`<section class="bento" aria-label="Overview">
    <div class="card accent s8"><div class="kicker">Used-car valuation · India</div>
      <h1>Estimate a used car’s resale value in rupees</h1>
      <p class="muted" style="max-width:58ch">A supervised machine-learning regression model, trained on thousands of real Indian used-car listings, estimates a price from the make, model, age, kilometres and other details you provide.</p>
      <p><a class="btn" href="#/estimate">Estimate a vehicle →</a> <a class="btn secondary" href="#/about">How it works</a></p>
      <p class="small muted">An estimate is not a guaranteed sale price. It reflects historical listing data, not a live market feed.</p></div>
    <div class="card s4" id="perf" aria-live="polite"><div class="kicker">Measured performance</div>${skeleton(150)}</div>
    <div class="card s4"><h2>How a valuation works</h2><ol class="steps">
      <li><span><strong>You describe the car</strong><br><span class="muted small">Make, model, year, kilometres, fuel, transmission and optional details.</span></span></li>
      <li><span><strong>Coverage is checked</strong><br><span class="muted small">Vehicles the model never saw are reported — never silently mapped to another car.</span></span></li>
      <li><span><strong>The trained model predicts</strong><br><span class="muted small">One fitted pipeline does all encoding and scaling; nothing is retrained per request.</span></span></li></ol></div>
    <div class="card s4" id="factors"><h2>What matters most</h2>${skeleton(150)}</div>
    <div class="card s4" id="coverage"><h2>Supported vehicles</h2>${skeleton(150)}</div>
    <div class="card solid s12"><h2>Honest by design</h2><p class="muted" style="margin:0">Numbers on this page come from the model’s own evaluation files and training data. Prices are historical <em>listing</em> prices from 2019–2022-era datasets; model years newer than the data are not supported.</p></div></section>`);

  const set = (id, tpl) => mount(root.querySelector(id), tpl);
  const [m, meta] = await Promise.allSettled([api.modelMetrics(), api.metadata()]);
  if (m.status === 'fulfilled') {
    const t = m.value.test, b = m.value.test_baseline_median, iv = m.value.interval;
    set('#perf', html`<div class="kicker">Measured performance</div><div class="stat">${formatINR(t.mae_inr)}</div><div class="stat-label">average absolute error on ${formatNumber(t.n)} held-out listings</div>
      <div class="stats"><div><div class="stat" style="font-size:1.3rem">${t.r2.toFixed(2)}</div><div class="stat-label">R²</div></div>
      <div><div class="stat" style="font-size:1.3rem">${t.median_ape_pct.toFixed(1)}%</div><div class="stat-label">median % error</div></div></div>
      <p class="small muted" style="margin-top:10px">Median-price baseline: ${formatINR(b.mae_inr)} error. Model: <code>${m.value.selected_model}</code>.${iv.validated ? ` 80% range covered ${formatPercent(iv.test_coverage)} of test cars.` : ''}</p>`);
    const imp = m.value.permutation_importance_test.filter((f) => f.mae_increase_inr > 0).slice(0, 6);
    set('#factors', html`<h2>What matters most</h2><p class="small muted">Increase in test error when a feature is shuffled (permutation importance).</p>
      <ol class="chips" style="flex-direction:column;align-items:stretch;gap:6px">${imp.map((f) => html`<li class="chip" style="display:flex;justify-content:space-between"><span>${FEATURE_LABELS[f.feature] ?? f.feature}</span><span class="num muted">+${formatINR(f.mae_increase_inr)}</span></li>`)}</ol>`);
  } else {
    set('#perf', html`<div class="kicker">Measured performance</div>${errorBox(m.reason)}`);
    set('#factors', html`<h2>What matters most</h2><p class="muted">Unavailable until the service is reachable.</p>`);
  }
  if (meta.status === 'fulfilled') {
    const c = meta.value.coverage;
    set('#coverage', html`<h2>Supported vehicles</h2><div class="stats"><div><div class="stat">${formatNumber(c.makes)}</div><div class="stat-label">manufacturers</div></div><div><div class="stat">${formatNumber(c.models)}</div><div class="stat-label">models</div></div><div><div class="stat">${formatNumber(c.rows)}</div><div class="stat-label">training listings</div></div></div>
      <p class="small muted" style="margin-top:10px">Model years ${c.year_range[0]}–${c.year_range[1]}. Fuel: ${c.fuels.join(', ')}. Body types in data: ${c.body_types.join(', ')}.</p>`);
  } else set('#coverage', html`<h2>Supported vehicles</h2>${errorBox(meta.reason)}`);
}
