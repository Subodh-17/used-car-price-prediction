# Used Car Price Prediction System Using Machine Learning

Estimates used-car resale prices in **Indian rupees (₹)** with a supervised regression model trained on real Indian listing data, served by a
FastAPI backend and a responsive Bento-grid web app (minimal, restrained glass, light/dark, reduced-motion aware).
An estimate is a statistical approximation of historical **listing** prices — not a guaranteed sale price.

## Measured results (held-out test set, n = 2,045, group-aware random split, seed 42)
| | Selected model (`hist_gradient_boosting`, log-price target) | Median-price baseline |
|---|---|---|
| MAE | **₹1,29,034** | ₹4,84,810 |
| RMSE | **₹6,33,967** | ₹11,80,077 |
| R² | **0.692** | −0.067 |
| Median abs. % error / MAPE | 11.2 % / 15.9 % (MAPE is inflated by cheap cars) | 46.0 % / 85.8 % |

Cross-validated (5-fold group CV on the 11,585-listing development set, used for selection) MAE: HistGradientBoosting ₹1,32,188 · Linear Regression ₹1,56,523 · Random Forest ₹1,68,260 · baseline ₹5,18,328.
CatBoost was **not evaluated** (not installable offline; `train.py` evaluates it automatically if `catboost` is installed).
The 80 % prediction range is calibrated per predicted-price band (Mondrian conformal) and validated on the test set: overall coverage 80.8 %; all 5 price bands validated
(< ₹3L 81.7 %, ₹3–6L 79.4 %, ₹6–10L 81.0 %, ₹10–20L 81.8 %, ≥ ₹20L 82.9 %).
Error is larger in rupees for expensive cars (MAE ₹6.3 L for ₹20–50 L cars, ₹22 L for ≥ ₹50 L); full segment tables and failure cases are in `ml/models/model_metrics.json`.
A random split does **not** prove accuracy on future market conditions.

### Dataset Release Note (13,630 Approved Records)
The released model is trained strictly on **13,630 cleaned listings** from approved, open-licensed sources (CarDekho DbCL v1.0 and CC0 city listings).
The third-party scraped dataset (`Used_Car_Price_Prediction.csv`, 7,391 rows, bringing total unconstrained rows to 21,029) was excluded from release training due to marketplace web-scraping provenance concerns. The resulting performance change (test MAE ₹1,29,034 vs ₹91,937 on the 21k mixed set) is reported honestly and without data manipulation. See [docs/DATA_AND_LICENSES.md](docs/DATA_AND_LICENSES.md).

## Repository & Deployment Links
* **GitHub Repository**: [https://github.com/Subodh-17/used-car-price-prediction](https://github.com/Subodh-17/used-car-price-prediction)
* **API Documentation**: `/api/docs` (interactive Swagger UI) and `/api/openapi.json`
* **Live Deployment**: Follow the Render deployment instructions below. Once deployed, the live service URL will be accessible via your Render service domain (e.g., `https://used-car-price-prediction.onrender.com`).

## Architecture
```
ml/ucpp/        shared library: units, cleaning, features, modelling, registry
ml/scripts/     ingest.py → validate_data.py → train.py → evaluate.py ; predict.py (CLI)
ml/models/      used_car_price_model.joblib (620 KB), model_metrics.json, feature_schema.json,
                model_card.md, training_metadata.json, release_manifest.json,
                vehicle_registry.json (coverage), analytics.json, explain_background.csv
backend/app/    FastAPI (api/, schemas/, services/model_service.py, services/history.py)
frontend/       dependency-free ES-module SPA (Bento Grid, Glassmorphic styling, no build step, bespoke SVG charts)
render.yaml     Render Blueprint infrastructure-as-code specification
Dockerfile      Containerized production deployment definition (Python 3.11-slim)
```
The API loads the fitted pipeline **once** at start-up; no encoder is fitted at request time. Missing artifacts ⇒ HTTP 503 `model_unavailable` (never a fake price).

## Setup
Python ≥ 3.10 (developed on 3.12) and Node ≥ 20 (only for frontend unit tests/config).
```bash
python -m venv .venv && source .venv/bin/activate        # Windows: py -m venv .venv ; .venv\Scripts\activate
pip install -r backend/requirements-dev.txt               # optional: pip install catboost
```

## Dataset download
Datasets are **not** bundled and no download is attempted by the code. Download from Kaggle (account required) and drop the zips (or CSVs) in `ml/data/raw/`:
* https://www.kaggle.com/datasets/nehalbirla/vehicle-dataset-from-cardekho (CarDekho; 4 CSVs; Database Contents License v1.0)
* https://www.kaggle.com/datasets/sanjeetsinghnaik/used-car-information (city listings; `UsedCars_Combined.csv`; CC0: Public Domain)
* `Used_Car_Price_Prediction.csv`: Identified on Kaggle as *True Value Cars Dataset* (listed as CC0), but contains web-scraped fields from Indian portal listings (2021–2022); can be safely excluded with `--exclude-source third_listings` without breaking the pipeline. See [docs/DATA_AND_LICENSES.md](docs/DATA_AND_LICENSES.md).

Sources are recognised by the CSV file names inside, so the Kaggle zip names do not matter.

## Pipeline (reproducible release; seed 42)
```bash
python ml/scripts/ingest.py --raw-dir ml/data/raw --exclude-source third_listings   # approved sources (13,630 clean rows)
python ml/scripts/validate_data.py                                                  # schema/unit/range/duplicate/leakage checks (exit 1 on failure)
python ml/scripts/train.py                                                          # ~5 min on 1 CPU: split, CV selection, calibration, test evaluation, release manifest
python ml/scripts/evaluate.py                                                       # independent re-evaluation of the saved model on the held-out split
python ml/scripts/predict.py --make "Maruti Suzuki" --model Swift --year 2016 --km 45000 --fuel Petrol --transmission Manual
```
Design notes: all targets are verified-INR (`ml/ucpp/units.py` only converts lakhs after verification); target-derived/platform columns are excluded; near-duplicate listings share a
group id so they never straddle train/test; preprocessing lives inside one scikit-learn `Pipeline` (age derivation → imputation/encoding → `TransformedTargetRegressor(log1p/expm1)`);
unseen categories encode to missing and are additionally reported as API warnings. `scikit-learn` pickles are version specific — retrain after upgrading, and **only load artifacts you trained** (joblib executes code on load).

## Run the app

From the repository root (recommended):
```bash
uvicorn backend.app.main:app --host 0.0.0.0 --port 8000
```
Or from the backend directory:
```bash
cd backend && uvicorn app.main:app --host 0.0.0.0 --port 8000
```
This single process serves both the FastAPI API endpoints (at `/api/...`) and the complete frontend UI (at `/`).
Open [http://localhost:8000](http://localhost:8000) in your browser. API interactive Swagger documentation is available at [http://localhost:8000/api/docs](http://localhost:8000/api/docs).

Separate frontend hosting: `cd frontend && API_BASE_URL=https://api.example.com npm run configure`, and set `CORS_ORIGINS` on the API. Copy `.env.example` for configuration
(placeholders only; set your own `HISTORY_SALT`). API reference: [docs/API.md](docs/API.md).

## Deployment on Render

This repository is pre-configured for one-click deployment on [Render](https://render.com) as a single Web Service.

### Option A: Render Blueprint (render.yaml)
1. In the Render Dashboard, click **New +** → **Blueprint**.
2. Connect your GitHub repository (`Subodh-17/used-car-price-prediction`).
3. Render reads `render.yaml` and sets up the Python web service with automatic `HISTORY_SALT` generation.
4. Click **Apply**.

### Option B: Manual Web Service
1. In the Render Dashboard, click **New +** → **Web Service**.
2. Connect your GitHub repository (`Subodh-17/used-car-price-prediction`).
3. Set the following parameters:
   * **Name**: `used-car-price-prediction`
   * **Language / Runtime**: `Python 3`
   * **Branch**: `main`
   * **Region**: Oregon (US West) or closest region
   * **Build Command**: `pip install -r requirements.txt`
   * **Start Command**: `uvicorn backend.app.main:app --host 0.0.0.0 --port $PORT`
   * **Health Check Path**: `/api/health`
4. In **Environment Variables**, add:
   * `PYTHON_VERSION`: `3.11.11`
   * `MODELS_DIR`: `ml/models`
   * `ML_DIR`: `ml`
   * `FRONTEND_DIR`: `frontend`
   * `HISTORY_DB_PATH`: `backend/data/history.sqlite3`
   * `LOG_LEVEL`: `INFO`
   * `HISTORY_SALT`: Generate a secure random string (e.g. run `python -c "import secrets; print(secrets.token_hex(32))"`)
5. Click **Create Web Service**.

## Tests
```bash
python -m unittest discover -s ml/tests -v                                 # data, units, artifact, leakage tests
cd backend && PYTHONPATH=tests python -m unittest discover -s tests -v    # service, history, API (pytest also works: pytest backend/tests ml/tests)
cd frontend && npm test && npm run check                                  # formatters, API client, charts; syntax check
```

### Verification status in the authoring environment (honest report)
| Check | Result |
|---|---|
| `validate_data.py` | 22/22 checks passed |
| `evaluate.py` | re-computed metrics match saved metrics exactly (`matches_saved_metrics: true`) |
| `ml/tests` | 22/22 passed (0 skipped) |
| `backend/tests` | 35/35 passed (0 skipped, all 8 FastAPI `TestClient` tests pass) |
| Combined `pytest` | 57/57 passed (0 skipped, 0 failed) |
| `frontend` `npm test` / `check` | 18/18 passed; syntax OK on 12 modules |
| Real-browser run (Chromium via puppeteer) | UI exercised end-to-end against the **real `ModelService`** (form, cascading selectors, validation, prediction, history, analytics, mobile width, 0 console errors) |
| **Not verified** | TypeScript type-checking / a bundler build do not apply (no-build JS with JSDoc types; `tsc` unavailable). Dockerfile untested in container engine. No automated accessibility audit (only manual keyboard/semantic design + a headless-browser run). CatBoost not evaluated (offline environment). |

## Deployment notes
Any ASGI host: install `backend/requirements.txt`, ship `backend/`, `ml/ucpp/`, `ml/models/`, `frontend/`, set `HISTORY_SALT`, `CORS_ORIGINS`, mount persistent storage for `HISTORY_DB_PATH`
(SQLite; fine for a demo, use a real database for multi-instance deployments). A starting-point `Dockerfile` is included (untested). The API has request-size limits, a prediction timeout,
JSON structured logs without request bodies, restricted CORS, and returns no stack traces or paths. There is no authentication: history is private per browser via a random id only.

## Limitations & known issues
* Data are 2019–2022-era **listing** prices; model years > 2022 are rejected; estimates do not reflect today’s used-car market.
* Sources are mixed; only one has listing dates, snapshot years for the rest are assumptions; no inflation adjustment; random (not time-based) split.
* Body types available: Hatchback, Sedan, SUV only (≈14 % unknown). Condition/rating features were excluded (platform-assigned, unavailable at inference, partially populated).
* Rare makes/models (116 of 346 models have < 5 listings and 18 of 41 makes have < 30) get limited-data warnings; luxury accuracy is poor in rupee terms (few samples).
* Feature “effects” are one-factor substitution diagnostics, **not SHAP** (not installable offline).
* The history feature stores data server-side without accounts; delete via the History page.
