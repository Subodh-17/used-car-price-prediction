// @ts-check
import { api, ApiError, getClientId } from '../api.js';
import { html, mount, esc } from '../dom.js';
import { formatINR, formatNumber, formatPercent, formatSignedINR } from '../format.js';
import { ICON_EMPTY, errorBox, header } from './_shared.js';

const opt = (value, label = value, sel = false) => `<option value="${esc(value)}"${sel ? ' selected' : ''}>${esc(label)}</option>`;
const OPTIONAL_NUM = [['engine_cc', 'Engine capacity', 'cc', 300, 9000], ['max_power_bhp', 'Maximum power', 'bhp', 15, 1500], ['mileage', 'Mileage', 'km/l', 2, 60], ['seats', 'Seating capacity', 'seats', 2, 14]];

export async function render(root) {
  mount(root, html`${header('Estimate a used car', 'Enter the vehicle details. Everything is sent to the trained model on the server — no price is ever generated in your browser.')}
    <div class="bento"><div class="card s7" id="form-card"><p class="muted">Loading vehicle options…</p></div>
    <div class="card s5" id="result-card" aria-live="polite" tabindex="-1"></div></div>`);
  const formCard = root.querySelector('#form-card'), resultCard = root.querySelector('#result-card');
  /** @type {AbortController|null} */ let inflight = null;
  let submitting = false;

  showEmpty();
  let options;
  try { options = await api.vehicleOptions(); } catch (e) {
    mount(formCard, html`${errorBox(e, 'retry')}`);
    formCard.querySelector('#retry')?.addEventListener('click', () => render(root));
    return;
  }
  const { bounds, valuation_year: maxYear } = options;
  mount(formCard, html`<form id="f" novalidate aria-describedby="disclaimer">
    <div id="summary" class="alert error-box" role="alert" tabindex="-1" hidden></div>
    <fieldset><legend>Vehicle</legend>
      <div class="grid2">
        <div class="field"><label for="make">Manufacturer</label><select id="make" name="make" required aria-describedby="e-make"><option value="">Select…</option>${options.makes.map((m) => html`<option value="${m.name}">${m.name}${m.limited ? ' (limited data)' : ''}</option>`)}</select><span class="error" id="e-make"></span></div>
        <div class="field"><label for="model">Model</label><select id="model" name="model" required disabled aria-describedby="e-model"><option value="">Select a manufacturer first</option></select><span class="error" id="e-model"></span></div>
      </div>
      <div class="field"><label for="variant">Variant <span class="muted">(optional)</span></label><select id="variant" name="variant" disabled aria-describedby="h-variant"><option value="">Not specified</option></select><span class="hint" id="h-variant">Choosing a variant pre-fills typical fuel, transmission and specifications from the dataset; you can edit them.</span></div>
      <div class="grid2">
        <div class="field"><label for="year">Manufacturing year</label><input id="year" name="year" type="number" inputmode="numeric" min="${bounds.year[0]}" max="${maxYear}" step="1" required aria-describedby="h-year e-year"><span class="hint" id="h-year">${bounds.year[0]}–${maxYear} (the model has no data beyond ${maxYear})</span><span class="error" id="e-year"></span></div>
        <div class="field"><label for="km_driven">Kilometres driven</label><div class="inline-unit"><input id="km_driven" name="km_driven" type="number" inputmode="numeric" min="0" max="${bounds.km_driven[1]}" step="1" required aria-describedby="e-km_driven"><span>km</span></div><span class="error" id="e-km_driven"></span></div>
        <div class="field"><label for="fuel">Fuel type</label><select id="fuel" name="fuel" required aria-describedby="e-fuel"><option value="">Select…</option>${options.fuels.map((f) => html`<option>${f}</option>`)}</select><span class="error" id="e-fuel"></span></div>
        <div class="field"><label for="transmission">Transmission</label><select id="transmission" name="transmission" required aria-describedby="e-transmission"><option value="">Select…</option>${options.transmissions.map((f) => html`<option>${f}</option>`)}</select><span class="error" id="e-transmission"></span></div>
        <div class="field"><label for="owner_count">Previous owners</label><select id="owner_count" name="owner_count"><option value="">Not specified</option><option value="1" selected>1st owner</option><option value="2">2nd owner</option><option value="3">3rd owner</option><option value="4">4th owner or more</option></select></div>
        <div class="field"><label for="city">City <span class="muted">(optional)</span></label><select id="city" name="city"><option value="">Not specified</option>${options.cities.map((c) => html`<option>${c.name}</option>`)}</select></div>
      </div></fieldset>
    <details class="more"><summary>More details (optional)</summary><div class="grid2" style="margin-top:10px">
      <div class="field"><label for="body_type">Body type</label><select id="body_type" name="body_type" aria-describedby="h-body"><option value="">Use model default</option>${options.body_types.map((b) => html`<option>${b}</option>`)}</select><span class="hint" id="h-body">Only body types present in the data are offered.</span></div>
      <div class="field"><label for="seller_type">Seller type</label><select id="seller_type" name="seller_type"><option value="">Not specified</option>${options.seller_types.map((b) => html`<option>${b}</option>`)}</select></div>
      ${OPTIONAL_NUM.map(([id, label, unit, lo, hi]) => html`<div class="field"><label for="${id}">${label}</label><div class="inline-unit"><input id="${id}" name="${id}" type="number" inputmode="decimal" min="${lo}" max="${hi}" step="any" aria-describedby="e-${id}"><span>${unit}</span></div><span class="error" id="e-${id}"></span></div>`)}
    </div></details>
    <label style="display:flex;gap:10px;align-items:center;font-weight:500"><input id="save" type="checkbox" style="width:auto;min-height:0" checked> Save this estimate to my history (stored on the server, private to this browser)</label>
    <div><button class="btn" id="go" type="submit">Estimate price</button></div>
    <p class="small muted" id="disclaimer">This is a statistical estimate, not a guaranteed sale price.</p></form>`);

  const $ = (id) => /** @type {HTMLInputElement & HTMLSelectElement} */ (root.querySelector(`#${id}`));
  const form = /** @type {HTMLFormElement} */ (root.querySelector('#f'));
  let modelDetail = null;

  $('make').addEventListener('change', async () => {
    const make = $('make').value;
    $('model').innerHTML = opt('', make ? 'Loading…' : 'Select a manufacturer first'); $('model').disabled = true; resetVariants();
    if (!make) return;
    try {
      const { models } = await api.models(make);
      $('model').innerHTML = opt('', 'Select…') + models.map((m) => opt(m.name, `${m.name}${m.limited ? ' (limited data)' : ''}`)).join('');
      $('model').disabled = false;
    } catch (e) { setError('model', e.message); $('model').innerHTML = opt('', 'Could not load models'); }
  });
  $('model').addEventListener('change', async () => {
    resetVariants();
    if (!$('model').value) return;
    try {
      modelDetail = (await api.modelDetail($('make').value, $('model').value)).model;
      $('variant').innerHTML = opt('', 'Not specified') + modelDetail.variants.map((v) => opt(v.key, v.name)).join('');
      $('variant').disabled = !modelDetail.variants.length;
      const [lo, hi] = [modelDetail.year_min, modelDetail.year_max];
      $('h-year').textContent = `${bounds.year[0]}–${maxYear}; this model appears in the data for ${lo}–${hi}`;
      if (modelDetail.fuels.length === 1) $('fuel').value = modelDetail.fuels[0];
      if (modelDetail.transmissions.length === 1) $('transmission').value = modelDetail.transmissions[0];
    } catch (e) { setError('model', e.message); }
  });
  $('variant').addEventListener('change', () => {
    const v = modelDetail?.variants.find((x) => x.key === $('variant').value);
    if (!v) return;
    if (v.fuel) $('fuel').value = v.fuel;
    if (v.transmission) $('transmission').value = v.transmission;
    for (const [id] of OPTIONAL_NUM) if (v[id] != null) $(id).value = v[id];
  });
  function resetVariants() { modelDetail = null; $('variant').innerHTML = opt('', 'Not specified'); $('variant').disabled = true; $('h-year').textContent = `${bounds.year[0]}–${maxYear} (the model has no data beyond ${maxYear})`; }

  function setError(id, msg) { const el = root.querySelector(`#e-${id}`), inp = $(id); if (el) el.textContent = msg ?? ''; inp?.setAttribute('aria-invalid', msg ? 'true' : 'false'); }
  function validate() {
    const errs = {}, v = (id) => $(id).value.trim();
    if (!v('make')) errs.make = 'Choose a manufacturer.';
    if (!v('model')) errs.model = 'Choose a model.';
    const year = Number(v('year'));
    if (!v('year') || !Number.isInteger(year)) errs.year = 'Enter a four-digit year.';
    else if (year < bounds.year[0] || year > maxYear) errs.year = `Year must be between ${bounds.year[0]} and ${maxYear}.`;
    const km = Number(v('km_driven'));
    if (v('km_driven') === '' || !Number.isFinite(km)) errs.km_driven = 'Enter the kilometres driven.';
    else if (km < 0 || km > bounds.km_driven[1]) errs.km_driven = `Kilometres must be between 0 and ${formatNumber(bounds.km_driven[1])}.`;
    if (!v('fuel')) errs.fuel = 'Choose a fuel type.';
    if (!v('transmission')) errs.transmission = 'Choose a transmission.';
    for (const [id, label, , lo, hi] of OPTIONAL_NUM) if (v(id) !== '') { const n = Number(v(id)); if (!Number.isFinite(n) || n < lo || n > hi) errs[id] = `${label} must be between ${lo} and ${hi}.`; }
    return errs;
  }
  function payload() {
    const v = (id) => $(id).value.trim(), num = (id) => (v(id) === '' ? null : Number(v(id)));
    const body = { make: v('make'), model: v('model'), variant: modelDetail?.variants.find((x) => x.key === v('variant'))?.name ?? null, year: Number(v('year')), km_driven: Number(v('km_driven')),
      fuel: v('fuel'), transmission: v('transmission'), owner_count: num('owner_count'), body_type: v('body_type') || null, engine_cc: num('engine_cc'), max_power_bhp: num('max_power_bhp'),
      mileage: num('mileage'), seats: num('seats'), city: v('city') || null, seller_type: v('seller_type') || null };
    return Object.fromEntries(Object.entries(body).filter(([, x]) => x !== null && x !== ''));
  }

  form.addEventListener('submit', async (ev) => {
    ev.preventDefault();
    if (submitting) return;                                    // prevents duplicate submissions
    const errs = validate();
    ['make', 'model', 'year', 'km_driven', 'fuel', 'transmission', ...OPTIONAL_NUM.map((o) => o[0])].forEach((id) => setError(id, errs[id]));
    const summary = root.querySelector('#summary');
    if (Object.keys(errs).length) {
      summary.hidden = false; summary.innerHTML = `<strong>Please fix ${Object.keys(errs).length} field${Object.keys(errs).length > 1 ? 's' : ''}:</strong> ${esc(Object.values(errs).join(' '))}`;
      summary.focus(); return;
    }
    summary.hidden = true;
    await submit();
  });

  async function submit() {
    submitting = true; inflight?.abort(); inflight = new AbortController();
    const btn = $('go'); btn.disabled = true; btn.innerHTML = '<span class="spinner" aria-hidden="true"></span> Estimating…';
    mount(resultCard, html`<div class="kicker">Estimate</div><div class="skeleton" style="height:56px"></div><p class="muted">Asking the model…</p>`);
    const body = payload();
    try {
      const res = await api.predict(body, { clientId: $('save').checked ? getClientId() : null, signal: inflight.signal });
      showResult(res);
    } catch (e) {
      if (inflight?.signal.aborted && !(e instanceof ApiError)) return;
      showFailure(e instanceof ApiError ? e : new ApiError('internal_error', 'Unexpected error.', 0));
    } finally { submitting = false; btn.disabled = false; btn.textContent = 'Estimate price'; }
  }

  function showEmpty() { mount(resultCard, html`<div class="empty">${ICON_EMPTY}<p><strong>Your estimate will appear here.</strong></p><p class="small">Fill in the vehicle details and press “Estimate price”.</p></div>`); }

  function showFailure(e) {
    if (e.kind === 'unsupported') {
      mount(resultCard, html`<div class="kicker">No estimate</div><div class="alert warn" role="alert"><strong>This vehicle is outside the model’s coverage</strong>${e.message}</div>
        <p class="small muted" style="margin-top:10px">The model never guesses with a different car’s data. Try a nearby model year or choose from the lists.</p>${editBtn()}`);
    } else if (e.kind === 'service') {
      mount(resultCard, html`<div class="kicker">Estimate</div>${errorBox(e, 'retry-predict')}`);
      resultCard.querySelector('#retry-predict')?.addEventListener('click', () => !submitting && submit());
    } else {
      const fields = e.details?.fields?.map((f) => `${f.field}: ${f.message}`).join('; ');
      mount(resultCard, html`<div class="kicker">Check your inputs</div><div class="alert error-box" role="alert"><strong>The server rejected some inputs</strong>${e.message} ${fields ?? ''}</div>${editBtn()}`);
    }
    wireEdit(); resultCard.focus();
  }
  const editBtn = () => html`<p style="margin-top:12px"><button type="button" class="btn secondary" data-edit>Edit vehicle details</button></p>`;
  function wireEdit() { resultCard.querySelector('[data-edit]')?.addEventListener('click', () => { $('make').scrollIntoView({ behavior: 'smooth', block: 'center' }); $('make').focus(); }); }

  function showResult(r) {
    const max = Math.max(1, ...(r.explanation?.effects ?? []).map((x) => Math.abs(x.effect_inr)));
    const u = r.inputs_used;
    mount(resultCard, html`<div class="kicker">Estimated resale value <span class="badge">Estimate · not a guaranteed price</span></div>
      <div class="estimate" id="price">${formatINR(r.estimated_price_inr)}</div>
      ${r.interval ? html`<p class="range">Likely range ${formatINR(r.interval.low_inr)} – ${formatINR(r.interval.high_inr)}<br><span class="small">${formatPercent(r.interval.nominal_coverage, 0)} range, calibrated for the ${r.interval.price_band} price band; on held-out test cars in this band it contained the true price ${formatPercent(r.interval.empirical_test_coverage)} of the time.</span></p>` : html`<p class="small muted">${r.interval_note}</p>`}
      ${r.warnings.length ? html`<ul class="alert-list" aria-label="Coverage warnings" style="margin:12px 0">${r.warnings.map((w) => html`<li class="alert warn">${w.message}</li>`)}</ul>` : ''}
      ${r.explanation ? html`<h3 style="margin-top:14px">What influenced this estimate</h3><ul class="effects">${r.explanation.effects.map((x) => html`<li class="effect"><span>${x.factor}</span><span class="track" aria-hidden="true"><span class="fill ${x.effect_inr < 0 ? 'neg' : ''}" style="left:${x.effect_inr < 0 ? 50 - (Math.abs(x.effect_inr) / max) * 50 : 50}%;width:${(Math.abs(x.effect_inr) / max) * 50}%"></span></span><span class="num">${formatSignedINR(x.effect_inr)}</span></li>`)}</ul><p class="small muted">${r.explanation.note}</p>` : ''}
      <h3 style="margin-top:14px">Inputs used</h3><dl class="kv">
        <dt>Vehicle</dt><dd>${u.make} ${modelDetail?.name ?? u.model}${u.variant ? ` · ${modelDetail?.variants.find((v) => v.key === u.variant)?.name ?? u.variant}` : ''}</dd><dt>Year / valuation baseline</dt><dd>${u.year} / ${r.model.valuation_year} (historical listing baseline)</dd><dt>Kilometres</dt><dd>${formatNumber(u.km_driven)} km</dd><dt>Fuel · transmission</dt><dd>${u.fuel} · ${u.transmission}</dd>
        ${u.owner_count ? html`<dt>Owners</dt><dd>${u.owner_count}</dd>` : ''}${u.city ? html`<dt>City</dt><dd>${u.city}</dd>` : ''}${u.body_type ? html`<dt>Body type</dt><dd>${u.body_type}${r.defaults_applied.some((d) => d.field === 'body_type') ? ' (model default)' : ''}</dd>` : ''}
        ${['engine_cc', 'max_power_bhp', 'mileage', 'seats'].filter((k) => u[k] != null).map((k) => html`<dt>${k.replace(/_/g, ' ')}</dt><dd>${u[k]}</dd>`)}</dl>
      <p class="small muted" style="margin-top:10px">${r.disclaimer} ${r.model.valuation_reference_note ?? ''} Model: ${r.model.estimator.replaceAll('_', ' ')}, data v${r.model.data_version}.${r.saved_to_history ? ' Saved to your history.' : ''}</p>${editBtn()}`);
    wireEdit(); resultCard.focus();
  }
  return () => inflight?.abort();
}
