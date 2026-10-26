#!/usr/bin/env python
"""Train, select, calibrate and evaluate the used-car price model; writes all artifacts under ml/models and ml/reports.

    python ml/scripts/train.py [--seed 42] [--no-variant]

Protocol: group-aware 15% test holdout (untouched until the end) -> 5-fold group CV on the development set for
model/hyper-parameter selection -> refit selected pipeline on the whole development set -> out-of-fold residuals give a
log-scale conformal quantile -> single evaluation on the test set (including empirical interval coverage).
"""
from __future__ import annotations

import argparse
import json
import math
import platform
import sys
import time

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.base import clone
from sklearn.inspection import permutation_importance
from sklearn.model_selection import GridSearchCV

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ucpp import schema as S  # noqa: E402
from ucpp.features import to_model_frame  # noqa: E402
from ucpp.modeling import (build_candidates, conformal_log_quantile, group_folds, group_holdout, interval_band_index,  # noqa: E402
                           mondrian_log_quantiles, price_band, regression_metrics, segment_metrics)
from ucpp.registry import build_registry  # noqa: E402

ALPHA = 0.2   # nominal 80% prediction interval


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(ROOT / "data" / "processed" / "used_cars_clean.csv"))
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--no-variant", action="store_true", help="exclude the variant text feature")
    args = ap.parse_args()
    t0 = time.time()
    models_dir, reports_dir = ROOT / "models", ROOT / "reports"
    models_dir.mkdir(exist_ok=True); reports_dir.mkdir(exist_ok=True)
    df = pd.read_csv(args.data)
    report = json.loads((Path(args.data).parent / "cleaning_report.json").read_text())
    X_all, y_all = to_model_frame(df), df[S.TARGET].values.astype(float)
    groups = df["group_id"].values
    use_variant = not args.no_variant

    # ---- split (group-aware; test set untouched until the end)
    dev_idx, test_idx = group_holdout(groups, 0.15, args.seed)
    assert not set(groups[dev_idx]) & set(groups[test_idx])
    Xd, yd, gd = X_all.iloc[dev_idx].reset_index(drop=True), y_all[dev_idx], groups[dev_idx]
    Xt, yt = X_all.iloc[test_idx].reset_index(drop=True), y_all[test_idx]
    dft = df.iloc[test_idx].reset_index(drop=True)
    folds = group_folds(gd, 5, args.seed)
    print(f"dev={len(dev_idx)} test={len(test_idx)} groups(dev)={len(set(gd))}", flush=True)

    # ---- model selection by out-of-fold performance on the development set
    cands = build_candidates(use_variant, args.seed)
    cv_rows, tuned, errors = [], {}, {}
    for name, (pipe, grid) in cands.items():
        t = time.time()
        try:
            if grid:
                gs = GridSearchCV(pipe, grid, cv=folds, scoring="neg_mean_absolute_error", n_jobs=1, refit=False)
                gs.fit(Xd, yd)
                best = gs.best_params_
                est = clone(pipe).set_params(**best)
            else:
                best, est = {}, clone(pipe)
            oof = np.zeros(len(yd))
            for tr, va in folds:
                m = clone(est).fit(Xd.iloc[tr], yd[tr]); oof[va] = m.predict(Xd.iloc[va])
            if not np.isfinite(oof).all():
                raise ValueError("non-finite out-of-fold predictions")
            met = regression_metrics(yd, oof)
            cv_rows.append({"model": name, "best_params": {k.split("__")[-1]: v for k, v in best.items()}, **met, "fit_seconds": round(time.time() - t, 1)})
            tuned[name] = (est, oof)
            print(f"[cv] {name}: MAE=₹{met['mae_inr']:,.0f} RMSE=₹{met['rmse_inr']:,.0f} R2={met['r2']:.3f} ({time.time()-t:.0f}s)", flush=True)
        except Exception as exc:  # a candidate failing must not hide the others
            errors[name] = repr(exc); print(f"[cv] {name} FAILED: {exc!r}", flush=True)
    ranked = sorted((r for r in cv_rows if r["model"] != "median_baseline"), key=lambda r: (r["mae_inr"], r["rmse_inr"]))
    selected = ranked[0]["model"]
    print("selected:", selected, flush=True)

    # ---- refit on all development data, conformal calibration from out-of-fold residuals
    final = clone(tuned[selected][0]).fit(Xd, yd)
    band_q = mondrian_log_quantiles(yd, tuned[selected][1], ALPHA)

    # ---- one-shot test evaluation (all candidates fitted on dev for transparency; selection already made on CV)
    test_rows = {}
    for name, (est, _) in tuned.items():
        m = final if name == selected else clone(est).fit(Xd, yd)
        test_rows[name] = regression_metrics(yt, m.predict(Xt))
    pred_t = final.predict(Xt)
    if not np.isfinite(pred_t).all() or (pred_t <= 0).any():
        raise SystemExit("Final model produced non-finite or non-positive predictions on the test set")
    pb = interval_band_index(pred_t)
    qs = np.array([b["log_quantile"] for b in band_q])[pb]
    covered = np.abs(np.log(yt) - np.log(pred_t)) <= qs
    bands = np.array(price_band(yt))
    cov = float(covered.mean())
    for i, b in enumerate(band_q):
        m = pb == i
        b["test_n"] = int(m.sum())
        b["test_coverage"] = float(covered[m].mean()) if m.sum() else None
        # a band's range is only shown to users if it was validated on held-out data (enough cars and coverage within 8 points of nominal)
        b["validated"] = bool(m.sum() >= 25 and abs(b["test_coverage"] - (1 - ALPHA)) <= 0.08)
    interval = {"method": "Mondrian split-conformal on log-price: one calibrated width per PREDICTED-price band, from out-of-fold residuals (5-fold group CV on the development set)",
                "nominal_coverage": 1 - ALPHA, "bands": band_q, "n_calibration": int(len(yd)), "test_coverage": cov,
                "validated": bool(abs(cov - (1 - ALPHA)) <= 0.05),
                "validation_rule": "overall test coverage within ±5 points of nominal; each band additionally needs >=25 test cars and coverage within ±8 points to be shown"}

    # ---- segment analysis and failure cases on the test set
    seg = {"price_band": segment_metrics(dft, yt, pred_t, "", bins=list(bands), min_n=25)}
    for col in ("make", "fuel", "transmission", "body_type", "source"):
        seg[col] = segment_metrics(dft, yt, pred_t, col, min_n=25)
    age = (dft["snapshot_year"] - dft["year"]).clip(lower=0)
    seg["vehicle_age"] = segment_metrics(dft, yt, pred_t, "", bins=list(pd.cut(age, [-1, 3, 6, 10, 60], labels=["0-3 yrs", "4-6 yrs", "7-10 yrs", "11+ yrs"]).astype(str)), min_n=25)
    err = pd.DataFrame({"row_id": dft["row_id"], "source": dft["source"], "make": dft["make"], "model": dft["model_display"], "year": dft["year"],
                        "km_driven": dft["km_driven"], "fuel": dft["fuel"], "actual_inr": yt, "predicted_inr": pred_t})
    err["abs_error_inr"] = (err.predicted_inr - err.actual_inr).abs()
    err["ape_pct"] = 100 * err.abs_error_inr / err.actual_inr
    failures = err.nlargest(20, "abs_error_inr").round(1).to_dict("records")
    err.round(1).to_csv(reports_dir / "test_predictions.csv", index=False)
    split = pd.DataFrame({"row_id": df["row_id"], "split": "dev"}); split.loc[test_idx, "split"] = "test"
    split.to_csv(reports_dir / "split_assignment.csv", index=False)

    # ---- permutation importance (test set, original feature groups; model-agnostic, global)
    pi = permutation_importance(final, Xt, yt, scoring="neg_mean_absolute_error", n_repeats=3, random_state=args.seed, n_jobs=1)
    imp = sorted(({"feature": c, "mae_increase_inr": float(m), "std": float(s)} for c, m, s in zip(Xt.columns, pi.importances_mean, pi.importances_std)),
                 key=lambda r: -r["mae_increase_inr"])

    # ---- artifacts
    joblib.dump(final, models_dir / "used_car_price_model.joblib", compress=3)
    registry = build_registry(df)
    valuation_year = int(df["snapshot_year"].max())
    registry["valuation_year"] = valuation_year
    (models_dir / "vehicle_registry.json").write_text(json.dumps(registry, separators=(",", ":")), encoding="utf-8")
    bg = Xd.sample(150, random_state=args.seed); bg.to_csv(models_dir / "explain_background.csv", index=False)

    metrics = {
        "target": "price_inr (listed selling price, Indian rupees)", "units": "INR (₹)", "selected_model": selected,
        "selection_rule": "lowest out-of-fold MAE (INR) in 5-fold group CV on the development set; ties -> RMSE",
        "split": {"strategy": "group-aware random holdout (no time-based split: reliable listing dates exist for one source only)",
                  "group_key": "make|model|year|fuel|km rounded to 1000", "seed": args.seed, "n_total": int(len(df)),
                  "n_dev": int(len(dev_idx)), "n_test": int(len(test_idx)), "cv_folds": 5},
        "test": test_rows[selected], "test_baseline_median": test_rows.get("median_baseline"), "test_all_candidates": test_rows,
        "cv_candidates": cv_rows, "candidate_errors": errors, "interval": interval, "segments_test": seg,
        "permutation_importance_test": imp, "failure_cases_top20_abs_error": failures,
        "caveat": "Random group split does not demonstrate accuracy on future market conditions. Prices are 2019-2022-era listings.",
    }
    (models_dir / "model_metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")

    cat_vals = {c: sorted(df[c].dropna().unique().tolist()) or (list(S.BODY_TYPES) if c == "body_type" else []) for c in ("fuel", "transmission", "seller_type", "body_type")}
    feature_schema = {
        "pipeline_input_columns": S.PIPELINE_INPUT_COLUMNS, "categorical": S.CATEGORICAL_FEATURES if use_variant else [c for c in S.CATEGORICAL_FEATURES if c != "variant"],
        "numeric_after_age_derivation": S.NUMERIC_FEATURES, "derived": {"vehicle_age": "snapshot_year - year (snapshot_year = valuation_year at inference)"},
        "valuation_year": valuation_year, "bounds": S.BOUNDS, "allowed_values": cat_vals, "unknown_category_handling": "unseen categories are encoded as missing/'other' inside the fitted pipeline; the API additionally reports them as coverage warnings",
        "excluded_as_leakage_or_unavailable": report["leakage_exclusions"],
        "uses_variant": use_variant,
    }
    (models_dir / "feature_schema.json").write_text(json.dumps(feature_schema, indent=2), encoding="utf-8")
    meta = {"trained_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "data_version": report["data_version"], "seed": args.seed,
            "selected_estimator": selected, "estimator_params": ranked[0]["best_params"], "rows": int(len(df)), "valuation_year": valuation_year,
            "features": S.PIPELINE_INPUT_COLUMNS, "libraries": {"python": platform.python_version(), "scikit-learn": sklearn.__version__,
            "pandas": pd.__version__, "numpy": np.__version__, "joblib": joblib.__version__}, "catboost_available": "catboost" in {r["model"] for r in cv_rows},
            "training_seconds": round(time.time() - t0, 1), "artifact": "models/used_car_price_model.joblib",
            "artifact_notice": "scikit-learn pickles are version specific; load only artifacts you trained yourself (never untrusted joblib files)."}
    (models_dir / "training_metadata.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    write_model_card(models_dir / "model_card.md", metrics, meta, report, feature_schema)
    write_analytics(models_dir / "analytics.json", df, dft, yt, pred_t, metrics, valuation_year, args.seed)
    write_release_manifest(models_dir / "release_manifest.json", Path(args.data), models_dir / "used_car_price_model.joblib", metrics, meta, report)
    t = metrics["test"]; b = metrics["test_baseline_median"]
    print(f"TEST {selected}: MAE=₹{t['mae_inr']:,.0f} RMSE=₹{t['rmse_inr']:,.0f} R2={t['r2']:.3f} MedAPE={t['median_ape_pct']:.1f}% | baseline MAE=₹{b['mae_inr']:,.0f} | interval cov={cov:.3f}", flush=True)


def write_release_manifest(path: Path, data_path: Path, model_path: Path, m: dict, meta: dict, report: dict):
    import hashlib
    def file_sha256(p: Path) -> str:
        h = hashlib.sha256()
        with open(p, "rb") as f:
            while chunk := f.read(65536):
                h.update(chunk)
        return h.hexdigest()

    manifest = {
        "release_timestamp_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "release_version": meta["data_version"],
        "valuation_reference_year": meta["valuation_year"],
        "historical_market_reference": "2019-2022 historical Indian listing price levels (not current-market)",
        "approved_sources": report.get("used_inventory", [i for i in report.get("inventory", []) if i.get("used_as") not in report.get("excluded_sources", [])]),
        "excluded_sources": report.get("excluded_sources", []),
        "cleaned_dataset": {
            "path": str(data_path.name),
            "sha256": file_sha256(data_path),
            "rows_clean": meta["rows"],
        },
        "model_artifact": {
            "path": str(model_path.name),
            "sha256": file_sha256(model_path),
            "selected_estimator": meta["selected_estimator"],
            "hyperparameters": meta["estimator_params"],
        },
        "environment": {
            "python": meta["libraries"]["python"],
            "scikit_learn": meta["libraries"]["scikit-learn"],
            "pandas": meta["libraries"]["pandas"],
            "numpy": meta["libraries"]["numpy"],
            "joblib": meta["libraries"]["joblib"],
        },
        "sample_counts": {
            "total_cleaned": m["split"]["n_total"],
            "development": m["split"]["n_dev"],
            "held_out_test": m["split"]["n_test"],
            "cv_folds": m["split"]["cv_folds"],
        },
        "split_strategy": m["split"]["strategy"],
        "evaluation_held_out": {
            "mae_inr": m["test"]["mae_inr"],
            "rmse_inr": m["test"]["rmse_inr"],
            "r2": m["test"]["r2"],
            "mape_pct": m["test"]["mape_pct"],
            "median_ape_pct": m["test"]["median_ape_pct"],
            "conformal_interval_coverage": m["interval"]["test_coverage"],
            "conformal_interval_validated": m["interval"]["validated"],
        },
    }
    path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def write_model_card(path: Path, m: dict, meta: dict, report: dict, fs: dict):
    t, b, i = m["test"], m["test_baseline_median"], m["interval"]
    band_rows = "| Predicted price band | Half-width (×/÷) | Test cars | Test coverage | Shown |\n|---|---|---|---|---|\n" + "\n".join(f"| {x['name']} | {math.exp(x['log_quantile']):.3f} | {x['test_n']} | {(x['test_coverage'] or 0):.1%} | {'yes' if x['validated'] else 'no'} |" for x in i["bands"])
    rows = "\n".join(f"| {r['model']} | ₹{r['mae_inr']:,.0f} | ₹{r['rmse_inr']:,.0f} | {r['r2']:.3f} | {r['median_ape_pct']:.1f}% |" for r in m["cv_candidates"])
    path.write_text(f"""# Model card — Used Car Price Prediction

**Selected estimator:** `{m['selected_model']}` (log-price target, expm1 inverse) · trained {meta['trained_utc']} · data version `{meta['data_version']}`

## Intended use
Educational demonstration of supervised regression for used-car valuation in India. **Not** a pricing authority; estimates are
statistical approximations of 2019–2022-era *listing* prices and are not guaranteed sale prices.

## Data
{meta['rows']:,} cleaned listings (INR) from the uploaded CarDekho, city-listing and third-party archives. See `ml/data/processed/cleaning_report.json`
for sources, rejected records and unit verification. Valuation year used for age: **{meta['valuation_year']}**.

## Evaluation (held-out test set, n={m['split']['n_test']:,}; split: {m['split']['strategy']})
| Metric | Selected model | Median baseline |
|---|---|---|
| MAE (INR) | ₹{t['mae_inr']:,.0f} | ₹{b['mae_inr']:,.0f} |
| RMSE (INR) | ₹{t['rmse_inr']:,.0f} | ₹{b['rmse_inr']:,.0f} |
| R² | {t['r2']:.3f} | {b['r2']:.3f} |
| Median abs. % error | {t['median_ape_pct']:.1f}% | {b['median_ape_pct']:.1f}% |
| MAPE (see caveat) | {t['mape_pct']:.1f}% | {b['mape_pct']:.1f}% |

MAPE is inflated by low-priced vehicles (small denominators) and should be read alongside MAE and the median error.

### Cross-validation on the development set (selection basis)
| Candidate | MAE | RMSE | R² | Median APE |
|---|---|---|---|---|
{rows}

## Prediction interval
Nominal {i['nominal_coverage']:.0%} interval, calibrated separately per predicted-price band (Mondrian conformal). Overall held-out test coverage: **{i['test_coverage']:.1%}** → validated: **{i['validated']}**.

{band_rows}

The API shows a range only for bands marked validated.

## Features
{', '.join(fs['pipeline_input_columns'])}. Excluded as leakage / unavailable at inference: see `feature_schema.json`.

## Limitations
- Listing (asking) prices, not transaction prices; source markets and dates are mixed and only partly dated.
- Model years above {meta['valuation_year']} are outside coverage; estimates reflect the dataset-era market, not today's.
- Body types present in data: {', '.join(fs['allowed_values']['body_type'])}. Rare makes/models have few samples (see registry coverage warnings).
- Random group split ≠ proof of accuracy on future market conditions.
""", encoding="utf-8")


def write_analytics(path: Path, df, dft, yt, pt, m, valuation_year, seed):
    rng = np.random.default_rng(seed)
    p99 = float(df.price_inr.quantile(0.99))
    edges = np.linspace(0, p99, 31)
    h, e = np.histogram(df.price_inr.clip(upper=p99 - 1), bins=edges)
    age = (df.snapshot_year - df.year).clip(lower=0)
    ag = df.assign(age=age.clip(upper=25)).groupby("age")["price_inr"].agg(["median", lambda s: s.quantile(.25), lambda s: s.quantile(.75), "size"]); ag.columns = ["median", "q1", "q3", "n"]
    kb = pd.cut(df.km_driven.clip(upper=250_000), [-1, 10_000, 25_000, 50_000, 75_000, 100_000, 150_000, 250_000]).astype(str)
    kg = df.groupby(kb)["price_inr"].agg(["median", "size"])
    samp = df.sample(min(1200, len(df)), random_state=seed)
    brand = df.groupby("make")["price_inr"].agg(["median", "size"]); brand = brand[brand["size"] >= 30].sort_values("median", ascending=False)
    ts = rng.choice(len(yt), size=min(800, len(yt)), replace=False)
    out = {
        "scope": "Historical dataset snapshot (not a live market feed).", "n_rows": int(len(df)),
        "price_histogram": {"edges": [float(x) for x in e], "counts": [int(x) for x in h], "clipped_at_p99_inr": p99},
        "age_vs_price": [{"age": int(a), "median": float(r["median"]), "q1": float(r["q1"]), "q3": float(r["q3"]), "n": int(r["n"])} for a, r in ag.iterrows() if r["n"] >= 15],
        "km_vs_price": [{"bucket": k, "median": float(r["median"]), "n": int(r["size"])} for k, r in kg.iterrows()],
        "km_price_scatter": [{"km": float(a), "price": float(b), "fuel": f} for a, b, f in zip(samp.km_driven, samp.price_inr, samp.fuel)],
        "fuel_breakdown": [{"name": k, "count": int(v)} for k, v in df.fuel.value_counts().items()],
        "transmission_breakdown": [{"name": k, "count": int(v)} for k, v in df.transmission.fillna("Unknown").value_counts().items()],
        "brand_median_price": [{"make": k, "median": float(r["median"]), "n": int(r["size"])} for k, r in brand.iterrows()],
        "model_comparison": [{"model": r["model"], "cv_mae_inr": r["mae_inr"], "cv_rmse_inr": r["rmse_inr"], "cv_r2": r["r2"],
                              "test_mae_inr": m["test_all_candidates"].get(r["model"], {}).get("mae_inr"), "test_r2": m["test_all_candidates"].get(r["model"], {}).get("r2")} for r in m["cv_candidates"]],
        "actual_vs_predicted_test": [{"actual": float(yt[i]), "predicted": float(pt[i])} for i in ts],
        "valuation_year": valuation_year,
    }
    path.write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")


if __name__ == "__main__":
    main()
