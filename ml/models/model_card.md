# Model card — Used Car Price Prediction

**Selected estimator:** `hist_gradient_boosting` (log-price target, expm1 inverse) · trained 2026-10-26T13:17:41+00:00 · data version `c190e4a8f72a23c9`

## Intended use
Educational demonstration of supervised regression for used-car valuation in India. **Not** a pricing authority; estimates are
statistical approximations of 2019–2022-era *listing* prices and are not guaranteed sale prices.

## Data
13,630 cleaned listings (INR) from the uploaded CarDekho, city-listing and third-party archives. See `ml/data/processed/cleaning_report.json`
for sources, rejected records and unit verification. Valuation year used for age: **2022**.

## Evaluation (held-out test set, n=2,045; split: group-aware random holdout (no time-based split: reliable listing dates exist for one source only))
| Metric | Selected model | Median baseline |
|---|---|---|
| MAE (INR) | ₹129,034 | ₹484,810 |
| RMSE (INR) | ₹633,967 | ₹1,180,077 |
| R² | 0.692 | -0.067 |
| Median abs. % error | 11.2% | 46.0% |
| MAPE (see caveat) | 15.9% | 85.8% |

MAPE is inflated by low-priced vehicles (small denominators) and should be read alongside MAE and the median error.

### Cross-validation on the development set (selection basis)
| Candidate | MAE | RMSE | R² | Median APE |
|---|---|---|---|---|
| median_baseline | ₹518,328 | ₹1,323,718 | -0.062 | 50.0% |
| linear_regression | ₹156,523 | ₹629,274 | 0.760 | 12.8% |
| random_forest | ₹168,260 | ₹643,786 | 0.749 | 13.6% |
| hist_gradient_boosting | ₹132,188 | ₹595,622 | 0.785 | 11.1% |

## Prediction interval
Nominal 80% interval, calibrated separately per predicted-price band (Mondrian conformal). Overall held-out test coverage: **80.8%** → validated: **True**.

| Predicted price band | Half-width (×/÷) | Test cars | Test coverage | Shown |
|---|---|---|---|---|
| < ₹3L | 1.389 | 569 | 81.7% | yes |
| ₹3–6L | 1.221 | 734 | 79.4% | yes |
| ₹6–10L | 1.203 | 415 | 81.0% | yes |
| ₹10–20L | 1.257 | 198 | 81.8% | yes |
| ≥ ₹20L | 1.311 | 129 | 82.9% | yes |

The API shows a range only for bands marked validated.

## Features
make, model, variant, fuel, transmission, seller_type, city, body_type, year, snapshot_year, km_driven, owner_count, engine_cc, max_power_bhp, mileage, seats. Excluded as leakage / unavailable at inference: see `feature_schema.json`.

## Limitations
- Listing (asking) prices, not transaction prices; source markets and dates are mixed and only partly dated.
- Model years above 2022 are outside coverage; estimates reflect the dataset-era market, not today's.
- Body types present in data: . Rare makes/models have few samples (see registry coverage warnings).
- Random group split ≠ proof of accuracy on future market conditions.
