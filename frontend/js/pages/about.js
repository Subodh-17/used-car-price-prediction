// @ts-check
import { api } from '../api.js';
import { html, mount } from '../dom.js';
import { formatINR, formatNumber, formatPercent } from '../format.js';
import { errorBox, header } from './_shared.js';

export async function render(root) {
  mount(root, html`${header('Methodology', 'What data the model learned from, how it was evaluated, and where it should not be trusted.')}
    <div class="bento">
      <div class="card s6"><h2>Data & preprocessing</h2><ul>
        <li>Listings from verified CarDekho-derived CSV files and a city-wise used-car dataset (all prices verified as INR).</li>
        <li>Third-party scraped listings (<code>third_listings</code>) are excluded from the released model for provenance and licensing compliance.</li>
        <li>Exact duplicates within and across sources removed; implausible prices, kilometres and years rejected with a logged reason.</li>
        <li>Outliers were <em>reviewed</em>, not deleted: expensive luxury cars are legitimate.</li>
        <li>Target-derived or unavailable columns (e.g. broker quotes, EMI, present showroom price, engineered inverse-price columns) were excluded to prevent leakage.</li>
        <li>Listing dates exist in only one historical source, so a time-based split was not possible.</li></ul></div>
      <div class="card s6" id="eval"><h2>Evaluation</h2><p class="muted">Loading…</p></div>
      <div class="card s6"><h2>Limitations</h2><ul>
        <li>Prices are listing (asking) prices, not confirmed transaction prices.</li>
        <li>The data is a mix of 2019–2022-era snapshots; the snapshot year of sources without dates is an assumption (newest model year in the file). Estimates do not reflect today’s market.</li>
        <li>Model years newer than the data are rejected rather than extrapolated.</li>
        <li>Body types present in the data are limited (see Overview). Rare makes and models have little data and are flagged.</li>
        <li>A random group split does not prove accuracy on future market conditions.</li>
        <li>Intended for educational use; not a professional valuation.</li></ul></div>
      <div class="card s6"><h2>Attribution & licences</h2><p class="small">The released training data derives strictly from approved open datasets: the Kaggle dataset <em>Vehicle dataset from CarDekho</em> (nehalbirla, DbCL v1.0) and the city-wise used-car dataset (Kaggle: sanjeetsinghnaik/used-car-information, CC0). The third-party scraped listing dataset has been excluded from release training due to marketplace scraping provenance concerns.</p>
        <p class="small muted">Check each dataset’s Kaggle page for its licence and terms before redistributing data or models. This project does not redistribute raw datasets.</p></div>
    </div>`);
  try {
    const [m, meta] = await Promise.all([api.modelMetrics(), api.metadata()]);
    const t = m.test, iv = m.interval;
    mount(root.querySelector('#eval'), html`<h2>Evaluation</h2><p class="small muted">${m.split.strategy}. ${formatNumber(m.split.n_dev)} development / ${formatNumber(m.split.n_test)} test listings; model chosen by 5-fold group cross-validation.</p>
      <dl class="kv"><dt>Selected model</dt><dd>${m.selected_model.replaceAll('_', ' ')}</dd><dt>MAE (test)</dt><dd class="num">${formatINR(t.mae_inr)}</dd><dt>RMSE (test)</dt><dd class="num">${formatINR(t.rmse_inr)}</dd><dt>R² (test)</dt><dd class="num">${t.r2.toFixed(3)}</dd>
      <dt>Median abs. % error</dt><dd class="num">${t.median_ape_pct.toFixed(1)}%</dd><dt>MAPE</dt><dd class="num">${t.mape_pct.toFixed(1)}%</dd><dt>Baseline MAE (median price)</dt><dd class="num">${formatINR(m.test_baseline_median.mae_inr)}</dd>
      <dt>80% range coverage (test, overall)</dt><dd class="num">${formatPercent(iv.test_coverage)} ${iv.validated ? '(validated)' : '(not validated – range hidden)'}</dd><dt>Trained</dt><dd>${meta.model.trained_utc.slice(0, 10)}</dd><dt>Data version</dt><dd><code>${meta.model.data_version}</code></dd></dl>
      <p class="small muted">MAPE is inflated by low-priced cars; read it with MAE and the median error.</p>`);
  } catch (e) { mount(root.querySelector('#eval'), html`<h2>Evaluation</h2>${errorBox(e)}`); }
}
