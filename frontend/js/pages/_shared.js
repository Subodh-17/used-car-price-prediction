// @ts-check
import { html } from '../dom.js';

export const ICON_EMPTY = html`<svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><path d="M3 17l2-6h14l2 6v3H3z"/><circle cx="7.5" cy="17" r="1.5"/><circle cx="16.5" cy="17" r="1.5"/></svg>`;

/** Friendly error box. @param {any} err @param {string} [retryId] */
export function errorBox(err, retryId) {
  const service = err?.kind === 'service' || err?.code === 'network_error';
  return html`<div class="alert error-box" role="alert"><strong>${service ? 'Service unavailable' : 'Something went wrong'}</strong>
    ${err?.message ?? 'Unexpected error.'}${service ? ' The prediction service may be offline or the model has not been trained yet (see README).' : ''}
    ${retryId ? html`<div style="margin-top:8px"><button class="btn secondary" type="button" id="${retryId}">Try again</button></div>` : ''}</div>`;
}
export const skeleton = (h = 120) => html`<div class="skeleton" style="height:${h}px" aria-hidden="true"></div><span class="muted small">Loading…</span>`;
export const header = (title, lead) => html`<div class="page-head"><h1>${title}</h1><p class="muted">${lead}</p></div>`;
