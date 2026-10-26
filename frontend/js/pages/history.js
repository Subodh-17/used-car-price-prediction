// @ts-check
import { api, getClientId } from '../api.js';
import { html, mount } from '../dom.js';
import { formatINR } from '../format.js';
import { ICON_EMPTY, errorBox, header, skeleton } from './_shared.js';

export async function render(root) {
  mount(root, html`${header('Prediction history', 'Estimates you saved in this browser. History is private to this browser (identified by a random id) and holds only the inputs, result, time and model version.')}
    <div class="card"><div id="list" aria-live="polite">${skeleton(120)}</div></div>`);
  const clientId = getClientId();
  const box = root.querySelector('#list');
  if (!clientId) return mount(box, html`<div class="empty">${ICON_EMPTY}<p>Browser storage is unavailable, so history cannot be kept.</p></div>`);
  async function load() {
    mount(box, skeleton(120));
    try {
      const { items } = await api.history(clientId);
      if (!items.length) return mount(box, html`<div class="empty">${ICON_EMPTY}<p><strong>No saved estimates yet.</strong></p><p><a class="btn" href="#/estimate">Estimate a vehicle</a></p></div>`);
      mount(box, html`<div class="table-wrap"><table><caption class="small muted" style="text-align:left;padding-bottom:8px">Newest first · numeric INR values from the API, formatted for display</caption>
        <thead><tr><th>When (UTC)</th><th>Vehicle</th><th>Year</th><th>Km</th><th>Estimate</th><th>Range</th></tr></thead><tbody>
        ${items.map((i) => html`<tr><td>${i.created_utc.replace('T', ' ')}</td><td>${i.inputs.make} ${i.inputs.model}${i.inputs.variant ? ` ${i.inputs.variant}` : ''}</td><td class="num">${i.inputs.year}</td><td class="num">${Math.round(i.inputs.km_driven).toLocaleString('en-IN')}</td><td class="num"><strong>${formatINR(i.estimated_price_inr)}</strong></td><td class="num muted">${i.low_inr ? `${formatINR(i.low_inr)} – ${formatINR(i.high_inr)}` : '—'}</td></tr>`)}</tbody></table></div>
        <p style="margin-top:14px"><button class="btn danger" type="button" id="clear">Delete my history</button></p>`);
      box.querySelector('#clear')?.addEventListener('click', async () => {
        if (!confirm('Delete all saved estimates for this browser?')) return;
        try { await api.clearHistory(clientId); await load(); } catch (e) { mount(box, errorBox(e, 'retry')); box.querySelector('#retry')?.addEventListener('click', load); }
      });
    } catch (e) { mount(box, errorBox(e, 'retry')); box.querySelector('#retry')?.addEventListener('click', load); }
  }
  await load();
}
