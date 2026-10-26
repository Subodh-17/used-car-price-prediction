# API reference

Base URL (local): `http://localhost:8000`. Interactive OpenAPI docs: `/api/docs` (FastAPI). All prices are **numeric INR** (rupees, JSON numbers) —
formatting such as `₹3,45,000` is done only in the frontend.

Errors always use one envelope: `{"error": {"code": "...", "message": "...", "details": {...}}}`.

| Status | `code` | Meaning |
|---|---|---|
| 422 | `validation_error` | Missing/out-of-range/unknown field (`details.fields` lists them) |
| 422 | `unsupported_vehicle` | Make/model not in the training data (never mapped to another car) |
| 422 | `year_out_of_coverage` | Year newer than the training data (see `max_year`) |
| 422 | `unsupported_value` | Unknown fuel / transmission / body type / seller type |
| 400 | `missing_client_id` | History endpoints need a valid `X-Client-Id` |
| 413 | `payload_too_large` | Body larger than `MAX_BODY_BYTES` |
| 503 | `model_unavailable` | Model artifact missing/unloadable — **no substitute prediction is ever returned** |
| 500 | `invalid_prediction` / `prediction_failed` / `internal_error` | NaN/∞/non-positive model output or internal failure (no stack traces are exposed) |
| 504 | `timeout` | Prediction exceeded `PREDICT_TIMEOUT_S` |

## `GET /api/health`
`{"status": "ok" | "model_unavailable", "model_loaded": true}` (always HTTP 200; inspect the body).

## `GET /api/metadata`
Model + coverage summary: estimator, `trained_utc`, `data_version`, `valuation_year`, library versions, row/make/model counts, supported fuels/transmissions/body types,
whether a validated prediction range exists, limits and the disclaimer.

## `GET /api/vehicle-options[?make=…[&model=…]]`
* no params → makes (with `count`, `limited`), fuels, transmissions, body types, seller types, cities (≥30 rows), bounds, `valuation_year`.
* `make` → the models of that manufacturer. * `make`+`model` → model detail incl. variants with typical fuel/transmission/engine/power/mileage/seats from the data.
Unknown make/model → 422 `unsupported_vehicle`.

## `POST /api/predict`
Request (`extra` fields are rejected):
```json
{"make":"Maruti Suzuki","model":"Swift","variant":"VDI","year":2016,"km_driven":45000,"fuel":"Diesel","transmission":"Manual",
 "owner_count":1,"body_type":null,"engine_cc":1248,"max_power_bhp":74,"mileage":22.9,"seats":5,"city":null,"seller_type":null}
```
Required: `make, model, year, km_driven, fuel, transmission`. Bounds: year 1980–`valuation_year`, km 0–1,000,000, owners 1–4 (4 = “4 or more”), engine 300–9000 cc,
power 15–1500 bhp, mileage 2–60, seats 2–14. Optional header `X-Client-Id` (UUID) saves the result to that browser’s history.

Response (abridged; values illustrative):
```json
{"estimated_price_inr": 463535,
 "interval": {"low_inr": 378338, "high_inr": 567919, "nominal_coverage": 0.8, "empirical_test_coverage": 0.796, "price_band": "₹3–6L", "method": "…"},
 "interval_note": null,
 "warnings": [{"code": "variant_unseen", "message": "…"}],
 "defaults_applied": [{"field": "body_type", "value": "Hatchback", "reason": "…"}],
 "inputs_used": {"make": "Maruti Suzuki", "model": "swift", "…": "…"},
 "explanation": {"method": "one-factor substitution against typical training listings", "effects": [{"factor": "Make & model", "effect_inr": -43750}], "note": "…"},
 "model": {"estimator": "hist_gradient_boosting", "data_version": "…", "trained_utc": "…", "valuation_year": 2022, "historical_reference_year": 2022, "is_historical": true, "valuation_reference_note": "…"},
 "disclaimer": "…", "saved_to_history": true}
```
`interval` is `null` (with an explanatory `interval_note`) unless that price band’s range validated on held-out data. `explanation` is **not SHAP**: each effect is
`estimate − mean estimate when that factor is replaced by values from typical training listings`; effects interact and do not sum to the estimate.
Warning codes: `limited_make_data`, `limited_model_data`, `limited_variant_data`, `variant_unseen`, `city_unsupported`, `fuel_unseen_for_model`, `transmission_unseen_for_model`,
`year_outside_model_range`, `km_above_typical`, `km_per_year_high`, `high_price_band`, `extreme_price_band`.

## `GET /api/model-metrics`
Full evaluation JSON (`ml/models/model_metrics.json`): test metrics, baseline, CV table, per-band interval validation, segment metrics, permutation importance, top failure cases.

## `GET /api/analytics`
Pre-aggregated dataset analytics (`ml/models/analytics.json`) — a **historical snapshot**, not a live feed.

## `GET /api/history`, `DELETE /api/history`
Require `X-Client-Id`. Only rows whose salted-hash matches that id are returned/deleted. Stored: inputs you typed (as normalised), result, UTC timestamp, model version. No IP/name/e-mail.
