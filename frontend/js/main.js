// @ts-check
import { mount, html } from './dom.js';

const routes = {
  '/': { title: 'Overview', load: () => import('./pages/home.js') },
  '/estimate': { title: 'Estimate a price', load: () => import('./pages/estimate.js') },
  '/analytics': { title: 'Analytics', load: () => import('./pages/analytics.js') },
  '/history': { title: 'Prediction history', load: () => import('./pages/history.js') },
  '/about': { title: 'Methodology', load: () => import('./pages/about.js') },
};
const root = document.getElementById('main');
let cleanup = null, token = 0;

async function navigate() {
  const path = location.hash.replace(/^#/, '') || '/';
  const route = routes[path] ?? routes['/'];
  const mine = ++token;
  cleanup?.(); cleanup = null;
  document.querySelectorAll('#nav a').forEach((a) => (a.dataset.route === (routes[path] ? path : '/') ? a.setAttribute('aria-current', 'page') : a.removeAttribute('aria-current')));
  document.title = `${route.title} · Used Car Price Prediction`;
  mount(root, html`<div class="card"><div class="skeleton" style="height:28px;width:40%"></div><p class="muted">Loading…</p></div>`);
  try {
    const page = await route.load();
    if (mine !== token) return;
    root.innerHTML = '';
    cleanup = (await page.render(root)) ?? null;
  } catch (err) {
    console.error(err);
    mount(root, html`<div class="card"><div class="alert error-box" role="alert"><strong>This page could not be displayed.</strong>Reload the page and try again.</div></div>`);
  }
  if (mine === token) { root.focus({ preventScroll: true }); window.scrollTo({ top: 0 }); }
}
window.addEventListener('hashchange', navigate);
navigate();

const themeBtn = document.getElementById('theme');
themeBtn?.addEventListener('click', () => {
  const cur = document.documentElement.dataset.theme;
  const dark = cur === 'dark' || (cur === 'auto' && matchMedia('(prefers-color-scheme: dark)').matches);
  const next = dark ? 'light' : 'dark';
  document.documentElement.dataset.theme = next;
  try { localStorage.setItem('ucp_theme', next); } catch { /* storage unavailable */ }
});
